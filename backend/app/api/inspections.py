"""Inspection reports read from scans at seeding time (see app.agent.inspections)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agent import inspections
from app.agent.data import normalise_tag
from app.config import get_settings
from app.db import connect

router = APIRouter(tags=["inspections"])


@router.get("/assets/{tag}/inspection")
def latest_inspection(tag: str) -> dict:
    """Latest inspection for an asset (frontend `Inspection` shape). 404 when there is none."""
    try:
        tag = normalise_tag(tag)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    conn = connect(get_settings().db_path)
    try:
        row = inspections.latest_inspection(conn, tag)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"No inspection for {tag}")
    return inspections.to_api(row)
