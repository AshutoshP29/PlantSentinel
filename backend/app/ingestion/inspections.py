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

    Raises LLMUnavailableError when the vision or text model can't be used, so the seed step reports
    why instead of recording one failure per scan.
    """
    s = get_settings()
    needed = [s.vision_model, s.llm_model]  # transcription + extraction
    status = check_ollama(needed)
    if not status.ready:
        pulls = "; ".join(f"ollama pull {m}" for m in status.missing)
        raise LLMUnavailableError(
            f"models for scan reading not available ({status.error or 'run: ' + pulls})"
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
