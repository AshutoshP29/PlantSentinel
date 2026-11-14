"""Analytics, asset and ingestion endpoints (Person A's functions behind the dashboard).

Paths follow the frontend client; the spec's paths (/analytics/..., /assets/{tag}/risk,
/ingest/work-orders) are registered on the same handlers.
"""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from app.analytics import dashboard, risk
from app.analytics.bad_actors import score_bad_actors
from app.analytics.cluster import recluster
from app.analytics.metrics import read_metrics
from app.config import get_settings
from app.db import connect
from app.ingestion.work_orders import ingest_work_orders, read_table

router = APIRouter(tags=["analytics"])

Window = Annotated[int, Query(ge=7, le=1095, description="window length in days (UI: 90/180/365)")]


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _asset_or_404(conn: sqlite3.Connection, tag: str) -> dict:
    row = conn.execute("SELECT * FROM assets WHERE tag = ?", (tag.upper(),)).fetchone()
    if row is None:
        raise HTTPException(404, f"Unknown asset {tag}")
    return dict(row)


# --------------------------------------------------------------------------- assets


@router.get("/assets")
def list_assets(conn: Conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM assets ORDER BY tag")]


@router.get("/assets/{tag}")
def get_asset(tag: str, conn: Conn) -> dict:
    return _asset_or_404(conn, tag)


@router.get("/assets/{tag}/work-orders")
def asset_work_orders(tag: str, conn: Conn) -> list[dict]:
    asset = _asset_or_404(conn, tag)
    rows = conn.execute(
        """SELECT w.id, w.tag, w.date, w.description, w.action_taken, w.downtime_hrs,
                  w.cost_inr, f.name AS failure_mode
           FROM work_orders w LEFT JOIN failure_modes f ON f.id = w.failure_mode_id
           WHERE w.tag = ? ORDER BY w.date DESC, w.id DESC""",
        (asset["tag"],),
    )
    return [dict(r) for r in rows]


@router.get("/risk/{tag}")
@router.get("/assets/{tag}/risk")
def asset_risk(tag: str, conn: Conn) -> dict:
    asset = _asset_or_404(conn, tag)
    if not (risk.model_path().exists() and risk.meta_path().exists()):
        raise HTTPException(
            503, "Risk model not trained. Run: uv run python scripts/train_risk_model.py"
        )
    try:
        return risk.predict_risk(asset["tag"])
    except KeyError as exc:
        raise HTTPException(404, f"No operating condition mapped for {asset['tag']}") from exc


# --------------------------------------------------------------------------- dashboard


@router.get("/bad-actors")
@router.get("/analytics/bad-actors")
def bad_actors(
    conn: Conn,
    top_n: Annotated[int, Query(ge=1, le=200)] = 10,
    window_days: Window = 180,
    flagged_only: bool = False,
) -> list[dict]:
    wo, _, _ = dashboard.load_all(conn)
    rows = score_bad_actors(conn, dashboard.resolve_as_of(wo), window_days)
    if flagged_only:
        rows = [r for r in rows if r["flagged"]]
    return rows[:top_n]


@router.get("/failure-modes")
@router.get("/analytics/failure-modes")
def failure_modes(conn: Conn, window_days: Window = 180) -> list[dict]:
    wo, _, modes = dashboard.load_all(conn)
    return dashboard.failure_mode_counts(wo, modes, dashboard.resolve_as_of(wo), window_days)


@router.get("/mtbf-trend")
def mtbf_trend(conn: Conn, months: Annotated[int, Query(ge=3, le=36)] = 12) -> list[dict]:
    wo, assets, _ = dashboard.load_all(conn)
    return dashboard.mtbf_trend(wo, len(assets), dashboard.resolve_as_of(wo), months)


@router.get("/dashboard/summary")
def summary(conn: Conn, window_days: Window = 180) -> dict:
    wo, assets, _ = dashboard.load_all(conn)
    site = get_settings().site_name
    return dashboard.summary(wo, assets, dashboard.resolve_as_of(wo), window_days, site)


# --------------------------------------------------------------------------- clustering


@router.post("/cluster")
@router.post("/analytics/recluster")
def run_clustering(conn: Conn) -> dict:
    """Re-cluster all work orders (falls back to the precomputed clusters if Ollama is down)."""
    if conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == 0:
        raise HTTPException(409, "No work orders loaded yet")
    result = recluster(conn)
    df = pd.read_sql_query("SELECT id, description FROM work_orders", conn)
    df["mode"] = df["id"].map(result.assignments).fillna("Unclassified")
    clusters = [
        {"name": name, "events": len(g), "samples": g["description"].head(3).tolist()}
        for name, g in sorted(df.groupby("mode"), key=lambda kv: -len(kv[1]))
    ]
    saved = read_metrics().get("clustering", {})
    metrics = {**saved, **{k: v for k, v in result.metrics.items() if v is not None}}
    metrics.setdefault("n_work_orders", len(df))
    metrics.setdefault("n_failure_modes", len([c for c in clusters if c["name"] != "Unclassified"]))
    metrics.setdefault("n_clusters", metrics["n_failure_modes"])
    return {"clusters": clusters, "metrics": metrics}


# --------------------------------------------------------------------------- ingestion


@router.post("/ingest/work-orders")
async def upload_work_orders(file: UploadFile, conn: Conn) -> dict:
    try:
        df = read_table(await file.read(), file.filename or "")
        return {"file": file.filename, **ingest_work_orders(conn, df)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
