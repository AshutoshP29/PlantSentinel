"""The guard the API plugs into the agent: allow-list + persistent audit log.

`AuditGuard` implements the agent's `ToolGuard` hook (app.agent.tools). The allow/deny decision
is the agent's `AllowListGuard`; this adds what a plant needs afterwards: every tool call is
written to `audit_log`, every blocked call also to `blocked_attempts`, and secrets or personal
data in the logged arguments are redacted before they are stored.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime

from app.agent.tools import TOOL_SPECS, AllowListGuard, GuardDecision, _find_target
from app.guard.redaction import REDACTED_MARK, redact

log = logging.getLogger(__name__)

MAX_FIELD_CHARS = 2000  # audit rows stay readable; full tool output is not stored


def _clip(value: object) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= MAX_FIELD_CHARS else text[:MAX_FIELD_CHARS] + "…"


def _loads(raw: object) -> object:
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return raw


def write_audit(conn: sqlite3.Connection, entry: dict) -> int:
    """Insert one audit row (redacted) and return its id."""
    cur = conn.execute(
        "INSERT INTO audit_log(ts, user, role, action, tool, input, output, status) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            entry.get("ts") or datetime.now().isoformat(timespec="seconds"),
            entry.get("user", ""),
            entry.get("role", ""),
            entry.get("action", "tool_call"),
            entry.get("tool", ""),
            redact(_clip(entry.get("input")))[0],
            redact(_clip(entry.get("output")))[0],
            entry.get("status", "allowed"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


class AuditGuard:
    """Allow-list guard that persists every decision. One per request (shares its connection)."""

    def __init__(self, conn: sqlite3.Connection, allowed: set[str] | None = None) -> None:
        self.conn = conn
        self.policy = AllowListGuard(allowed or {name for name, *_ in TOOL_SPECS})
        self.entries: list[dict] = []

    def check(self, tool: str, args: dict) -> GuardDecision:
        return self.policy.check(tool, args)

    def record(self, entry: dict) -> None:
        self.entries.append(entry)
        try:
            audit_id = write_audit(self.conn, entry)
            if entry.get("status") == "blocked":
                self._write_blocked(entry, audit_id)
        except sqlite3.Error:
            # The audit log must never take the agent down, but a gap must be visible.
            log.exception("audit log write failed for tool %s", entry.get("tool"))

    def _write_blocked(self, entry: dict, audit_id: int) -> None:
        tool = entry.get("tool", "")
        reason = entry.get("reason") or str(entry.get("output", "")).removeprefix("Blocked: ")
        target = entry.get("target") or _find_target(_loads(entry.get("input"))) or tool
        self.conn.execute(
            "INSERT INTO blocked_attempts(id, ts, user, tool, target, source, reason, audit_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                entry.get("blocked_id") or f"blk-{uuid.uuid4().hex[:8]}",
                entry.get("ts") or datetime.now().isoformat(timespec="seconds"),
                entry.get("user", ""),
                tool,
                _clip(target),
                _clip(entry.get("source") or "model output"),
                _clip(reason),
                audit_id,
            ),
        )
        self.conn.commit()


def list_audit(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, user, role, action, tool, input, output, status "
        "FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def list_blocked(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts AS at, tool, target, source, reason "
        "FROM blocked_attempts ORDER BY ts DESC, rowid DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


# Stored text that may hold redaction marks: (table, columns).
REDACTED_COLUMNS = (
    ("audit_log", ("input", "output")),
    ("work_orders", ("description", "action_taken")),
    ("inspections", ("raw_text", "extracted_json")),
)


def count_redactions(conn: sqlite3.Connection) -> int:
    """How many values the app is holding back: redaction marks in the audit log and in
    ingested work orders and inspection reports."""
    mark, n = REDACTED_MARK, len(REDACTED_MARK)
    total = 0
    for table, columns in REDACTED_COLUMNS:
        terms = " + ".join(
            f"(LENGTH(COALESCE({c}, '')) - LENGTH(REPLACE(COALESCE({c}, ''), ?, ''))) / ?"
            for c in columns
        )
        row = conn.execute(
            f"SELECT COALESCE(SUM({terms}), 0) FROM {table}", (mark, n) * len(columns)
        ).fetchone()
        total += int(row[0])
    return total
