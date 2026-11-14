"""Adapter from agent events (graph.EVENT_TYPES) to the frontend's `AgentEvent` contract.

frontend/src/api/types.ts:

    {type: "step", step: {id, tool, summary, status: running|done|blocked|error, duration_ms}}
    {type: "token", text}
    {type: "done", citations: [{id, kind: inspection|manual|work_orders, label, title, quote}],
                   can_draft_work_order}
    {type: "blocked", attempt: {id, at, tool, target, source, reason}}
    {type: "error", message}

The answer cites [S3], [INSP-P101-20261102], [WO-0069]; the UI renders numbered refs, so refs
are renumbered [1], [2], ... in order of first appearance while tokens stream, and `done`
carries the matching citation list.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from app.agent.graph import BRACKET_RE, REF_TOKEN, known_refs
from app.agent.tools import AgentContext

STEP_STATUS = {"success": "done", "error": "error", "blocked": "blocked"}
MAX_HOLD = 200  # longest unclosed "[..." held back while streaming


def _args_summary(args: dict) -> str:
    return ", ".join(
        f"{k}={json.dumps(v) if not isinstance(v, str) else v}" for k, v in args.items()
    )


class FrontendStream:
    def __init__(self, ctx: AgentContext, tag: str | None = None) -> None:
        self.ctx = ctx
        self.tag = tag
        self.numbers: dict[str, int] = {}
        self.pending = ""
        self.streamed = False
        self.steps: dict[str, dict] = {}

    # ------------------------------------------------------------------ refs

    def _number(self, ref: str) -> int:
        if ref not in self.numbers:
            self.numbers[ref] = len(self.numbers) + 1
        return self.numbers[ref]

    def _renumber(self, text: str) -> str:
        known = known_refs(self.ctx)

        def sub(m: re.Match) -> str:
            refs = re.findall(REF_TOKEN, m.group(1))
            rest = re.sub(REF_TOKEN, "", m.group(1)).replace(",", "").replace(";", "").strip()
            if not refs or rest:  # not a citation bracket (e.g. a markdown link) -> unchanged
                return m.group(0)
            nums = [self._number(r) for r in refs if r in known]
            return "".join(f"[{n}]" for n in nums)

        return BRACKET_RE.sub(sub, text)

    def _feed(self, text: str, final: bool = False) -> str:
        """Renumber streamed text, holding back a trailing unclosed '[...'."""
        buf = self.pending + text
        cut = buf.rfind("[")
        if not final and cut != -1 and "]" not in buf[cut:] and len(buf) - cut <= MAX_HOLD:
            self.pending, buf = buf[cut:], buf[:cut]
        else:
            self.pending = ""
        return self._renumber(buf)

    # ------------------------------------------------------------------ events

    def convert(self, ev: dict) -> list[dict]:
        t, d = ev["type"], ev["data"]
        if t == "tool_started":
            step = {
                "id": d["call_id"],
                "tool": d["tool"],
                "summary": _args_summary(d.get("args") or {}),
                "status": "running",
            }
            self.steps[d["call_id"]] = step
            return [{"type": "step", "step": step}]
        if t == "tool_completed":
            step = {
                **self.steps.get(d["call_id"], {"id": d["call_id"], "tool": d["tool"]}),
                "summary": d.get("summary", ""),
                "status": STEP_STATUS.get(d.get("status", ""), "done"),
            }
            if d.get("duration_ms") is not None:
                step["duration_ms"] = d["duration_ms"]
            return [{"type": "step", "step": step}]
        if t == "blocked":
            attempt = {k: d.get(k, "") for k in ("id", "at", "tool", "target", "source", "reason")}
            return [{"type": "blocked", "attempt": attempt}]
        if t == "answer_delta":
            self.streamed = True
            out = self._feed(d["text"])
            return [{"type": "token", "text": out}] if out else []
        if t == "answer":
            out = self._feed("", final=True) if self.streamed else self._renumber(d["text"])
            self.streamed = False
            return [{"type": "token", "text": out}] if out else []
        if t == "error":
            return [{"type": "error", "message": d.get("message", "Agent error")}]
        if t == "done":
            return [
                {
                    "type": "done",
                    "citations": self.citations(),
                    "can_draft_work_order": self.can_draft(),
                }
            ]
        return []

    # ------------------------------------------------------------------ done payload

    def citations(self) -> list[dict]:
        by_ref = self.ctx.by_ref()
        out = []
        for ref, n in sorted(self.numbers.items(), key=lambda kv: kv[1]):
            if ref in by_ref:
                c = by_ref[ref]
                name = c.title or c.source
                out.append(
                    {
                        "id": n,
                        "kind": "manual",
                        "label": f"Manual · p. {c.page}",
                        "title": f"{name} · page {c.page}"
                        + (f" · {c.section}" if c.section else ""),
                        "quote": c.text,
                    }
                )
            elif ref in self.ctx.inspections:
                i = self.ctx.inspections[ref]
                flagged = [f for f in i["findings"] if f["flagged"]] or i["findings"]
                report = f"Inspection report {i['report_no']}" if i.get("report_no") else ref
                out.append(
                    {
                        "id": n,
                        "kind": "inspection",
                        "label": f"Inspection · p. {i['page']}",
                        "title": f"{report} · page {i['page']}",
                        "quote": "; ".join(f"{f['item']}: {f['result']}" for f in flagged),
                    }
                )
            elif ref in self.ctx.seen_work_orders:
                w = self.ctx.seen_work_orders[ref]
                out.append(
                    {
                        "id": n,
                        "kind": "work_orders",
                        "label": "Work orders",
                        "title": f"{ref} · {w['date']}",
                        "quote": f"{w['description']} -> {w['action_taken']}",
                    }
                )
        return out

    def can_draft(self) -> bool:
        if any(doc.get("kind") == "work_order" for doc in self.ctx.documents):
            return False
        tags = {i["tag"] for i in self.ctx.inspections.values()} | set(self.ctx.patterns)
        if self.tag:
            tags.add(self.tag)
        return bool(tags)


async def frontend_stream(
    events: AsyncIterator[dict], ctx: AgentContext, tag: str | None = None
) -> AsyncIterator[dict]:
    """Wrap any agent event stream (stream_agent, stream_injection_test) in the UI contract."""
    adapter = FrontendStream(ctx, tag)
    async for ev in events:
        for out in adapter.convert(ev):
            yield out
