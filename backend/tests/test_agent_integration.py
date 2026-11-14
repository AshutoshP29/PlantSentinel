"""Real-model tests. Need Ollama with the README models: `pytest -m integration`."""

import asyncio
from datetime import date

import pytest

from app.agent import llm
from app.config import get_settings
from tests.agent_helpers import MANUALS, MemoryCollection, make_context

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def ollama_ready():
    status = llm.check_ollama()
    if not status.ready:
        pytest.skip(f"Ollama not ready: {status.error or status.missing}")


@pytest.fixture
def real_store():
    from app.agent.rag import ManualStore, NomicPrefixEmbedder, ingest_directory

    store = ManualStore(MemoryCollection(), NomicPrefixEmbedder(llm.get_embeddings()))
    ingest_directory(store, MANUALS)
    return store


def test_generation_and_json_mode() -> None:
    assert "OK" in str(llm.get_chat_model().invoke("Reply with exactly: OK").content)
    out = llm.get_chat_model(format="json").invoke('Return {"ok": true} as JSON.').content
    assert "true" in str(out)


def test_real_embeddings_retrieve_the_right_section(real_store) -> None:
    hits = real_store.search("why does the pump mechanical seal keep failing from overheating")
    assert hits, "nothing retrieved"
    assert any("flush" in h.text.lower() for h in hits[:3])


def test_demo_question_end_to_end(tmp_path, real_store, monkeypatch) -> None:
    from app.agent.graph import run_agent

    monkeypatch.setattr(get_settings(), "analysis_as_of", date(2026, 11, 14))
    ctx = make_context(tmp_path, real_store, llm_factory=llm.get_chat_model)
    q = (
        "Pump P-101 has experienced repeated overheating. Investigate its maintenance history, "
        "find relevant instructions in the technical manuals, identify possible causes and "
        "generate a maintenance work order."
    )
    out = asyncio.run(run_agent(q, ctx, llm.get_chat_model()))
    tools = [e["data"]["tool"] for e in out["events"] if e["type"] == "tool_started"]
    assert "get_maintenance_history" in tools or "analyze_failure_patterns" in tools
    assert "search_manuals" in tools or "recommend_maintenance" in tools
    assert out["answer"] and out["answer"]["text"]
    assert ctx.work_orders, f"no work order generated; tools called: {tools}"
