import asyncio
import json
from datetime import date

import pytest
from langchain_core.messages import AIMessage

from app.agent.graph import cited_refs, recover_tool_calls, run_agent
from app.config import get_settings
from tests.agent_helpers import ScriptedChatModel, make_context, tool_call

THREE_TOOLS = ["get_asset_info", "get_maintenance_history", "analyze_failure_patterns"]


@pytest.fixture(autouse=True)
def demo_date(monkeypatch):
    monkeypatch.setattr(get_settings(), "analysis_as_of", date(2026, 11, 14))


def run(ctx, llm, question="Investigate P-101", **kw):
    return asyncio.run(run_agent(question, ctx, llm, **kw))


def types(events):
    return [e["type"] for e in events]


def test_three_tool_investigation_streams_events_in_order(tmp_path) -> None:
    llm = ScriptedChatModel(
        responses=[
            tool_call("get_asset_info", {"tag": "P-101"}),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_maintenance_history",
                        "args": {"tag": "P-101", "days": 180},
                        "id": "h1",
                    },
                    {
                        "name": "analyze_failure_patterns",
                        "args": {"tag": "P-101", "keywords": ["seal"]},
                        "id": "p1",
                    },
                ],
            ),
            "**Finding** - P-101 had 4 seal failures in 180 days (WO-0359).",
        ]
    )
    out = run(make_context(tmp_path), llm, tool_names=THREE_TOOLS)
    ev = out["events"]
    assert types(ev)[:3] == ["run_started", "status", "tool_started"]
    assert types(ev)[-2:] == ["answer", "done"]
    started = [e["data"]["tool"] for e in ev if e["type"] == "tool_started"]
    assert started == THREE_TOOLS
    done = [e["data"] for e in ev if e["type"] == "tool_completed"]
    assert [d["status"] for d in done] == ["success"] * 3
    assert "9 events, 4 in last window" in done[2]["summary"]
    assert "4 seal failures" in out["answer"]["text"]
    assert ev[-1]["data"]["iterations"] == 3
    # the model saw the tool results it asked for
    tool_msgs = [m for m in llm.calls[-1] if m.type == "tool"]
    assert json.loads(tool_msgs[-1].content)["matching"]["events"] == 9


def test_tool_not_in_allow_list_is_blocked(tmp_path) -> None:
    llm = ScriptedChatModel(
        responses=[tool_call("generate_work_order", {"tag": "P-101", "issue": "x"}), "ok"]
    )
    out = run(make_context(tmp_path), llm, tool_names=THREE_TOOLS)
    done = next(e["data"] for e in out["events"] if e["type"] == "tool_completed")
    assert done["status"] == "error" and "Blocked" in done["summary"]
    assert out["answer"]["text"] == "ok"


def test_iteration_limit_forces_final_answer(tmp_path) -> None:
    loop = [tool_call("get_asset_info", {"tag": f"P-10{i}"}, f"c{i}") for i in range(1, 4)]
    llm = ScriptedChatModel(responses=[*loop, "Final answer with what I have."])
    out = run(make_context(tmp_path), llm, max_iterations=3)
    assert types(out["events"]).count("tool_started") == 3
    assert out["answer"]["text"] == "Final answer with what I have."
    assert "tool-call limit" in llm.calls[-1][-1].content


def test_repeated_call_returns_cached_result(tmp_path) -> None:
    llm = ScriptedChatModel(
        responses=[
            tool_call("get_asset_info", {"tag": "P-101"}, "a"),
            tool_call("get_asset_info", {"tag": "P-101"}, "b"),
            "done",
        ]
    )
    out = run(make_context(tmp_path), llm)
    summaries = [e["data"]["summary"] for e in out["events"] if e["type"] == "tool_completed"]
    assert summaries[1] == "Repeated call (cached result)"


def test_llm_failure_becomes_error_event(tmp_path) -> None:
    llm = ScriptedChatModel(responses=[ConnectionError("Ollama connection refused")])
    out = run(make_context(tmp_path), llm)
    assert types(out["events"]) == ["run_started", "status", "error", "done"]
    assert "connection refused" in out["events"][2]["data"]["message"]
    assert out["answer"] is None


def test_sources_and_cited_refs_reported(tmp_path) -> None:
    from app.agent.rag import ingest_directory
    from tests.agent_helpers import MANUALS, memory_store

    store = memory_store()
    ingest_directory(store, MANUALS)
    llm = ScriptedChatModel(
        responses=[
            tool_call("search_manuals", {"query": "repeated seal failures root cause analysis"}),
            "Raise an RCA [S1]. Also see [S42].",
        ]
    )
    out = run(make_context(tmp_path, store), llm)
    src = next(e["data"]["sources"] for e in out["events"] if e["type"] == "sources")
    assert src[0]["ref"] == "S1" and src[0]["page"] and src[0]["snippet"]
    assert out["answer"]["cited_refs"] == ["S1"]
    assert out["answer"]["unknown_refs"] == ["S42"]


def test_recover_tool_call_printed_as_text() -> None:
    msg = AIMessage(
        content="<tool_call>\n"
        '{"name": "get_asset_info", "arguments": {"tag": "P-101"}}'
        "\n</tool_call>"
    )
    fixed = recover_tool_calls(msg, {"get_asset_info"})
    assert fixed.tool_calls[0]["name"] == "get_asset_info"
    assert fixed.tool_calls[0]["args"] == {"tag": "P-101"}
    bare = AIMessage(content='{"name": "rm_rf", "arguments": {}}')
    assert recover_tool_calls(bare, {"get_asset_info"}) is bare  # not allowed -> untouched


def test_cited_refs_parsing() -> None:
    assert cited_refs("See [S1], [S2, S3] and S1 again; WO-0012 is not a ref") == [
        "S1",
        "S2",
        "S3",
    ]
