"""Privacy panel and audit log.

GET  /api/privacy/status           live connections, network mode, redaction count (polled)
GET  /api/privacy/blocked          blocked tool calls, newest first
POST /api/privacy/injection-test   the injection drill as an SSE stream (agent event shape)
GET  /api/audit-log                audit_log rows, newest first
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Header, Query
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.db import connect, init_db
from app.guard.audit import AuditGuard, count_redactions, list_audit, list_blocked
from app.privacy import network
from app.privacy.injection import run_drill

router = APIRouter(tags=["privacy"])

STEP_PAUSE_S = 0.35  # lets the UI show each drill step instead of one flash


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = connect(get_settings().db_path)
    try:
        init_db(conn)  # idempotent; covers databases created before blocked_attempts existed
        yield conn
    finally:
        conn.close()


@router.get("/privacy/status")
def privacy_status() -> dict:
    with _db() as conn:
        redactions = count_redactions(conn)
    return network.snapshot(redactions)


@router.get("/privacy/blocked")
def privacy_blocked(limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    with _db() as conn:
        return list_blocked(conn, limit)


@router.get("/audit-log")
def audit_log(limit: int = Query(200, ge=1, le=1000)) -> list[dict]:
    with _db() as conn:
        return list_audit(conn, limit)


@router.post("/privacy/injection-test")
async def injection_test(
    x_user: str | None = Header(None),
    x_plant_role: str | None = Header(None),
) -> EventSourceResponse:
    """Run the injection drill. Same named events as POST /api/agent/chat."""
    user, role = x_user or "privacy-panel", x_plant_role or ""
    docs_dir = get_settings().injection_docs_dir

    async def events() -> AsyncIterator[dict]:
        with _db() as conn:
            for ev in run_drill(AuditGuard(conn), conn, docs_dir, user, role):
                yield {"event": ev["type"], "data": json.dumps(ev["data"], default=str)}
                if ev["type"] in ("tool_started", "tool_completed"):
                    await asyncio.sleep(STEP_PAUSE_S)

    return EventSourceResponse(events())
