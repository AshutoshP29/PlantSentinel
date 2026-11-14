import json
from datetime import date

import pytest
from docx import Document

from app.agent import data
from app.agent.schemas import Recommendation
from app.agent.tools import TOOL_NAMES, TOOL_SPECS, _ground, build_tools, execute
from app.config import get_settings
from tests.agent_helpers import (
    MANUALS,
    ScriptedChatModel,
    make_context,
    memory_store,
)

SPECS = {name: (schema, fn) for name, schema, fn, _ in TOOL_SPECS}


@pytest.fixture(autouse=True)
def demo_date(monkeypatch):
    monkeypatch.setattr(get_settings(), "analysis_as_of", date(2026, 11, 14))
    # the bag-of-words test embedder scores lower than real embeddings: keep all top-k hits
    monkeypatch.setattr(get_settings(), "rag_max_distance", 1.0)


@pytest.fixture
def store():
    from app.agent.rag import ingest_directory

    s = memory_store()
    ingest_directory(s, MANUALS)
    return s


def call(ctx, name, **args):
    content, artifact = execute(ctx, name, *SPECS[name], args)
    return json.loads(content), artifact


def test_seven_tools_registered_with_schemas(tmp_path) -> None:
    tools = build_tools(make_context(tmp_path))
    assert [t.name for t in tools] == TOOL_NAMES
    assert len(tools) == 7
    assert all(t.args_schema is not None and t.description for t in tools)
    assert [t.name for t in build_tools(make_context(tmp_path), ["search_manuals"])] == [
        "search_manuals"
    ]


@pytest.mark.parametrize("raw", ["P-101", "p101", "P 101", "pump P101 is hot"])
def test_normalise_tag(raw) -> None:
    assert data.normalise_tag(raw) == "P-101"


def test_asset_info(tmp_path) -> None:
    out, art = call(make_context(tmp_path), "get_asset_info", tag="p101")
    assert art["status"] == "success"
    assert out["tag"] == "P-101" and out["criticality"] == "A" and out["type"] == "pump"
    assert out["last_work_order"]["id"]
    assert "criticality A" in art["summary"]


def test_unknown_asset_is_a_recoverable_error(tmp_path) -> None:
    out, art = call(make_context(tmp_path), "get_asset_info", tag="P-999")
    assert art["status"] == "error"
    assert "No asset P-999" in out["error"] and "P-101" in out["error"]


def test_invalid_arguments_are_reported(tmp_path) -> None:
    out, art = call(make_context(tmp_path), "get_maintenance_history", tag="P-101", limit=0)
    assert art["status"] == "error" and "Invalid arguments" in out["error"]


def test_history_newest_first_and_window(tmp_path) -> None:
    ctx = make_context(tmp_path)
    out, _ = call(ctx, "get_maintenance_history", tag="P-101", days=180)
    dates = [w["date"] for w in out["work_orders"]]
    assert dates == sorted(dates, reverse=True)
    assert all(d >= "2026-05-18" for d in dates)
    assert out["total_matching"] == out["returned"]


def test_failure_patterns_find_the_planted_p101_seal_story(tmp_path) -> None:
    out, art = call(
        make_context(tmp_path), "analyze_failure_patterns", tag="P-101", keywords=["seal"]
    )
    m = out["matching"]
    assert m["events"] == 9
    assert m["events_in_window"] == 4
    assert m["mean_days_between_before_window"] == 150.0
    assert m["mean_days_between_in_window"] < 60
    assert "preliminary" in out["method"]
    assert "9 events, 4 in last window" in art["summary"]


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


def test_search_manuals_assigns_stable_refs(tmp_path, store) -> None:
    ctx = make_context(tmp_path, store)
    out, art = call(ctx, "search_manuals", query="repeated mechanical seal failures RCA")
    refs = [r["ref"] for r in out["results"]]
    assert refs[0] == "S1" and all(r["page"] for r in out["results"])
    again, _ = call(ctx, "search_manuals", query="repeated mechanical seal failures RCA")
    assert [r["ref"] for r in again["results"]] == refs  # same passage -> same ref
    assert art["summary"].startswith(f"{len(refs)} passages")


def test_search_manuals_unavailable_store(tmp_path) -> None:
    ctx = make_context(tmp_path)

    def broken():
        raise RuntimeError("chroma down")

    ctx.store_factory = broken
    out, art = call(ctx, "search_manuals", query="seal leak")
    assert art["status"] == "error" and "unavailable" in out["error"]


def test_grounding_drops_uncited_and_invented_refs() -> None:
    rec = Recommendation.model_validate(
        {
            "summary": "s",
            "probable_causes": [
                {"cause": "flush blocked", "evidence": "e", "sources": ["[S1]"]},
                {"cause": "history", "evidence": "e", "sources": ["WO-0069"]},
                {"cause": "made up", "evidence": "e", "sources": []},
            ],
            "actions": [
                {"action": "check alignment", "sources": ["s2"]},
                {"action": "replace impeller", "sources": ["S9"]},
            ],
            "safety": [{"action": "wear a hat", "sources": []}],
            "estimated_duration": {"action": "2 h", "sources": ["S7"]},
        }
    )
    out, dropped = _ground(rec, {"S1", "S2"}, {"WO-0069"})
    assert [c["cause"] for c in out["probable_causes"]] == ["flush blocked", "history"]
    assert [a["action"] for a in out["actions"]] == ["check alignment"]
    assert out["safety"] == [] and out["estimated_duration"] is None
    assert dropped == 4


def _rec_json() -> str:
    return json.dumps(
        {
            "summary": "P-101 has repeat seal failures; MTBF fell from 150 to ~51 days.",
            "probable_causes": [
                {
                    "cause": "Loss of seal flush",
                    "evidence": "4 failures in 180 days",
                    "sources": ["S1", "WO-0359"],
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


def test_recommend_is_grounded_and_retries_bad_json(tmp_path, store) -> None:
    fake = ScriptedChatModel(responses=["not json", _rec_json()])
    ctx = make_context(tmp_path, store, llm_factory=lambda **kw: fake)
    out, art = call(ctx, "recommend_maintenance", tag="P-101", issue="repeated seal failures")
    assert art["status"] == "success", out
    assert [a["action"] for a in out["actions"]] == ["Inspect Plan 11 orifice"]
    assert out["unsupported_items_removed"] == 1
    assert out["priority"] == "High" and out["sources"]
    prompt = fake.calls[-1][0].content
    assert "[S1]" in prompt and "WO-0359" in prompt and "previous JSON was invalid" in prompt


def test_generate_work_order_docx(tmp_path, store) -> None:
    fake = ScriptedChatModel(responses=[_rec_json()])
    ctx = make_context(tmp_path, store, llm_factory=lambda **kw: fake)
    call(ctx, "analyze_failure_patterns", tag="P-101", keywords=["seal"])
    out, art = call(ctx, "generate_work_order", tag="P-101", issue="Repeated seal failures")
    assert art["status"] == "success", out
    path = tmp_path / "outputs" / out["file"]
    assert path.is_file() and out["download_url"].endswith(out["file"])
    assert out["work_order_id"].startswith("WO-AI-") and out["priority"] == "High"

    doc = Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs)
    tables = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert out["work_order_id"] in text
    assert "Inspect Plan 11 orifice  [S1]" in text
    assert "Invented step" not in text
    assert "Apply LOTO" in text and "CS-45-SIC" in text
    assert "9 recorded events" in text and "from 150 days to 51 days" in text
    assert "P-101" in tables and "Approved by (Area Manager)" in tables
    assert "8 hours, two fitters" in tables
    assert ctx.work_orders == [out]


def test_work_order_states_missing_safety_instead_of_inventing(tmp_path, store) -> None:
    rec = json.loads(_rec_json())
    rec["safety"], rec["materials"], rec["estimated_duration"] = [], [], None
    fake = ScriptedChatModel(responses=[json.dumps(rec)])
    ctx = make_context(tmp_path, store, llm_factory=lambda **kw: fake)
    out, _ = call(ctx, "generate_work_order", tag="P-101", issue="seal leak", priority="Medium")
    doc = Document(str(tmp_path / "outputs" / out["file"]))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "No verified safety procedure was found" in text
    assert "Not specified in the indexed manuals." in text
    assert out["priority"] == "Medium"
