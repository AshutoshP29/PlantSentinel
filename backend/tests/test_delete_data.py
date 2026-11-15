"""DELETE /api/data: engineers clear ingested data; the register and audit trail survive."""

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import config
from app.analytics import cluster
from app.db import connect, init_db
from app.ingestion.reset import clear_data
from app.ingestion.work_orders import ingest_assets, ingest_work_orders

SYN = Path(__file__).resolve().parents[2] / "data" / "synthetic"
ENGINEER = {"X-Role": "engineer", "X-User": "asha"}


def _seed(conn) -> None:
    init_db(conn)
    ingest_assets(conn, pd.read_csv(SYN / "assets.csv"))
    ingest_work_orders(conn, pd.read_csv(SYN / "work_orders.csv"))
    cluster.apply_to_db(conn, cluster.load_fallback())
    conn.execute(
        "INSERT INTO inspections(id, tag, date, file_path, raw_text, extracted_json) "
        "VALUES ('INSP-004', 'P-101', '2026-11-06', 'x.jpg', 'text', '{}')"
    )
    conn.execute("INSERT INTO audit_log(user, action, status) VALUES ('earlier', 'x', 'allowed')")
    conn.commit()


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "reset.db"
    monkeypatch.setenv("DB_PATH", str(path))
    config.get_settings.cache_clear()
    conn = connect(path)
    _seed(conn)
    conn.close()
    return path


@pytest.fixture
def client(db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def no_live_clustering(*_: object, **__: object) -> None:
        raise ConnectionError("ollama not running")

    monkeypatch.setattr("app.analytics.cluster.cluster_work_orders", no_live_clustering)
    from app.main import app

    return TestClient(app)


def test_clear_data_scopes() -> None:
    conn = connect(":memory:")
    _seed(conn)
    out = clear_data(conn, "work_orders")
    assert out["deleted"] == {"work_orders": 491, "failure_modes": 16}
    assert _count(conn, "inspections") == 1 and _count(conn, "assets") == 30
    assert clear_data(conn, "all")["deleted"]["inspections"] == 1
    assert _count(conn, "audit_log") == 1  # the trail is never cleared
    with pytest.raises(ValueError, match="Unknown scope"):
        clear_data(conn, "everything")


@pytest.mark.parametrize("headers", [{}, {"X-Role": "technician"}])
def test_non_engineers_are_refused_and_nothing_changes(client, db, headers) -> None:
    r = client.delete("/api/data", headers=headers)
    assert r.status_code == 403 and "can't clear plant data" in r.json()["detail"]
    conn = connect(db)
    assert _count(conn, "work_orders") == 491
    conn.close()


def test_engineer_clears_work_orders_and_it_is_audited(client, db) -> None:
    r = client.delete("/api/data", headers=ENGINEER)
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "work_orders"
    assert body["deleted"] == {"work_orders": 491, "failure_modes": 16}
    assert "audit_log" in body["kept"]

    conn = connect(db)
    assert _count(conn, "work_orders") == 0 and _count(conn, "failure_modes") == 0
    assert _count(conn, "inspections") == 1 and _count(conn, "assets") == 30
    row = conn.execute(
        "SELECT user, role, action, input, output, status FROM audit_log "
        "WHERE action = 'data_reset'"
    ).fetchone()
    conn.close()
    assert row["user"] == "asha" and row["role"] == "engineer" and row["status"] == "allowed"
    assert json.loads(row["input"]) == {"scope": "work_orders"}
    assert json.loads(row["output"])["work_orders"] == 491


def test_scope_all_also_clears_inspections(client, db) -> None:
    r = client.delete("/api/data", params={"scope": "all"}, headers=ENGINEER)
    assert r.json()["deleted"]["inspections"] == 1
    assert client.delete("/api/data", params={"scope": "x"}, headers=ENGINEER).status_code == 422


def test_dashboard_still_answers_on_empty_data(client) -> None:
    client.delete("/api/data", headers=ENGINEER)
    s = client.get("/api/dashboard/summary").json()
    assert s["work_orders_parsed"] == 0 and s["bad_actors_flagged"] == 0
    assert client.get("/api/bad-actors").json() == []
    assert client.get("/api/failure-modes").json() == []
    assert client.get("/api/mtbf-trend").status_code == 200
    assert client.get("/api/assets/P-101/work-orders").json() == []


def test_upload_after_clear_brings_the_story_back(client) -> None:
    client.delete("/api/data", headers=ENGINEER)
    csv = (SYN / "work_orders.csv").read_bytes()
    up = client.post(
        "/api/ingest/work-orders", files={"file": ("work_orders.csv", csv, "text/csv")}
    )
    assert up.json()["inserted"] == 491
    assert client.post("/api/cluster").json()["metrics"]["source"] == "fallback"
    top = [r["tag"] for r in client.get("/api/bad-actors", params={"top_n": 3}).json()]
    assert top == ["P-101", "C-203", "E-302"]
