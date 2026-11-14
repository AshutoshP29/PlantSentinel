"""LangGraph maintenance agent and its event stream.

    START -> agent --(tool calls)--> tools --(calls left)--> agent --(no tool calls)--> END
                                       \\--(8 calls used)--> finalize --> END

The limit is on tool calls (spec: max 8 per question), not on rounds: a round asking for
several tools spends several calls, and calls beyond the budget are refused, not run.

Every call passes the guard (`AgentContext.guard`): calls to tools outside the allow-list, or
carrying an outbound destination (URL / e-mail), are blocked, reported as a `blocked` event
and recorded for the audit log.

`stream_agent` yields UI events (EVENT_TYPES). Tool names, arguments, short summaries,
sources, the final answer (streamed token by token) and errors are emitted; intermediate model
text that looks like a tool call is never streamed.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.prompts import FINALIZE_PROMPT, SYSTEM_PROMPT
from app.agent.tools import TOOL_SPECS, AgentContext, AllowListGuard, build_tools, execute
from app.config import get_settings

log = logging.getLogger(__name__)

EVENT_TYPES = (
    "run_started",  # {run_id, question}
    "status",  # {stage, message}
    "tool_started",  # {call_id, tool, args}
    "tool_completed",  # {call_id, tool, status, summary, duration_ms}
    "blocked",  # {id, call_id, at, tool, target, source, reason}
    "sources",  # {sources: [{ref, title, source, page, section, score, snippet}]}
    "document",  # DocumentItem + {download_url, ...}
    "answer_delta",  # {text}  (final answer, streamed)
    "answer",  # {text, cited_refs, unknown_refs, documents}
    "error",  # {message}
    "done",  # {run_id, tool_calls, elapsed_s}
)

TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
REF_TOKEN = r"S\d+|INSP-[A-Z0-9]+-[A-Za-z0-9]+(?:-\d+)?|WO-[A-Z0-9-]*\d"
BRACKET_RE = re.compile(r"\[([^\[\]]{1,200})\]")
STREAM_NODES = ("agent", "finalize")


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    tool_calls: int


# --------------------------------------------------------------------------- helpers


def recover_tool_calls(msg: AIMessage) -> AIMessage:
    """Small models sometimes print the tool call as text instead of using the tool API.

    Accepts `<tool_call>{...}</tool_call>` or a bare JSON object with name/arguments. Unknown
    tool names are kept on purpose: the guard blocks and reports them instead of hiding them.
    """
    if msg.tool_calls or not isinstance(msg.content, str) or not msg.content.strip():
        return msg
    text = msg.content.strip()
    blobs = TOOL_CALL_TAG.findall(text) or ([text] if text.startswith("{") else [])
    calls = []
    for blob in blobs:
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        name = obj.get("name") if isinstance(obj, dict) else None
        args = obj.get("arguments", obj.get("parameters", {})) if name else None
        if isinstance(name, str) and isinstance(args, dict):
            calls.append({"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"})
    if not calls:
        return msg
    log.info("recovered %d tool call(s) from model text", len(calls))
    return AIMessage(content="", tool_calls=calls)


def _call_key(name: str, args: dict) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


def _blocked_source(ctx: AgentContext, tool: str, target: str) -> str:
    """Name the retrieved document that carried the instruction, if we can tell."""
    needles = [n.lower() for n in (target, tool) if n]
    for c in ctx.citations.values():
        text = re.sub(r"\s+", "", c.text.lower())
        if any(re.sub(r"\s+", "", n) in text for n in needles):
            return c.label()
    return "model output"


# --------------------------------------------------------------------------- graph


def build_graph(
    ctx: AgentContext,
    llm: BaseChatModel,
    max_tool_calls: int | None = None,
    tool_names: list[str] | None = None,
):
    """Compile the agent graph. `tool_names` is the allow-list (default: all seven tools)."""
    limit = max_tool_calls or get_settings().agent_max_tool_calls
    specs = {
        name: (schema, fn)
        for name, schema, fn, _ in TOOL_SPECS
        if tool_names is None or name in tool_names
    }
    if ctx.guard is None:
        ctx.guard = AllowListGuard(set(specs))
    guard = ctx.guard
    model = llm.bind_tools(build_tools(ctx, list(specs)))
    system = SystemMessage(SYSTEM_PROMPT.replace("{max_calls}", str(limit)))
    seen: dict[str, str] = {}

    def agent(state: AgentState) -> dict:
        resp = recover_tool_calls(model.invoke([system, *state["messages"]]))
        return {"messages": [resp]}

    def tools(state: AgentState) -> dict:
        used = state.get("tool_calls", 0)
        out: list[ToolMessage] = []
        for call in getattr(state["messages"][-1], "tool_calls", []):
            name, args = call["name"], call.get("args") or {}
            if used >= limit:
                content = json.dumps(
                    {"error": f"Tool-call limit of {limit} reached. Answer with what you have."}
                )
                artifact = {"status": "error", "summary": "Skipped: tool-call limit reached"}
            else:
                used += 1
                decision = guard.check(name, args)
                if not decision.allowed:
                    content = json.dumps({"error": f"Blocked by policy: {decision.reason}."})
                    artifact = {
                        "status": "blocked",
                        "summary": f"Blocked: {decision.reason}",
                        "reason": decision.reason,
                        "target": decision.target,
                        "source": _blocked_source(ctx, name, decision.target),
                    }
                elif (key := _call_key(name, args)) in seen:
                    content = json.dumps(
                        {
                            "note": "Already called with these arguments; same result.",
                            "result": json.loads(seen[key]),
                        }
                    )
                    artifact = {"status": "success", "summary": "Repeated call (cached result)"}
                else:
                    content, artifact = execute(ctx, name, *specs[name], args)
                    if artifact["status"] == "success":
                        seen[key] = content
                guard.record(
                    {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "user": ctx.user,
                        "role": ctx.role,
                        "action": "tool_call",
                        "tool": name,
                        "input": json.dumps(args, default=str),
                        "output": artifact["summary"],
                        "status": {"success": "allowed"}.get(
                            artifact["status"], artifact["status"]
                        ),
                    }
                )
            out.append(
                ToolMessage(
                    content=content,
                    tool_call_id=call["id"],
                    name=name,
                    status="success" if artifact["status"] == "success" else "error",
                    artifact=artifact,
                )
            )
        return {"messages": out, "tool_calls": used}

    def finalize(state: AgentState) -> dict:
        resp = llm.invoke([system, *state["messages"], HumanMessage(FINALIZE_PROMPT)])
        return {"messages": [AIMessage(content=str(resp.content))]}

    def after_agent(state: AgentState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    def after_tools(state: AgentState) -> str:
        return "finalize" if state.get("tool_calls", 0) >= limit else "agent"

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_node("finalize", finalize)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", END])
    g.add_conditional_edges("tools", after_tools, ["agent", "finalize"])
    g.add_edge("finalize", END)
    return g.compile()


# --------------------------------------------------------------------------- streaming


def _event(kind: str, /, **data: Any) -> dict:
    assert kind in EVENT_TYPES, kind
    return {"type": kind, "data": data}


def cited_refs(text: str) -> list[str]:
    """Refs in brackets, in order of first appearance: S1, INSP-..., WO-...."""
    refs: list[str] = []
    for m in BRACKET_RE.finditer(text):
        for r in re.findall(REF_TOKEN, m.group(1)):
            if r not in refs:
                refs.append(r)
    return refs


def history_messages(history: list[dict] | None) -> list[AnyMessage]:
    msgs: list[AnyMessage] = []
    for turn in history or []:
        cls = HumanMessage if turn.get("role") == "user" else AIMessage
        msgs.append(cls(content=str(turn.get("content", ""))))
    return msgs


class _DeltaFilter:
    """Turns LLM token chunks into answer deltas, holding back tool-call-looking text."""

    def __init__(self) -> None:
        self.buf: dict[str, str] = {}
        self.sent: dict[str, int] = {}
        self.tool_turns: set[str] = set()

    def feed(self, chunk: BaseMessage, meta: dict) -> str:
        if meta.get("langgraph_node") not in STREAM_NODES or not isinstance(chunk.content, str):
            return ""
        key = f"{meta.get('langgraph_checkpoint_ns', '')}|{chunk.id}"
        if getattr(chunk, "tool_call_chunks", None) or getattr(chunk, "tool_calls", None):
            self.tool_turns.add(key)
        if key in self.tool_turns:
            return ""
        text = self.buf.get(key, "") + chunk.content
        self.buf[key] = text
        head = text.lstrip()
        if not head or head[0] in "{<":
            return ""  # empty so far, or a tool call printed as text
        start = self.sent.get(key, 0)
        self.sent[key] = len(text)
        return text[start:]


async def stream_agent(
    question: str,
    ctx: AgentContext,
    llm: BaseChatModel,
    history: list[dict] | None = None,
    max_tool_calls: int | None = None,
    tool_names: list[str] | None = None,
) -> AsyncIterator[dict]:
    """Run the agent and yield UI events. Never raises: failures become an `error` event."""
    run_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    limit = max_tool_calls or get_settings().agent_max_tool_calls
    yield _event("run_started", run_id=run_id, question=question)
    yield _event("status", stage="planning", message="Planning the investigation")
    calls_used, sent_sources, sent_docs, answered = 0, 0, 0, False
    names: dict[str, str] = {}
    deltas = _DeltaFilter()
    try:
        graph = build_graph(ctx, llm, limit, tool_names)
        state = {"messages": [*history_messages(history), HumanMessage(question)], "tool_calls": 0}
        async for mode, payload in graph.astream(
            state,
            stream_mode=["updates", "messages"],
            config={"recursion_limit": 4 * limit + 10},
        ):
            if mode == "messages":
                chunk, meta = payload
                if text := deltas.feed(chunk, meta):
                    yield _event("answer_delta", text=text)
                continue
            for node, upd in payload.items():
                if not upd:
                    continue
                msgs = upd.get("messages", [])
                calls_used = upd.get("tool_calls", calls_used)
                if node == "agent" and msgs and msgs[-1].tool_calls:
                    for call in msgs[-1].tool_calls:
                        names[call["id"]] = call["name"]
                        yield _event(
                            "tool_started",
                            call_id=call["id"],
                            tool=call["name"],
                            args=call.get("args") or {},
                        )
                elif node == "tools":
                    for m in msgs:
                        art = m.artifact or {}
                        tool = names.get(m.tool_call_id, m.name)
                        if art.get("status") == "blocked":
                            yield _event(
                                "blocked",
                                id=f"blk-{uuid.uuid4().hex[:8]}",
                                call_id=m.tool_call_id,
                                at=datetime.now().isoformat(timespec="seconds"),
                                tool=tool,
                                target=art.get("target", ""),
                                source=art.get("source", ""),
                                reason=art.get("reason", ""),
                            )
                        yield _event(
                            "tool_completed",
                            call_id=m.tool_call_id,
                            tool=tool,
                            status=art.get("status", m.status),
                            summary=art.get("summary", ""),
                            duration_ms=art.get("duration_ms"),
                        )
                    new = list(ctx.citations.values())[sent_sources:]
                    if new:
                        sent_sources += len(new)
                        yield _event("sources", sources=[_source(c) for c in new])
                    for doc in ctx.documents[sent_docs:]:
                        sent_docs += 1
                        yield _event("document", **doc)
                    yield _event("status", stage="reasoning", message="Reviewing tool results")
                elif node in STREAM_NODES and msgs:
                    text = str(msgs[-1].content).strip()
                    refs = cited_refs(text)
                    known = known_refs(ctx)
                    answered = True
                    yield _event(
                        "answer",
                        text=text,
                        cited_refs=[r for r in refs if r in known],
                        unknown_refs=[r for r in refs if r not in known],
                        documents=list(ctx.documents),
                    )
        if not answered:
            yield _event("error", message="The agent stopped without an answer.")
    except Exception as exc:
        log.exception("agent run %s failed", run_id)
        yield _event("error", message=f"{type(exc).__name__}: {exc}")
    yield _event(
        "done",
        run_id=run_id,
        tool_calls=calls_used,
        elapsed_s=round(time.perf_counter() - started, 2),
    )


def known_refs(ctx: AgentContext) -> set[str]:
    """Everything the answer may legitimately cite: passages, inspections, seen work orders."""
    return set(ctx.by_ref()) | set(ctx.inspections) | set(ctx.seen_work_orders)


def _source(c) -> dict:
    return {
        "ref": c.ref,
        "title": c.title,
        "source": c.source,
        "page": c.page,
        "section": c.section,
        "score": c.score,
        "snippet": c.text[:300],
    }


async def run_agent(question: str, ctx: AgentContext, llm: BaseChatModel, **kw: Any) -> dict:
    """Non-streaming helper: collect all events and return the final answer and events."""
    events = [e async for e in stream_agent(question, ctx, llm, **kw)]
    answer = next((e["data"] for e in reversed(events) if e["type"] == "answer"), None)
    return {"answer": answer, "events": events}
