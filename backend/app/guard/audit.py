"""The guard the API plugs into the agent: allow-list + persistent audit log.

`AuditGuard` implements the agent's `ToolGuard` hook (app.agent.tools). The allow/deny decision
is the agent's `AllowListGuard`; this adds what a plant needs afterwards: every tool call is
written to `audit_log`, every blocked call also to `blocked_attempts`, and secrets or personal
data in the logged arguments are redacted before they are stored.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime

from app.agent.tools import TOOL_SPECS, AllowListGuard, GuardDecision, _find_target

log = logging.getLogger(__name__)

MAX_FIELD_CHARS = 2000  # audit rows stay readable; full tool output is not stored

# What must not sit in an audit table in clear text. Order matters: specific before generic.
REDACTIONS: list[tuple[str, re.Pattern[str]]] = [
    (
        "secret",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization)\b"
            r"(\s*[\"']?\s*[:=]\s*[\"']?)([^\s\"',;}]+)"
        ),
    ),
    ("key", re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("phone", re.compile(r"(?<![\w.])(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\w.])")),
    ("id", re.compile(r"(?<![\w.])\d{4}[\s-]\d{4}[\s-]\d{4}(?![\w.])")),  # Aadhaar-style
]
REDACTED_MARK = "[REDACTED:"


def redact(text: str) -> tuple[str, int]:
    """Replace secrets and personal data with `[REDACTED:kind]`. Returns (text, how many)."""
    total = 0
    for kind, pattern in REDACTIONS:
        if kind == "secret":
            text, n = pattern.subn(rf"\1\2{REDACTED_MARK}secret]", text)
        else:
            text, n = pattern.subn(f"{REDACTED_MARK}{kind}]", text)
        total += n
    return text, total


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


def count_redactions(conn: sqlite3.Connection) -> int:
    """How many values the audit log is holding back (occurrences of the redaction mark)."""
    mark, n = REDACTED_MARK, len(REDACTED_MARK)
    row = conn.execute(
        "SELECT COALESCE(SUM("
        " (LENGTH(input) - LENGTH(REPLACE(input, ?, ''))) / ?"
        " + (LENGTH(output) - LENGTH(REPLACE(output, ?, ''))) / ?), 0) FROM audit_log",
        (mark, n, mark, n),
    ).fetchone()
    return int(row[0])
