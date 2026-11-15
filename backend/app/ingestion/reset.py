"""Clear ingested plant data so the upload step of the demo can start from empty.

Scopes:
  work_orders  work orders and their failure modes: what the Upload page can put back
  all          also the inspections (scans are read at seeding time, so re-seed afterwards)

Never touched: the equipment register, the audit log and blocked attempts (an audit trail
must survive a reset), the manual index, the risk model and generated documents.
"""

from __future__ import annotations

import sqlite3

# Child tables first, so foreign keys hold at every step.
SCOPES: dict[str, tuple[str, ...]] = {
    "work_orders": ("work_orders", "failure_modes"),
    "all": ("work_orders", "failure_modes", "inspections"),
}
KEPT = ("assets", "audit_log", "blocked_attempts", "manual index", "risk model", "documents")


def clear_data(conn: sqlite3.Connection, scope: str = "work_orders") -> dict:
    """Delete the tables in `scope` in one transaction. Returns the rows removed per table."""
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope {scope!r}; use one of {sorted(SCOPES)}")
    deleted: dict[str, int] = {}
    with conn:
        for table in SCOPES[scope]:
            deleted[table] = conn.execute(f"DELETE FROM {table}").rowcount
    return {"scope": scope, "deleted": deleted, "kept": list(KEPT)}
