import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import health
from app.db import TABLES, connect, init_db


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = connect(":memory:")
    init_db(c)
    return c


def test_all_tables_created(conn: sqlite3.Connection) -> None:
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(TABLES) <= names


def test_init_db_is_idempotent(conn: sqlite3.Connection) -> None:
    init_db(conn)


def test_criticality_check(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO assets(tag, criticality) VALUES ('P-101', 'A')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO assets(tag, criticality) VALUES ('P-102', 'Z')")


def test_foreign_keys_enforced(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO work_orders(id, tag) VALUES ('WO-1', 'NOPE')")


def test_audit_status_check(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO audit_log(status) VALUES ('blocked')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO audit_log(status) VALUES ('maybe')")


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:3b-instruct")
    assert config.Settings().llm_model == "qwen2.5:3b-instruct"


def test_health_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    config.get_settings.cache_clear()
    monkeypatch.setattr(health, "ollama_reachable", lambda: False)
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/health")
    config.get_settings.cache_clear()
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True, "ollama": False}
