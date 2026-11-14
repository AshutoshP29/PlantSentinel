import json

import pytest
from fastapi.testclient import TestClient

from app.api import agent as agent_api
from app.config import get_settings
from app.main import app
from tests.agent_helpers import ScriptedChatModel, make_context, tool_call


@pytest.fixture
def client(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "db_path", tmp_path / "app.db")
    monkeypatch.setattr(s, "outputs_dir", tmp_path / "outputs")
    with TestClient(app) as c:
        yield c


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_chat_streams_sse_events(client, tmp_path, monkeypatch) -> None:
    llm = ScriptedChatModel(responses=[tool_call("get_asset_info", {"tag": "P-101"}), "Done."])
    monkeypatch.setattr(agent_api, "make_context", lambda: make_context(tmp_path))
    monkeypatch.setattr(agent_api, "get_chat_model", lambda **kw: llm)
    resp = client.post("/api/agent/chat", json={"message": "Tell me about P-101"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    names = [e for e, _ in events]
    assert names[0] == "run_started" and names[-1] == "done"
    assert "tool_started" in names and "tool_completed" in names
    assert dict(events)["answer"]["text"] == "Done."


def test_chat_validates_input(client) -> None:
    assert client.post("/api/agent/chat", json={"message": ""}).status_code == 422


def test_work_order_download_and_traversal_guard(client, tmp_path) -> None:
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "WO-AI-1.docx").write_bytes(b"PK")
    assert client.get("/api/agent/work-orders/WO-AI-1.docx").status_code == 200
    assert client.get("/api/agent/work-orders/missing.docx").status_code == 404
    assert client.get("/api/agent/work-orders/..%5Csecret.docx").status_code == 400
    assert client.get("/api/agent/work-orders/notes.txt").status_code == 400


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
