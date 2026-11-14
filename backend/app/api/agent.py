"""Agent endpoints.

POST /api/agent/ask   frontend contract ({question, tag}) -> SSE, one JSON per `data:` line
POST /api/agent/chat  full agent event stream (graph.EVENT_TYPES), for tools and debugging
GET  /api/agent/status
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agent.data import normalise_tag
from app.agent.frontend_events import frontend_stream
from app.agent.graph import stream_agent
from app.agent.llm import check_ollama, get_chat_model
from app.agent.rag import ManualStore
from app.agent.tools import AgentContext, AuditSink, ToolGuard
from app.config import get_settings
from app.db import connect
from app.guard.audit import AuditGuard

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    tag: str | None = Field(None, max_length=20)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@lru_cache
def _manual_store() -> ManualStore:
    return ManualStore.from_settings()


def make_context(
    user: str = "agent",
    role: str = "",
    audit: AuditSink | None = None,
    guard: ToolGuard | None = None,
) -> AgentContext:
    """Per-request agent context.

    Every tool call goes through `guard` (default: the auditing guard, which writes audit_log
    and blocked_attempts). `audit` optionally receives the same entries as well.
    """
    s = get_settings()
    conn = connect(s.db_path)
    return AgentContext(
        conn=conn,
        guard=guard or AuditGuard(conn),
        store_factory=_manual_store,
        llm_factory=get_chat_model,
        outputs_dir=s.outputs_dir,
        user=user,
        role=role,
        audit=audit,
    )


def _with_tag(question: str, tag: str | None) -> tuple[str, str | None]:
    if not tag:
        return question, None
    try:
        tag = normalise_tag(tag)
    except ValueError:
        return question, None
    if tag.replace("-", "") in question.upper().replace("-", ""):
        return question, tag
    return f"{question}\n\n(The user is looking at asset {tag}.)", tag


@router.post("/ask")
async def ask(
    req: AskRequest,
    x_user: str | None = Header(None),
    x_plant_role: str | None = Header(None),
) -> EventSourceResponse:
    """Frontend contract: step / token / done / blocked / error events."""
    question, tag = _with_tag(req.question, req.tag)

    async def events() -> AsyncIterator[dict]:
        ctx = make_context(user=x_user or "agent", role=x_plant_role or "")
        raw = stream_agent(
            question, ctx, get_chat_model(), [t.model_dump() for t in req.history], tag=tag
        )
        try:
            async for out in frontend_stream(raw, ctx, tag):
                yield {"data": json.dumps(out, default=str)}
        finally:
            ctx.conn.close()

    return EventSourceResponse(events())


@router.post("/chat")
async def chat(
    req: ChatRequest,
    x_user: str | None = Header(None),
    x_plant_role: str | None = Header(None),
) -> EventSourceResponse:
    """Stream the agent run as server-sent events. Event names are graph.EVENT_TYPES."""

    async def events() -> AsyncIterator[dict]:
        ctx = make_context(user=x_user or "agent", role=x_plant_role or "")
        try:
            async for ev in stream_agent(
                req.message, ctx, get_chat_model(), [t.model_dump() for t in req.history]
            ):
                yield {"event": ev["type"], "data": json.dumps(ev["data"], default=str)}
        finally:
            ctx.conn.close()

    return EventSourceResponse(events())


@router.get("/status")
def status() -> dict:
    """Ollama and model readiness plus the number of indexed manual chunks."""
    ollama = check_ollama()
    try:
        chunks, store_error = _manual_store().count(), None
    except Exception as exc:  # chroma not available / not initialised
        chunks, store_error = 0, str(exc)
    return {
        "ollama": {
            "reachable": ollama.reachable,
            "host": ollama.host,
            "missing_models": ollama.missing,
            "error": ollama.error,
        },
        "manual_chunks": chunks,
        "manual_store_error": store_error,
        "ready": ollama.ready and chunks > 0,
    }
