"""Demo rehearsal: run the P-101 question end to end and check every beat of the story.

    uv run python scripts/agent_cli.py rehearse -n 3

Checks per run (the demo script, docs/PROJECT_BRIEF.md section 7):
  history     get_asset_history ran and the answer talks about the seal failures
  inspection  read_inspection ran and the answer cites the P-101 inspection (INSP-004)
  manual      a cited manual passage states the 0.05 mm alignment tolerance
  docx        a work order .docx is produced (as the UI's "Draft work order" button does)
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from app.agent import inspections
from app.agent.graph import run_agent
from app.agent.tools import AgentContext, create_work_order

DEMO_QUESTION = "Why does P-101 keep failing and what should we do?"
DEMO_TAG = "P-101"


async def rehearse_once(
    ctx: AgentContext,
    llm: BaseChatModel,
    question: str = DEMO_QUESTION,
    tag: str = DEMO_TAG,
    draft_work_order: bool = True,
) -> dict:
    started = time.perf_counter()
    out = await run_agent(question, ctx, llm, tag=tag)
    events = out["events"]
    answer = (out["answer"] or {}).get("text", "")
    cited = set((out["answer"] or {}).get("cited_refs", []))
    calls = [e["data"] for e in events if e["type"] == "tool_started"]
    tools = [c["tool"] for c in calls]
    forced = [c["tool"] for c in calls if str(c["call_id"]).startswith("auto_")]
    insp_row = inspections.latest_inspection(ctx.conn, tag)
    insp_id = insp_row["id"] if insp_row else None
    by_ref = ctx.by_ref()
    manual_texts = [by_ref[r].text for r in cited if r in by_ref]

    checks = {
        "history": "get_asset_history" in tools and bool(re.search(r"seal", answer, re.I)),
        "inspection": "read_inspection" in tools and insp_id is not None and insp_id in cited,
        "manual": any(re.search(r"0\.05\s*mm", t) for t in manual_texts),
    }
    docx: Path | None = None
    error = next((e["data"]["message"] for e in events if e["type"] == "error"), None)
    if draft_work_order:
        try:
            doc = next((d for d in ctx.documents if d.get("kind") == "work_order"), None)
            doc = doc or create_work_order(ctx, tag, created_by="rehearsal")
            docx = ctx.outputs_dir / doc["file_name"]
        except Exception as exc:  # report, don't crash the rehearsal
            error = error or f"work order: {exc}"
        checks["docx"] = bool(docx and docx.is_file())
    return {
        "ok": all(checks.values()) and error is None,
        "checks": checks,
        "tools": tools,
        "forced_by_checklist": forced,
        "inspection_id": insp_id,
        "cited": sorted(cited),
        "docx": str(docx) if docx else None,
        "error": error,
        "seconds": round(time.perf_counter() - started, 1),
        "answer": answer,
    }
