"""Seeding entry point for scanned inspection reports (called by scripts/seed_demo.py).

The pipeline itself lives in app.agent.inspections (vision model -> inspections table).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.agent import inspections as pipeline
from app.agent.llm import LLMUnavailableError, check_ollama
from app.config import get_settings


def ingest_scans(
    conn: sqlite3.Connection, directory: Path | None = None, force: bool = False
) -> str:
    """Read every scan into the inspections table and return a one-line summary.

    Raises LLMUnavailableError when the vision model can't be used, so the seed step reports
    why instead of recording one failure per scan.
    """
    vision_model = get_settings().vision_model
    status = check_ollama([vision_model])
    if not status.ready:
        raise LLMUnavailableError(
            f"vision model {vision_model} not available "
            f"({status.error or 'run: ollama pull ' + vision_model})"
        )
    reports = pipeline.ingest_scans(conn, directory, force=force)
    counts = {s: sum(r.status == s for r in reports) for s in ("added", "skipped", "failed")}
    ids = ", ".join(r.inspection_id for r in reports if r.inspection_id)
    failed = "; ".join(f"{r.file}: {r.detail}" for r in reports if r.status == "failed")
    summary = (
        f"{len(reports)} scans: {counts['added']} added, {counts['skipped']} unchanged, "
        f"{counts['failed']} failed [{ids}]"
    )
    return f"{summary} ({failed})" if failed else summary
