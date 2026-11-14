"""Run every beat of the demo (spec section 16) against the running stack, through the gateway.

Talks to the gateway exactly as the browser does, so with Wi-Fi off it proves the whole demo
works offline. Standard library only.

    uv run python scripts/demo_check.py                 # http://127.0.0.1:8080
    uv run python scripts/demo_check.py --base http://127.0.0.1:8080 --skip-agent

Exit code 0 only if every beat passes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator

QUESTION = "Why does P-101 keep failing and what should we do?"
HEADERS = {"X-Role": "engineer", "X-User": "demo-check", "X-Plant-Role": "reliability_engineer"}


class BeatFailedError(AssertionError):
    """A demo beat did not hold."""


def _request(base: str, method: str, path: str, body: dict | None, timeout: float):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    for k, v in {**HEADERS, "Content-Type": "application/json"}.items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(base: str, path: str, timeout: float = 30) -> object:
    with _request(base, "GET", path, None, timeout) as r:
        return json.loads(r.read())


def post_json(base: str, path: str, body: dict, timeout: float = 120) -> object:
    with _request(base, "POST", path, body, timeout) as r:
        return json.loads(r.read())


def sse(base: str, path: str, body: dict, timeout: float = 300) -> Iterator[dict]:
    """POST and yield each JSON `data:` event of a server-sent-event stream."""
    with _request(base, "POST", path, body, timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    yield json.loads(payload)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise BeatFailedError(msg)


# --------------------------------------------------------------------------- beats


def beat_stack(base: str) -> str:
    with _request(base, "GET", "/", None, 15) as r:
        html = r.read().decode("utf-8", "replace")
    expect('<div id="root"' in html or "<script" in html, "UI index.html not served")
    h = get_json(base, "/api/health")
    expect(h.get("db") is True, f"database not ready: {h}")
    expect(h.get("ollama") is True, f"Ollama not reachable from the backend: {h}")
    st = get_json(base, "/api/agent/status")
    expect(st.get("ready") is True, f"agent not ready: {st}")
    return f"UI served, db + ollama ok, {st.get('manual_chunks')} manual chunks indexed"


def beat_dashboard(base: str) -> str:
    s = get_json(base, "/api/dashboard/summary")
    top = get_json(base, "/api/bad-actors?top_n=3")
    tags = [r["tag"] for r in top]
    expect(tags == ["P-101", "C-203", "E-302"], f"top bad actors are {tags}")
    p = top[0]
    expect(p["count_180d"] == 4, f"P-101 has {p['count_180d']} events in 180 d, expected 4")
    drop = round(p["mtbf_drop_pct"] * 100)
    expect(drop >= 60, f"P-101 MTBF drop only {drop}%")
    modes = get_json(base, "/api/failure-modes")
    expect(any(m["name"] == "Mechanical Seal Leakage" for m in modes), "seal failure mode missing")
    return (
        f"{s['bad_actors_flagged']} bad actors; P-101 {p['failure_mode']}: 4 in 180 d, "
        f"MTBF {p['mtbf_previous_days']:.0f} -> {p['mtbf_current_days']:.0f} d (-{drop}%)"
    )


def beat_asset(base: str) -> str:
    risk = get_json(base, "/api/risk/P-101")
    expect(risk["risk_level"] == "high", f"P-101 risk is {risk['risk_level']}")
    insp = get_json(base, "/api/assets/P-101/inspection")
    expect(insp.get("id") == "INSP-004", f"latest inspection is {insp.get('id')}")
    hit = [f for f in insp.get("findings", []) if "0.3 mm" in f"{f.get('item')} {f.get('result')}"]
    expect(bool(hit), "INSP-004 has no 0.3 mm misalignment finding")
    expect(hit[0].get("flagged") is True, "misalignment finding is not flagged")
    return f"risk {risk['risk_score']:.2f} ({risk['reasons'][0]['label']}); INSP-004 shows 0.3 mm"


def beat_agent(base: str) -> str:
    t = time.perf_counter()
    steps, text, done, errors = [], [], None, []
    for ev in sse(base, "/api/agent/ask", {"question": QUESTION, "tag": "P-101"}):
        kind = ev.get("type")
        if kind == "step" and ev["step"].get("status") in ("done", "error", "blocked"):
            steps.append(ev["step"]["tool"])
        elif kind == "token":
            text.append(ev["text"])
        elif kind == "done":
            done = ev
        elif kind == "error":
            errors.append(ev.get("message"))
    secs = time.perf_counter() - t
    answer = "".join(text)
    expect(not errors, f"agent error: {errors}")
    expect(done is not None, "stream ended without a done event")
    for tool in ("read_inspection", "search_manuals"):
        expect(tool in steps, f"agent never called {tool} (steps: {steps})")
    # /ask renumbers refs [1], [2], ... for the UI; the inspection id is in the title.
    cites = done.get("citations", [])
    insp = [c for c in cites if c.get("kind") == "inspection" and "INSP-004" in c.get("title", "")]
    expect(bool(insp), f"INSP-004 not cited (citations: {[c.get('title') for c in cites]})")
    expect(any(c.get("kind") == "manual" for c in cites), "no manual passage cited")
    expect("0.3" in answer and "0.05" in answer, "answer lacks 0.3 mm vs 0.05 mm")
    expect("misalign" in answer.lower(), "answer does not name misalignment")
    return f"{len(steps)} tools, cites INSP-004, 0.3 mm vs 0.05 mm, {secs:.0f} s"


def beat_work_order(base: str) -> str:
    doc = post_json(base, "/api/documents/work-order", {"tag": "P-101", "requested_by": "demo"})
    doc_id = doc.get("id") or doc.get("doc_id")
    expect(bool(doc_id), f"no document id in {doc}")
    with _request(base, "GET", f"/api/documents/{doc_id}/download", None, 60) as r:
        blob = r.read()
    expect(blob[:2] == b"PK", "download is not a .docx (zip) file")
    return f"{doc.get('file_name', doc_id)} ({len(blob) // 1024} KB)"


def beat_privacy(base: str) -> str:
    st = get_json(base, "/api/privacy/status")
    expect(st.get("external_connections") == 0, f"external connections: {st}")
    blocked = None
    for ev in sse(base, "/api/privacy/injection-test", {}, timeout=120):
        if "target" in ev and "tool" in ev and "reason" in ev:
            blocked = ev
    expect(blocked is not None, "injection test produced no blocked attempt")
    expect("evil.example" in blocked["target"], f"blocked target is {blocked['target']}")
    rows = get_json(base, "/api/audit-log?page=1")
    rows = rows if isinstance(rows, list) else rows.get("items", rows.get("rows", []))
    expect(any(r.get("status") == "blocked" for r in rows), "no blocked row in the audit log")
    return f"0 external connections; {blocked['tool']} -> {blocked['target']} blocked and audited"


BEATS: list[tuple[str, Callable[[str], str]]] = [
    ("stack", beat_stack),
    ("dashboard", beat_dashboard),
    ("asset detail", beat_asset),
    ("ask agent", beat_agent),
    ("work order", beat_work_order),
    ("privacy", beat_privacy),
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", default="http://127.0.0.1:8080")
    p.add_argument("--skip-agent", action="store_true", help="skip the (slow) agent question")
    args = p.parse_args(argv)

    failed = 0
    for name, fn in BEATS:
        if args.skip_agent and fn is beat_agent:
            print(f"SKIP  {name}")
            continue
        t = time.perf_counter()
        try:
            detail, status = fn(args.base), "PASS"
        except BeatFailedError as exc:
            detail, status = str(exc), "FAIL"
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as exc:
            detail, status = f"{type(exc).__name__}: {exc}", "FAIL"
        failed += status == "FAIL"
        print(f"{status}  {name:<13} {detail}  ({time.perf_counter() - t:.1f}s)", flush=True)
    print("\nDEMO READY" if not failed else f"\n{failed} beat(s) failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
