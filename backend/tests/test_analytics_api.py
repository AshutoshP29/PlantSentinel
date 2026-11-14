"""Analytics/ingestion endpoints against the real synthetic data (no Ollama: clustering
falls back to the committed clusters_fallback.json)."""

import io
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import config
from app.analytics import cluster, dashboard
from app.db import connect, init_db
from app.ingestion.work_orders import ingest_assets, ingest_work_orders, normalise_work_orders

REPO = Path(__file__).resolve().parents[2]
SYN = REPO / "data" / "synthetic"


def _no_live_clustering(*_: object, **__: object) -> None:
    raise ConnectionError("ollama not running")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "api.db"
    monkeypatch.setenv("DB_PATH", str(db))
    config.get_settings.cache_clear()
    conn = connect(db)
    init_db(conn)
    ingest_assets(conn, pd.read_csv(SYN / "assets.csv"))
    ingest_work_orders(conn, pd.read_csv(SYN / "work_orders.csv"))
    cluster.apply_to_db(conn, cluster.load_fallback())
    conn.close()
    monkeypatch.setattr("app.analytics.cluster.cluster_work_orders", _no_live_clustering)
    from app.main import app

    return TestClient(app)


# ---------------------------------------------------------------- ingestion


def test_normalise_header_variants() -> None:
    raw = pd.DataFrame(
        {
            "Work Order": ["1"],
            "Equipment": ["p-101"],
            "Reported On": ["2026-03-04"],
            "Short Text": ["seal lkg"],
            "Downtime": ["5"],
        }
    )
    out = normalise_work_orders(raw)
    assert out.iloc[0]["tag"] == "P-101"
    assert out.iloc[0]["downtime_hrs"] == 5
    assert out.iloc[0]["action_taken"] is None
    with pytest.raises(ValueError, match="Missing required"):
        normalise_work_orders(pd.DataFrame({"foo": [1]}))


def test_ingest_is_idempotent_and_registers_unknown_tags() -> None:
    conn = connect(":memory:")
    init_db(conn)
    ingest_assets(conn, pd.read_csv(SYN / "assets.csv"))
    df = pd.read_csv(SYN / "work_orders.csv")
    first = ingest_work_orders(conn, df)
    assert first["inserted"] == len(df) and first["new_assets"] == []
    again = ingest_work_orders(conn, df)
    assert again["inserted"] == 0 and again["duplicates_skipped"] == len(df)

    extra = pd.DataFrame(
        [
            {"id": "X-1", "tag": "K-999", "date": "2026-01-02", "description": "new"},
            {"id": "X-2", "tag": "P-101", "date": "not a date", "description": "bad"},
        ]
    )
    res = ingest_work_orders(conn, extra, redact=lambda t: t.upper())
    assert res["inserted"] == 1 and res["rejected"] == 1 and res["new_assets"] == ["K-999"]
    row = conn.execute("SELECT description FROM work_orders WHERE id='X-1'").fetchone()
    assert row[0] == "NEW"  # redaction hook applied before storage


def test_upload_xlsx(client: TestClient) -> None:
    buf = io.BytesIO()
    pd.DataFrame(
        [{"id": "WO-9001", "tag": "P-101", "date": "2026-11-10", "description": "seal lkg"}]
    ).to_excel(buf, index=False)
    r = client.post(
        "/api/ingest/work-orders", files={"file": ("export.xlsx", buf.getvalue(), "application/x")}
    )
    assert r.status_code == 200 and r.json()["inserted"] == 1
    bad = client.post("/api/ingest/work-orders", files={"file": ("x.txt", b"a", "text/plain")})
    assert bad.status_code == 422


# ---------------------------------------------------------------- endpoints


def test_assets_and_history(client: TestClient) -> None:
    assets = client.get("/api/assets").json()
    assert len(assets) == 30 and set(assets[0]) >= {"tag", "type", "criticality"}
    assert client.get("/api/assets/p-101").json()["criticality"] == "A"
    wos = client.get("/api/assets/P-101/work-orders").json()
    assert wos[0]["date"] >= wos[-1]["date"]
    seal = [w for w in wos if w["failure_mode"] == "Mechanical Seal Leakage"]
    assert len(seal) == 9
    assert client.get("/api/assets/X-000/work-orders").status_code == 404


def test_bad_actors_story_and_windows(client: TestClient) -> None:
    rows = client.get("/api/bad-actors", params={"top_n": 3}).json()
    assert [r["tag"] for r in rows] == ["P-101", "C-203", "E-302"]
    assert rows[0]["count_180d"] == 4 and rows[0]["mtbf_drop_pct"] == pytest.approx(0.66)
    assert client.get("/api/analytics/bad-actors").json()[0]["tag"] == "P-101"  # spec alias
    year = client.get("/api/bad-actors", params={"window_days": 365, "top_n": 1}).json()
    assert year[0]["count_180d"] >= 4
    assert client.get("/api/bad-actors", params={"window_days": 0}).status_code == 422


def test_failure_modes(client: TestClient) -> None:
    modes = client.get("/api/failure-modes").json()
    names = [m["name"] for m in modes]
    assert "Routine Maintenance" not in names
    assert "Mechanical Seal Leakage" in names
    assert all(m["id"] > 0 for m in modes)
    assert [m["events"] for m in modes if not m["is_noise"]] == sorted(
        (m["events"] for m in modes if not m["is_noise"]), reverse=True
    )


def test_mtbf_trend_and_summary(client: TestClient) -> None:
    trend = client.get("/api/mtbf-trend").json()
    assert len(trend) == 12 and trend[-1]["month"] == "2026-11"
    assert all(p["mtbf_days"] > 0 for p in trend)

    s = client.get("/api/dashboard/summary").json()
    latest = pd.read_csv(SYN / "work_orders.csv")["date"].max()
    assert s["as_of"] == latest  # latest work order, not the wall clock
    assert s["assets_monitored"] == 30 and s["work_orders_parsed"] == 491
    assert s["bad_actors_flagged"] == 3
    assert s["plant_mtbf_days"] == pytest.approx(30 * 180 / s["failure_events"], abs=0.1)
    assert s["site"] == "Demo Refinery"


def test_pinned_as_of(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_AS_OF", "2026-05-01")
    config.get_settings.cache_clear()
    assert client.get("/api/dashboard/summary").json()["as_of"] == "2026-05-01"
    top = client.get("/api/bad-actors", params={"top_n": 1}).json()[0]
    assert top["count_180d"] < 4 or top["tag"] != "P-101"  # story not yet unfolded


def test_risk_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/risk/P-101").status_code == 503  # no model in tmp MODELS_DIR
    monkeypatch.setattr("app.analytics.risk.model_path", lambda: REPO / "pyproject.toml")
    monkeypatch.setattr("app.analytics.risk.meta_path", lambda: REPO / "pyproject.toml")
    monkeypatch.setattr(
        "app.analytics.risk.predict_risk", lambda tag: {"tag": tag, "risk_score": 0.99}
    )
    assert client.get("/api/assets/P-101/risk").json() == {"tag": "P-101", "risk_score": 0.99}
    assert client.get("/api/risk/Z-404").status_code == 404


def test_cluster_endpoint_falls_back(client: TestClient) -> None:
    r = client.post("/api/cluster")
    assert r.status_code == 200
    body = r.json()
    assert body["metrics"]["source"] == "fallback"
    top = {c["name"]: c for c in body["clusters"]}
    assert top["Mechanical Seal Leakage"]["events"] == 51
    assert len(top["Mechanical Seal Leakage"]["samples"]) == 3


def test_dashboard_helpers_edge_cases() -> None:
    empty = pd.DataFrame(columns=["id", "tag", "date", "cost_inr", "downtime_hrs", "failure_mode"])
    assert dashboard.plant_mtbf(0, 30, 180) is None
    assert dashboard.mtbf_trend(empty, 30, pd.Timestamp("2026-11-14")) == []
