"""LangGraph maintenance agent and its event stream.

    START -> agent --(tool calls)--> tools --(under limit)--> agent --(no tool calls)--> END
                                       \\--(limit reached)--> finalize --> END

`stream_agent` turns graph updates into UI events (see EVENT_TYPES). Only tool names,
arguments, short result summaries, sources and the final answer are emitted; intermediate
model text is never streamed.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.prompts import FINALIZE_PROMPT, SYSTEM_PROMPT
from app.agent.tools import TOOL_SPECS, AgentContext, build_tools, execute
from app.config import get_settings

log = logging.getLogger(__name__)

EVENT_TYPES = (
    "run_started",  # {run_id, question}
    "status",  # {stage, message}
    "tool_started",  # {call_id, tool, args}
    "tool_completed",  # {call_id, tool, status, summary}
    "sources",  # {sources: [{ref, title, source, page, section, score, snippet}]}
    "work_order",  # {work_order_id, tag, priority, file, download_url}
    "answer",  # {text, cited_refs, unknown_refs, work_orders}
    "error",  # {message}
    "done",  # {run_id, iterations, elapsed_s}
)

TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
REF_RE = re.compile(r"\[(S\d+)(?:\s*,\s*(S\d+))*\]|\b(S\d+)\b")


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    iterations: int


# --------------------------------------------------------------------------- helpers


def recover_tool_calls(msg: AIMessage, allowed: set[str]) -> AIMessage:
    """Small models sometimes print the tool call as text instead of using the tool API.

    Accepts `<tool_call>{...}</tool_call>` or a bare JSON object with name/arguments.
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
        name = obj.get("name")
        args = obj.get("arguments", obj.get("parameters", {}))
        if name in allowed and isinstance(args, dict):
            calls.append({"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"})
    if not calls:
        return msg
    log.info("recovered %d tool call(s) from model text", len(calls))
    return AIMessage(content="", tool_calls=calls)


def _call_key(name: str, args: dict) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


# --------------------------------------------------------------------------- graph


def build_graph(
    ctx: AgentContext,
    llm: BaseChatModel,
    max_iterations: int | None = None,
    tool_names: list[str] | None = None,
):
    """Compile the agent graph. `tool_names` is the allow-list (default: all seven tools)."""
    limit = max_iterations or get_settings().agent_max_iterations
    specs = {
        name: (schema, fn)
        for name, schema, fn, _ in TOOL_SPECS
        if tool_names is None or name in tool_names
    }
    model = llm.bind_tools(build_tools(ctx, list(specs)))
    seen: dict[str, str] = {}

    def agent(state: AgentState) -> dict:
        msgs = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        resp = recover_tool_calls(model.invoke(msgs), set(specs))
        return {"messages": [resp], "iterations": state.get("iterations", 0) + 1}

    def tools(state: AgentState) -> dict:
        last = state["messages"][-1]
        out: list[ToolMessage] = []
        for call in getattr(last, "tool_calls", []):
            name, args = call["name"], call.get("args") or {}
            if name not in specs:
                content = json.dumps({"error": f"Tool '{name}' is not available."})
                artifact = {"status": "error", "summary": f"Blocked: unknown tool {name}"}
            elif (key := _call_key(name, args)) in seen:
                content = json.dumps(
                    {
                        "note": "Already called with these arguments; result repeated below.",
                        "result": json.loads(seen[key]),
                    }
                )
                artifact = {"status": "success", "summary": "Repeated call (cached result)"}
            else:
                content, artifact = execute(ctx, name, *specs[name], args)
                if artifact["status"] == "success":
                    seen[key] = content
            out.append(
                ToolMessage(
                    content=content,
                    tool_call_id=call["id"],
                    name=name,
                    status=artifact["status"],
                    artifact=artifact,
                )
            )
        return {"messages": out}

    def finalize(state: AgentState) -> dict:
        msgs = [SystemMessage(SYSTEM_PROMPT), *state["messages"], HumanMessage(FINALIZE_PROMPT)]
        resp = llm.invoke(msgs)
        return {"messages": [AIMessage(content=str(resp.content))]}

    def after_agent(state: AgentState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    def after_tools(state: AgentState) -> str:
        return "finalize" if state.get("iterations", 0) >= limit else "agent"

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


def _event(kind: str, **data: Any) -> dict:
    assert kind in EVENT_TYPES, kind
    return {"type": kind, "data": data}


def cited_refs(text: str) -> list[str]:
    refs: list[str] = []
    for m in REF_RE.finditer(text):
        for r in re.findall(r"S\d+", m.group(0)):
            if r not in refs:
                refs.append(r)
    return refs


def history_messages(history: list[dict] | None) -> list[AnyMessage]:
    msgs: list[AnyMessage] = []
    for turn in history or []:
        cls = HumanMessage if turn.get("role") == "user" else AIMessage
        msgs.append(cls(content=str(turn.get("content", ""))))
    return msgs


async def stream_agent(
    question: str,
    ctx: AgentContext,
    llm: BaseChatModel,
    history: list[dict] | None = None,
    max_iterations: int | None = None,
    tool_names: list[str] | None = None,
) -> AsyncIterator[dict]:
    """Run the agent and yield UI events. Never raises: failures become an `error` event."""
    run_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    limit = max_iterations or get_settings().agent_max_iterations
    yield _event("run_started", run_id=run_id, question=question)
    yield _event("status", stage="planning", message="Planning the investigation")
    iterations, sent_sources, sent_wos, answered = 0, 0, 0, False
    names: dict[str, str] = {}
    try:
        graph = build_graph(ctx, llm, limit, tool_names)
        state = {"messages": [*history_messages(history), HumanMessage(question)], "iterations": 0}
        async for update in graph.astream(
            state, stream_mode="updates", config={"recursion_limit": 3 * limit + 5}
        ):
            for node, upd in update.items():
                if not upd:
                    continue
                msgs = upd.get("messages", [])
                iterations = upd.get("iterations", iterations)
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
                        yield _event(
                            "tool_completed",
                            call_id=m.tool_call_id,
                            tool=names.get(m.tool_call_id, m.name),
                            status=art.get("status", m.status),
                            summary=art.get("summary", ""),
                        )
                    new = list(ctx.citations.values())[sent_sources:]
                    if new:
                        sent_sources += len(new)
                        yield _event("sources", sources=[_source(c) for c in new])
                    for wo in ctx.work_orders[sent_wos:]:
                        sent_wos += 1
                        yield _event("work_order", **wo)
                    yield _event("status", stage="reasoning", message="Reviewing tool results")
                elif node in ("agent", "finalize") and msgs:
                    text = str(msgs[-1].content).strip()
                    refs = cited_refs(text)
                    known = ctx.by_ref()
                    answered = True
                    yield _event(
                        "answer",
                        text=text,
                        cited_refs=[r for r in refs if r in known],
                        unknown_refs=[r for r in refs if r not in known],
                        work_orders=list(ctx.work_orders),
                    )
        if not answered:
            yield _event("error", message="The agent stopped without an answer.")
    except Exception as exc:
        log.exception("agent run %s failed", run_id)
        yield _event("error", message=f"{type(exc).__name__}: {exc}")
    yield _event(
        "done",
        run_id=run_id,
        iterations=iterations,
        elapsed_s=round(time.perf_counter() - started, 2),
    )


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
