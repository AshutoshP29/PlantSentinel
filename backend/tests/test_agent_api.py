import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent.frontend_events import FrontendStream
from app.agent.rag import ingest_directory
from app.api import agent as agent_api
from app.config import get_settings
from app.main import app
from tests.agent_helpers import (
    MANUALS,
    ScriptedChatModel,
    add_inspection,
    make_context,
    memory_store,
    tool_call,
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "db_path", tmp_path / "app.db")
    monkeypatch.setattr(s, "outputs_dir", tmp_path / "outputs")
    monkeypatch.setattr(s, "analysis_as_of", date(2026, 11, 14))
    monkeypatch.setattr(s, "rag_max_distance", 1.0)
    return s


@pytest.fixture
def client(settings):
    with TestClient(app) as c:
        yield c


def parse_sse(body: str) -> list[dict]:
    """Like the frontend: one JSON per `data:` line, ignoring other lines."""
    return [
        json.loads(line[5:].strip())
        for line in body.replace("\r\n", "\n").split("\n")
        if line.startswith("data:")
    ]


def parse_named_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def p101_script() -> list:
    return [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_asset_history",
                    "args": {"tag": "P-101", "keywords": ["seal"]},
                    "id": "h1",
                },
                {"name": "read_inspection", "args": {"tag": "P-101"}, "id": "i1"},
                {
                    "name": "search_manuals",
                    "args": {"query": "seal failure misalignment"},
                    "id": "s1",
                },
            ],
        ),
        "## Finding\nSeal failures [WO-0359] follow misalignment [INSP-P101-20261102].\n"
        "## Recommended actions\n1. Align the coupling [S1, S2] and check flush [S1].",
    ]


def test_ask_matches_frontend_contract(client, tmp_path, monkeypatch) -> None:
    store = memory_store()
    ingest_directory(store, MANUALS)
    ctx = make_context(tmp_path, store)
    add_inspection(ctx.conn)
    llm = ScriptedChatModel(responses=p101_script())
    monkeypatch.setattr(agent_api, "make_context", lambda **kw: ctx)
    monkeypatch.setattr(agent_api, "get_chat_model", lambda **kw: llm)

    resp = client.post(
        "/api/agent/ask", json={"question": "Why does it keep failing?", "tag": "P-101"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    assert {e["type"] for e in events} <= {"step", "token", "done", "blocked", "error"}
    assert "(The user is looking at asset P-101.)" in llm.calls[0][-1].content

    steps = [e["step"] for e in events if e["type"] == "step"]
    assert [s["status"] for s in steps[:3]] == ["running"] * 3
    final = {s["id"]: s for s in steps}
    assert [final[i]["status"] for i in ("h1", "i1", "s1")] == ["done"] * 3
    assert final["h1"]["tool"] == "get_asset_history"
    assert "9 seal events" in final["h1"]["summary"]
    assert isinstance(final["i1"]["duration_ms"], int)

    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert text == (
        "## Finding\nSeal failures [1] follow misalignment [2].\n"
        "## Recommended actions\n1. Align the coupling [3][4] and check flush [3]."
    )
    done = events[-1]
    assert done["type"] == "done" and done["can_draft_work_order"] is True
    cites = done["citations"]
    assert [c["id"] for c in cites] == [1, 2, 3, 4]
    assert [c["kind"] for c in cites] == ["work_orders", "inspection", "manual", "manual"]
    assert cites[1]["label"] == "Inspection · p. 1"
    assert cites[1]["title"] == "Inspection report IR-2026-118 · page 1"
    assert "Misalignment observed: 0.3 mm" in cites[1]["quote"]
    assert cites[2]["label"].startswith("Manual · p. ") and cites[2]["quote"]
    assert cites[0]["title"].startswith("WO-0359 · ")


def test_streamed_refs_split_across_tokens_are_renumbered(tmp_path) -> None:
    ctx = make_context(tmp_path)
    add_inspection(ctx.conn)
    ctx.inspections["INSP-P101-20261102"] = {
        "tag": "P-101",
        "findings": [],
        "page": 1,
        "report_no": "",
        "id": "INSP-P101-20261102",
    }
    fs = FrontendStream(ctx, "P-101")
    out = []
    for piece in ["Misalign", "ment [INSP-P1", "01-20261102] and [", "link](x) [S9]."]:
        for e in fs.convert({"type": "answer_delta", "data": {"text": piece}}):
            out.append(e["text"])
    for e in fs.convert({"type": "answer", "data": {"text": "ignored when streamed"}}):
        out.append(e["text"])
    assert "".join(out) == "Misalignment [1] and [link](x) ."


def test_blocked_maps_to_frontend_attempt(tmp_path) -> None:
    fs = FrontendStream(make_context(tmp_path))
    ev = {
        "type": "blocked",
        "data": {
            "id": "blk-1",
            "call_id": "x",
            "at": "2026-11-14T10:00:00",
            "tool": "send_data",
            "target": "http://evil.example/c",
            "source": "Vendor bulletin, p. 1",
            "reason": "not allowed",
        },
    }
    (out,) = fs.convert(ev)
    assert out == {
        "type": "blocked",
        "attempt": {
            "id": "blk-1",
            "at": "2026-11-14T10:00:00",
            "tool": "send_data",
            "target": "http://evil.example/c",
            "source": "Vendor bulletin, p. 1",
            "reason": "not allowed",
        },
    }
    step = fs.convert(
        {
            "type": "tool_completed",
            "data": {
                "call_id": "x",
                "tool": "send_data",
                "status": "blocked",
                "summary": "Blocked",
            },
        }
    )
    assert step[0]["step"]["status"] == "blocked"


def test_ask_error_event(client, tmp_path, monkeypatch) -> None:
    llm = ScriptedChatModel(responses=[ConnectionError("Ollama is down")])
    monkeypatch.setattr(agent_api, "make_context", lambda **kw: make_context(tmp_path))
    monkeypatch.setattr(agent_api, "get_chat_model", lambda **kw: llm)
    events = parse_sse(client.post("/api/agent/ask", json={"question": "hi"}).text)
    assert [e["type"] for e in events] == ["error", "done"]
    assert "Ollama is down" in events[0]["message"]
    assert events[1]["can_draft_work_order"] is False


def test_chat_streams_named_sse_events(client, tmp_path, monkeypatch) -> None:
    llm = ScriptedChatModel(responses=[tool_call("get_asset_history", {"tag": "P-101"}), "Done."])
    monkeypatch.setattr(agent_api, "make_context", lambda **kw: make_context(tmp_path))
    monkeypatch.setattr(agent_api, "get_chat_model", lambda **kw: llm)
    resp = client.post("/api/agent/chat", json={"message": "Tell me about P-101"})
    events = parse_named_sse(resp.text)
    names = [e for e, _ in events]
    assert names[0] == "run_started" and names[-1] == "done"
    assert "tool_started" in names and "tool_completed" in names
    assert dict(events)["answer"]["text"] == "Done."


def test_requests_are_validated(client) -> None:
    assert client.post("/api/agent/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/agent/ask", json={"question": ""}).status_code == 422


def test_status_reports_ollama_and_store(client, monkeypatch) -> None:
    from app.agent.llm import OllamaStatus

    monkeypatch.setattr(
        agent_api, "check_ollama", lambda: OllamaStatus(False, "http://x", error="down")
    )

    class Store:
        def count(self):
            return 0

    monkeypatch.setattr(agent_api, "_manual_store", lambda: Store())
    body = client.get("/api/agent/status").json()
    assert body["ollama"]["reachable"] is False and body["ready"] is False


# --------------------------------------------------------------------------- documents


def test_documents_work_order_report_list_and_download(client, tmp_path, monkeypatch) -> None:
    from tests.test_agent_tools import _rec_json

    store = memory_store()
    ingest_directory(store, MANUALS)
    fake = ScriptedChatModel(responses=[_rec_json()])

    def ctx_factory(**kw):
        c = make_context(tmp_path, store, llm_factory=lambda **k: fake)
        c.user = kw.get("user", "agent")
        return c

    monkeypatch.setattr(agent_api, "make_context", ctx_factory)

    wo = client.post("/api/documents/work-order", json={"tag": "p101", "requested_by": "Asha"})
    assert wo.status_code == 200, wo.text
    item = wo.json()
    assert item["kind"] == "work_order" and item["tag"] == "P-101"
    assert item["created_by"] == "Asha" and item["work_order"]["requested_by"] == "Asha"
    assert item["work_order"]["problem"].startswith("Recurring failures")  # no issue given

    rep = client.post("/api/documents/bad-actor-report")
    assert rep.status_code == 200 and rep.json()["kind"] == "bad_actor_report"

    listed = client.get("/api/documents").json()
    assert {d["id"] for d in listed} == {item["id"], rep.json()["id"]}

    dl = client.get(f"/api/documents/{item['id']}/download")
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    assert "wordprocessingml" in dl.headers["content-type"]
    xl = client.get(f"/api/documents/{rep.json()['id']}/download")
    assert "spreadsheetml" in xl.headers["content-type"]


def test_document_download_rejects_traversal(client, settings) -> None:
    assert client.get("/api/documents/missing/download").status_code == 404
    assert client.get("/api/documents/..%5C..%5Csecret/download").status_code == 404
    assert client.get("/api/documents/.env/download").status_code == 404


def test_work_order_for_unknown_asset_is_422(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_api, "make_context", lambda **kw: make_context(tmp_path))
    assert client.post("/api/documents/work-order", json={"tag": "P-999"}).status_code == 422


# --------------------------------------------------------------------------- inspections


def test_asset_inspection_endpoint(client, settings) -> None:
    import pandas as pd

    from app.db import connect, init_db
    from tests.agent_helpers import SYNTHETIC

    conn = connect(settings.db_path)
    init_db(conn)
    pd.read_csv(SYNTHETIC / "assets.csv").to_sql("assets", conn, if_exists="append", index=False)
    add_inspection(conn)
    conn.close()

    body = client.get("/api/assets/p101/inspection").json()
    assert body["id"] == "INSP-P101-20261102" and body["report_no"] == "IR-2026-118"
    assert body["pages"] == 2 and body["page"] == 1
    assert {"item", "result", "flagged"} == set(body["findings"][0])
    assert client.get("/api/assets/C-203/inspection").status_code == 404
    assert client.get("/api/assets/nonsense/inspection").status_code == 400
