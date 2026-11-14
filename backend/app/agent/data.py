"""Read-only queries the agent tools run against the application SQLite database.

The schema is owned by app.db; this module never writes to it.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

from app.config import get_settings

TAG_RE = re.compile(r"\b([A-Za-z])\s*-?\s*(\d{3})\b")


def normalise_tag(raw: str) -> str:
    """'p101', 'P 101', 'P-101' -> 'P-101'. Raises ValueError if it doesn't look like a tag."""
    m = TAG_RE.search(raw.strip())
    if not m:
        raise ValueError(f"'{raw}' is not an equipment tag (expected something like P-101)")
    return f"{m.group(1).upper()}-{m.group(2)}"


def as_of_date() -> date:
    return get_settings().analysis_as_of or date.today()


def get_asset(conn: sqlite3.Connection, tag: str) -> dict | None:
    row = conn.execute("SELECT * FROM assets WHERE tag = ?", (tag,)).fetchone()
    return dict(row) if row else None


def similar_tags(conn: sqlite3.Connection, tag: str, limit: int = 5) -> list[str]:
    prefix = tag.split("-")[0]
    rows = conn.execute(
        "SELECT tag FROM assets WHERE tag LIKE ? ORDER BY tag LIMIT ?", (f"{prefix}-%", limit)
    ).fetchall()
    return [r["tag"] for r in rows]


def work_orders(
    conn: sqlite3.Connection,
    tag: str,
    since: date | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Work orders for an asset, newest first, with the clustered failure mode if available."""
    sql = """
        SELECT w.id, w.date, w.description, w.action_taken, w.downtime_hrs, w.cost_inr,
               f.name AS failure_mode
        FROM work_orders w LEFT JOIN failure_modes f ON f.id = w.failure_mode_id
        WHERE w.tag = ?"""
    params: list = [tag]
    if since:
        sql += " AND w.date >= ?"
        params.append(since.isoformat())
    sql += " ORDER BY w.date DESC, w.id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def asset_totals(conn: sqlite3.Connection, since: date) -> list[dict]:
    """Per-asset work-order count, downtime and cost since a date (raw facts, no scoring)."""
    rows = conn.execute(
        """
        SELECT a.tag, a.type, a.criticality, COUNT(w.id) AS work_orders,
               ROUND(COALESCE(SUM(w.downtime_hrs), 0), 1) AS downtime_hrs,
               ROUND(COALESCE(SUM(w.cost_inr), 0), 0) AS cost_inr
        FROM assets a LEFT JOIN work_orders w ON w.tag = a.tag AND w.date >= ?
        GROUP BY a.tag ORDER BY downtime_hrs DESC, work_orders DESC""",
        (since.isoformat(),),
    ).fetchall()
    return [dict(r) for r in rows]


def window_start(days: int | None = None) -> date:
    return as_of_date() - timedelta(days=days or get_settings().analysis_window_days)
