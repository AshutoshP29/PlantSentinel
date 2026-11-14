"""The seven agent tools.

Tools are built per run around an `AgentContext`, which holds the database connection, the
manual store, the LLM and everything retrieved so far (so citations get stable refs S1, S2,
... across the whole run, and the work order can reuse the evidence already gathered).

Every tool validates its input with a pydantic schema and returns a JSON string. Errors are
returned as {"error": ...} with status="error" so the agent can recover instead of crashing.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError

from app.agent import analytics, data
from app.agent.prompts import RECOMMEND_PROMPT
from app.agent.rag import Citation, ManualStore
from app.agent.schemas import (
    BadActorInput,
    HistoryInput,
    PatternInput,
    Recommendation,
    RecommendInput,
    SearchManualsInput,
    TagInput,
    WorkOrderInput,
)

log = logging.getLogger(__name__)


class ToolError(Exception):
    """A user-facing tool failure (bad tag, missing data). Message is shown to the agent."""


@dataclass
class AgentContext:
    conn: sqlite3.Connection
    store_factory: Callable[[], ManualStore]
    llm_factory: Callable[..., BaseChatModel]
    outputs_dir: Path
    citations: dict[str, Citation] = field(default_factory=dict)  # chunk_id -> citation
    recommendations: dict[str, Recommendation] = field(default_factory=dict)
    patterns: dict[str, dict] = field(default_factory=dict)
    work_orders: list[dict] = field(default_factory=list)
    _store: ManualStore | None = None

    @property
    def store(self) -> ManualStore:
        if self._store is None:
            try:
                self._store = self.store_factory()
            except Exception as exc:
                raise ToolError(f"Manual search is unavailable: {exc}") from exc
        return self._store

    def remember(self, cites: list[Citation]) -> list[Citation]:
        """Assign run-wide refs (S1, S2, ...) to retrieved passages."""
        out = []
        for c in cites:
            if c.chunk_id not in self.citations:
                c.ref = f"S{len(self.citations) + 1}"
                self.citations[c.chunk_id] = c
            out.append(self.citations[c.chunk_id])
        return out

    def by_ref(self) -> dict[str, Citation]:
        return {c.ref: c for c in self.citations.values()}

    def asset(self, raw_tag: str) -> dict:
        try:
            tag = data.normalise_tag(raw_tag)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        row = data.get_asset(self.conn, tag)
        if row is None:
            near = data.similar_tags(self.conn, tag)
            raise ToolError(f"No asset {tag} in the equipment register. Similar tags: {near}")
        return row


# --------------------------------------------------------------------------- tool bodies


def _search_manuals(ctx: AgentContext, args: SearchManualsInput) -> dict:
    cites = ctx.remember(ctx.store.search(args.query, equipment=args.equipment_type))
    if not cites:
        return {"query": args.query, "results": [], "note": "No relevant passage found."}
    return {
        "query": args.query,
        "results": [
            {
                "ref": c.ref,
                "document": c.title or c.source,
                "page": c.page,
                "section": c.section,
                "score": c.score,
                "text": c.text,
            }
            for c in cites
        ],
    }


def _asset_info(ctx: AgentContext, args: TagInput) -> dict:
    asset = ctx.asset(args.tag)
    last = data.work_orders(ctx.conn, asset["tag"], limit=1)
    return {**asset, "last_work_order": last[0] if last else None}


def _history(ctx: AgentContext, args: HistoryInput) -> dict:
    tag = ctx.asset(args.tag)["tag"]
    since = data.window_start(args.days) if args.days else None
    rows = data.work_orders(ctx.conn, tag, since=since, limit=args.limit)
    total = len(data.work_orders(ctx.conn, tag, since=since))
    return {
        "tag": tag,
        "since": since.isoformat() if since else None,
        "returned": len(rows),
        "total_matching": total,
        "work_orders": rows,
    }


def _patterns(ctx: AgentContext, args: PatternInput) -> dict:
    tag = ctx.asset(args.tag)["tag"]
    result = analytics.failure_patterns(ctx.conn, tag, args.keywords, args.window_days)
    ctx.patterns[tag] = result
    return result


def _bad_actors(ctx: AgentContext, args: BadActorInput) -> dict:
    tag = ctx.asset(args.tag)["tag"] if args.tag else None
    return analytics.bad_actors(ctx.conn, args.top_n, tag)


def _history_facts(ctx: AgentContext, tag: str) -> str:
    pat = ctx.patterns.get(tag) or analytics.failure_patterns(ctx.conn, tag)
    facts = {k: pat.get(k) for k in ("method", "keyword_filter", "matching", "by_failure_mode")}
    facts["all_work_orders"] = {
        k: v for k, v in (pat.get("all_work_orders") or {}).items() if k != "work_order_ids"
    }
    recent = data.work_orders(ctx.conn, tag, limit=10)
    facts["recent_work_orders"] = [
        {k: r[k] for k in ("id", "date", "description", "action_taken")} for r in recent
    ]
    return json.dumps({k: v for k, v in facts.items() if v}, default=str)


def _ground(rec: Recommendation, valid_refs: set[str], wo_ids: set[str]) -> tuple[dict, int]:
    """Drop recommendation items that don't cite a passage we actually retrieved."""
    dropped = 0

    def keep(items: list, allow_wo: bool = False) -> list:
        nonlocal dropped
        out = []
        for it in items:
            ok = valid_refs | (wo_ids if allow_wo else set())
            it.sources = [s for s in it.sources if s in ok]
            if it.sources:
                out.append(it)
            else:
                dropped += 1
        return out

    rec.probable_causes = keep(rec.probable_causes, allow_wo=True)
    rec.actions = keep(rec.actions)
    rec.materials = keep(rec.materials)
    rec.safety = keep(rec.safety)
    if rec.estimated_duration and not keep([rec.estimated_duration]):
        rec.estimated_duration = None
    return rec.model_dump(), dropped


def _recommend(ctx: AgentContext, args: RecommendInput) -> dict:
    asset = ctx.asset(args.tag)
    tag = asset["tag"]
    queries = [
        args.issue,
        f"{asset['type']} {args.issue} causes",
        f"{args.issue} repair procedure safety precautions materials",
    ]
    cites: list[Citation] = []
    for q in queries:
        for c in ctx.remember(ctx.store.search(q, equipment=asset["type"])):
            if c not in cites:
                cites.append(c)
    if not cites:
        raise ToolError(
            "No manual passage covers this issue, so no grounded recommendation can be made."
        )
    passages = "\n\n".join(f"[{c.ref}] ({c.label()})\n{c.text}" for c in cites)
    prompt = RECOMMEND_PROMPT.format(
        tag=tag,
        issue=args.issue,
        asset=json.dumps(asset),
        history=_history_facts(ctx, tag),
        passages=passages,
    )
    llm = ctx.llm_factory(format=Recommendation.model_json_schema())
    rec, last_err = None, None
    for attempt in range(2):
        msg = prompt if attempt == 0 else f"{prompt}\n\nYour previous JSON was invalid: {last_err}"
        raw = llm.invoke([HumanMessage(msg)]).content
        try:
            rec = Recommendation.model_validate_json(raw if isinstance(raw, str) else str(raw))
            break
        except ValidationError as exc:
            last_err = str(exc)[:500]
            log.warning("recommendation JSON invalid (attempt %d): %s", attempt + 1, last_err)
    if rec is None:
        raise ToolError("The model did not return a valid recommendation. Try again.")
    wo_ids = {r["id"] for r in data.work_orders(ctx.conn, tag)}
    result, dropped = _ground(rec, {c.ref for c in cites}, wo_ids)
    ctx.recommendations[tag] = Recommendation.model_validate(result)
    result["tag"] = tag
    result["unsupported_items_removed"] = dropped
    result["sources"] = [{"ref": c.ref, "document": c.label()} for c in cites]
    return result


def _work_order(ctx: AgentContext, args: WorkOrderInput) -> dict:
    from app.docgen.work_order import WorkOrderData, build_work_order

    asset = ctx.asset(args.tag)
    tag = asset["tag"]
    rec = ctx.recommendations.get(tag)
    if rec is None:
        _recommend(ctx, RecommendInput(tag=tag, issue=args.issue))
        rec = ctx.recommendations[tag]
    refs = ctx.by_ref()
    used = {
        s
        for item in [*rec.probable_causes, *rec.actions, *rec.materials, *rec.safety]
        for s in item.sources
    }
    if rec.estimated_duration:
        used |= set(rec.estimated_duration.sources)
    pattern = ctx.patterns.get(tag) or analytics.failure_patterns(ctx.conn, tag)
    wo = WorkOrderData(
        asset=asset,
        issue=args.issue,
        priority=args.priority or rec.priority,
        recommendation=rec,
        pattern=pattern,
        history=data.work_orders(ctx.conn, tag, limit=12),
        citations=[refs[r] for r in sorted(used, key=_ref_order) if r in refs],
    )
    path = build_work_order(wo, ctx.outputs_dir)
    info = {
        "work_order_id": wo.work_order_id,
        "tag": tag,
        "priority": wo.priority,
        "file": path.name,
        "download_url": f"/api/agent/work-orders/{path.name}",
    }
    ctx.work_orders.append(info)
    return info


# --------------------------------------------------------------------------- registry

TOOL_SPECS: list[tuple[str, type[BaseModel], Callable[[AgentContext, Any], dict], str]] = [
    (
        "get_asset_info",
        TagInput,
        _asset_info,
        "Get the equipment register entry for a tag: type, location, criticality, install date.",
    ),
    (
        "get_maintenance_history",
        HistoryInput,
        _history,
        "List past work orders for a tag (newest first), optionally only the last N days.",
    ),
    (
        "analyze_failure_patterns",
        PatternInput,
        _patterns,
        "Failure counts, recent-window counts and mean days between failures for a tag. Use "
        "keywords to focus on one failure type (e.g. ['seal']).",
    ),
    (
        "get_bad_actors",
        BadActorInput,
        _bad_actors,
        "Rank the assets causing the most trouble, and give the rank of a tag if provided.",
    ),
    (
        "search_manuals",
        SearchManualsInput,
        _search_manuals,
        "Search technical manuals and SOPs. Returns passages with refs like S1 to cite.",
    ),
    (
        "recommend_maintenance",
        RecommendInput,
        _recommend,
        "Grounded probable causes, corrective actions, materials and safety precautions for an "
        "issue on a tag, using manuals and failure history. Every item cites a source.",
    ),
    (
        "generate_work_order",
        WorkOrderInput,
        _work_order,
        "Create a maintenance work-order .docx for a tag and issue. Returns a download link.",
    ),
]
TOOL_NAMES = [name for name, *_ in TOOL_SPECS]


def build_tools(ctx: AgentContext, names: list[str] | None = None) -> list[StructuredTool]:
    """LangChain tools bound to this run's context. `names` restricts the allow-list."""
    tools = []
    for name, schema, fn, desc in TOOL_SPECS:
        if names is not None and name not in names:
            continue

        def run(_fn=fn, _schema=schema, _name=name, **kwargs: Any) -> tuple[str, dict]:
            return execute(ctx, _name, _schema, _fn, kwargs)

        tools.append(
            StructuredTool.from_function(
                func=run,
                name=name,
                description=desc,
                args_schema=schema,
                response_format="content_and_artifact",
            )
        )
    return tools


def execute(
    ctx: AgentContext,
    name: str,
    schema: type[BaseModel],
    fn: Callable[[AgentContext, Any], dict],
    kwargs: dict,
) -> tuple[str, dict]:
    """Validate, run and serialise one tool call. Returns (content, artifact)."""
    try:
        args = schema.model_validate(kwargs)
        result = fn(ctx, args)
        status = "success"
    except ValidationError as exc:
        result, status = {"error": f"Invalid arguments: {exc.errors(include_url=False)}"}, "error"
    except ToolError as exc:
        result, status = {"error": str(exc)}, "error"
    except Exception as exc:
        log.exception("tool %s failed", name)
        result, status = {"error": f"{type(exc).__name__}: {exc}"}, "error"
    artifact = {"status": status, "summary": summarise(name, result)}
    return json.dumps(result, default=str), artifact


def summarise(name: str, r: dict) -> str:
    """One line for the UI's step list."""
    if "error" in r:
        return f"Error: {str(r['error'])[:160]}"
    match name:
        case "get_asset_info":
            return f"{r['tag']}: {r['type']}, {r['location']}, criticality {r['criticality']}"
        case "get_maintenance_history":
            return f"{r['returned']} of {r['total_matching']} work orders for {r['tag']}"
        case "analyze_failure_patterns":
            m = r.get("matching") or r.get("all_work_orders") or {}
            return (
                f"{m.get('events', 0)} events, {m.get('events_in_window', 0)} in last window; "
                f"mean gap {m.get('mean_days_between_before_window')} -> "
                f"{m.get('mean_days_between_in_window')} days"
            )
        case "get_bad_actors":
            a = r.get("asset")
            return f"{a['tag']} ranked {a['rank']} of {a.get('of')}" if a else "ranking loaded"
        case "search_manuals":
            refs = ", ".join(x["ref"] for x in r["results"])
            return f"{len(r['results'])} passages ({refs})" if refs else "no relevant passage"
        case "recommend_maintenance":
            return (
                f"{len(r['probable_causes'])} causes, {len(r['actions'])} actions, "
                f"{len(r['safety'])} safety items"
            )
        case "generate_work_order":
            return f"{r['work_order_id']} -> {r['file']}"
    return "done"


def _ref_order(ref: str) -> tuple[int, str]:
    """Sort S1, S2, ... numerically; anything else (e.g. work-order ids) after them."""
    return (int(ref[1:]), "") if re.fullmatch(r"S\d+", ref) else (10**9, ref)
