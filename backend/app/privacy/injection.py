"""The injection drill: prove the guard holds even if the model is fully fooled.

A real model may or may not obey an instruction hidden in a document, so a demo that waits
for it to misbehave proves little either way. The drill assumes the worst case instead: it
reads the poisoned vendor document for real, takes the destination the document asks for, and
submits exactly that tool call to the same guard the agent uses. The call is blocked and
audited like any other. No model is involved, and nothing is sent anywhere.

Events use the agent's stream shape (graph.EVENT_TYPES) so the UI renders them unchanged.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from app.agent.rag import SUPPORTED_SUFFIXES, ManualPage, load_document
from app.agent.tools import INJECTION_RE, ToolGuard, _find_target
from app.guard.audit import write_audit

EXFIL_TOOL = "send_data"  # what the planted instruction asks for; not on the allow-list
EXFIL_PAYLOAD = "asset register and failure history"


def find_injection(docs_dir: Path) -> tuple[ManualPage, str] | None:
    """First page under `docs_dir` carrying an injected instruction, with its destination."""
    if not docs_dir.is_dir():
        return None
    for path in sorted(docs_dir.iterdir()):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        for page in load_document(path):
            if INJECTION_RE.search(page.text) and (target := _find_target(page.text)):
                return page, target
    return None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run_drill(guard: ToolGuard, conn, docs_dir: Path, user: str, role: str) -> Iterator[dict]:
    """Yield the drill as agent-style events. Always ends with `done`."""
    run_id, started = uuid.uuid4().hex[:12], time.perf_counter()

    def ev(kind: str, **data) -> dict:
        return {"type": kind, "data": data}

    def done(calls: int) -> dict:
        elapsed = round(time.perf_counter() - started, 2)
        return ev("done", run_id=run_id, tool_calls=calls, elapsed_s=elapsed)

    yield ev("run_started", run_id=run_id, question="Injection drill: poisoned vendor document")
    yield ev("status", stage="reading", message="Reading the vendor document")

    read_id = f"call_{uuid.uuid4().hex[:8]}"
    yield ev("tool_started", call_id=read_id, tool="read_document", args={"folder": docs_dir.name})
    t0 = time.perf_counter()
    try:
        found = find_injection(docs_dir)
    except Exception as exc:  # unreadable or corrupt document
        found, problem = None, f"Could not read the vendor document: {exc}"
    else:
        problem = f"No document with an injected instruction in {docs_dir.name}/"
    if found is None:
        yield ev(
            "tool_completed",
            call_id=read_id,
            tool="read_document",
            status="error",
            summary=problem,
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
        yield ev("error", message=problem)
        yield done(1)
        return

    page, target = found
    source = f"{page.title or page.source}, page {page.page}"
    summary = f"Hidden instruction found in {source}: send data to {target}"
    write_audit(
        conn,
        {
            "ts": _now(),
            "user": user,
            "role": role,
            "action": "injection_drill",
            "tool": "read_document",
            "input": page.source,
            "output": summary,
            "status": "allowed",
        },
    )
    yield ev(
        "tool_completed",
        call_id=read_id,
        tool="read_document",
        status="success",
        summary=summary,
        duration_ms=int((time.perf_counter() - t0) * 1000),
    )

    # Worst case: the model obeys. Submit the call the document asked for to the real guard.
    yield ev("status", stage="guard", message="Submitting the injected request to the guard")
    args = {"url": target, "data": EXFIL_PAYLOAD}
    call_id = f"call_{uuid.uuid4().hex[:8]}"
    yield ev("tool_started", call_id=call_id, tool=EXFIL_TOOL, args=args)
    t0 = time.perf_counter()
    decision = guard.check(EXFIL_TOOL, args)
    blocked_id = f"blk-{uuid.uuid4().hex[:8]}"  # same id in the stream and in the table
    status = "allowed" if decision.allowed else "blocked"
    outcome = (
        "NOT BLOCKED: the guard let this call through"
        if decision.allowed
        else (f"Blocked: {decision.reason}")
    )
    guard.record(
        {
            "ts": _now(),
            "user": user,
            "role": role,
            "action": "injection_drill",
            "tool": EXFIL_TOOL,
            "input": f'{{"url": "{target}", "data": "{EXFIL_PAYLOAD}"}}',
            "output": outcome,
            "status": "error" if decision.allowed else "blocked",
            "reason": decision.reason,
            "target": decision.target or target,
            "source": source,
            "blocked_id": blocked_id,
        }
    )
    if not decision.allowed:
        yield ev(
            "blocked",
            id=blocked_id,
            call_id=call_id,
            at=_now(),
            tool=EXFIL_TOOL,
            target=decision.target or target,
            source=source,
            reason=decision.reason,
        )
    yield ev(
        "tool_completed",
        call_id=call_id,
        tool=EXFIL_TOOL,
        status="error" if decision.allowed else status,
        summary=outcome,
        duration_ms=int((time.perf_counter() - t0) * 1000),
    )
    if decision.allowed:
        yield ev("error", message="Guard failure: the injected request was not blocked.")
    else:
        text = (
            f"{source} contained a hidden instruction to send plant data to {target}. "
            "The request was blocked by the guard and recorded in the audit log. "
            "No data left the plant."
        )
        yield ev("answer", text=text, cited_refs=[], unknown_refs=[], documents=[])
    yield done(2)
