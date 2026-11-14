"""Real-model tests. Need Ollama with the configured models: `pytest -m integration`."""

import asyncio
from datetime import date

import pytest

from app.agent import llm
from app.config import get_settings
from tests.agent_helpers import MANUALS, MemoryCollection, add_inspection, make_context

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
    hits = real_store.search("why does the pump mechanical seal keep failing from misalignment")
    assert hits, "nothing retrieved"
    assert any("align" in h.text.lower() for h in hits[:3])


def test_vision_model_reads_a_rendered_page(tmp_path) -> None:
    import pymupdf

    from app.agent.inspections import TRANSCRIBE_PROMPT, ollama_vision

    if llm.check_ollama([get_settings().vision_model]).missing:
        pytest.skip("vision model not pulled")
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 90), "Coupling alignment: Misalignment observed 0.3 mm", 14)
    png = doc[0].get_pixmap(dpi=110).tobytes("png")
    text = ollama_vision(TRANSCRIBE_PROMPT, [png], None)
    assert "0.3" in text and "lign" in text


def test_demo_question_end_to_end(tmp_path, real_store, monkeypatch) -> None:
    from app.agent.graph import run_agent

    s = get_settings()
    monkeypatch.setattr(s, "analysis_as_of", date(2026, 11, 14))
    monkeypatch.setattr(s, "outputs_dir", tmp_path / "outputs")
    ctx = make_context(tmp_path, real_store, llm_factory=llm.get_chat_model)
    add_inspection(ctx.conn)
    q = (
        "Pump P-101 keeps failing. Investigate its maintenance history and latest inspection, "
        "find relevant instructions in the technical manuals, identify the likely cause and "
        "generate a maintenance work order."
    )
    out = asyncio.run(run_agent(q, ctx, llm.get_chat_model()))
    tools = [e["data"]["tool"] for e in out["events"] if e["type"] == "tool_started"]
    assert len(tools) <= s.agent_max_tool_calls
    assert "get_asset_history" in tools and "search_manuals" in tools
    assert out["answer"] and out["answer"]["text"]
    assert any(d["kind"] == "work_order" for d in ctx.documents), f"tools called: {tools}"
