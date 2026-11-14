"""Developer CLI for the LLM / RAG / agent layer.

    uv run python scripts/agent_cli.py check [--pull]     # Ollama + models (pull only if missing)
    uv run python scripts/agent_cli.py ingest [--dir DIR] # index manuals into ChromaDB
    uv run python scripts/agent_cli.py search "query"     # test retrieval
    uv run python scripts/agent_cli.py ask "question" [--demo-db]
    uv run python scripts/agent_cli.py inspect-scans [--dir DIR] [--force]  # seeding step

--demo-db loads data/synthetic/*.csv into a temporary SQLite file for the run, so the agent can
be tried before the application database is seeded. It never touches the app database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from app.agent import llm  # noqa: E402
from app.config import get_settings  # noqa: E402


def cmd_check(args: argparse.Namespace) -> int:
    s = get_settings()
    st = llm.check_ollama()  # chat + embedding models: required by the agent
    if not st.reachable:
        print(f"Ollama NOT reachable at {st.host}: {st.error}")
        return 1
    print(f"Ollama at {st.host}. Installed: {', '.join(st.installed) or '(none)'}")
    if llm.check_ollama([s.vision_model]).missing:  # used by OCR ingestion, not the agent
        print(f"Optional (OCR vision) model not installed: {s.vision_model}")
    if st.missing:
        print(f"Missing: {', '.join(st.missing)}")
        if not args.pull:
            print("Re-run with --pull to download them (one-time, needs internet).")
            return 1
        for m in st.missing:
            print(f"Pulling {m} ...")
            with httpx.stream(
                "POST", f"{s.ollama_host}/api/pull", json={"model": m}, timeout=None
            ) as r:
                for line in r.iter_lines():
                    status = json.loads(line).get("status", "") if line else ""
                    if status and not status.startswith("pulling "):
                        print(f"  {status}")
    print("Testing generation ...")
    reply = llm.get_chat_model().invoke("Reply with exactly: OK").content
    print(f"  {s.llm_model}: {reply!r}")
    out = (
        llm.get_chat_model(format="json")
        .invoke('Return JSON {"pump": "P-101", "status": "ok"} and nothing else.')
        .content
    )
    print(f"  JSON mode: {json.loads(out)}")
    vec = llm.get_embeddings().embed_query("mechanical seal leakage")
    print(f"  {s.embed_model}: {len(vec)}-dim embedding")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from app.agent.rag import ManualStore, ingest_directory

    llm.require_ollama([get_settings().embed_model])
    store = ManualStore.from_settings()
    for r in ingest_directory(store, Path(args.dir or get_settings().manuals_dir)):
        print(f"  {r.status:8} {r.chunks:3} chunks  {r.source}")
    print(f"Collection now has {store.count()} chunks.")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from app.agent.rag import ManualStore

    for c in ManualStore.from_settings().search(args.query, k=args.k):
        print(f"[{c.score:.3f}] {c.label()}\n    {c.text[:200]!r}")
    return 0


def _demo_db() -> Path:
    import pandas as pd

    from app.db import connect, init_db

    path = Path(tempfile.mkdtemp()) / "demo.db"
    conn = connect(path)
    init_db(conn)
    syn = ROOT / "data" / "synthetic"
    pd.read_csv(syn / "assets.csv").to_sql("assets", conn, if_exists="append", index=False)
    pd.read_csv(syn / "work_orders.csv").to_sql(
        "work_orders", conn, if_exists="append", index=False
    )
    conn.close()
    return path


def cmd_ask(args: argparse.Namespace) -> int:
    from app.agent.graph import stream_agent
    from app.api.agent import make_context

    s = get_settings()
    if args.demo_db:
        s.db_path = _demo_db()
        print(f"(demo database: {s.db_path})")
    llm.require_ollama()
    ctx = make_context()

    async def run() -> None:
        async for ev in stream_agent(args.question, ctx, llm.get_chat_model()):
            t, d = ev["type"], ev["data"]
            if t == "tool_started":
                print(f"-> {d['tool']}({json.dumps(d['args'])})")
            elif t == "tool_completed":
                print(f"   [{d['status']}] {d['summary']}")
            elif t == "sources":
                for src in d["sources"]:
                    print(f"   {src['ref']}: {src['title']} p.{src['page']} ({src['score']})")
            elif t == "blocked":
                print(
                    f"   BLOCKED {d['tool']} -> {d['target']} ({d['reason']}; from {d['source']})"
                )
            elif t == "document":
                print(f"   document: {d['file_name']}  {d['download_url']}")
            elif t == "answer":
                print(f"\n{d['text']}\n")
            elif t in ("error", "done"):
                print(f"[{t}] {d}")

    asyncio.run(run())
    return 0


def cmd_inspect_scans(args: argparse.Namespace) -> int:
    """Seeding step: read data/scans/* with the vision model into the inspections table."""
    from app.agent.inspections import ingest_scans
    from app.db import connect, init_db

    s = get_settings()
    llm.require_ollama([s.vision_model])
    conn = connect(s.db_path)
    init_db(conn)
    try:
        reports = ingest_scans(conn, Path(args.dir) if args.dir else None, force=args.force)
    finally:
        conn.close()
    for r in reports:
        print(f"  {r.status:8} {r.inspection_id or '-':24} {r.file}  {r.detail}")
    if not reports:
        print(f"No scans found in {args.dir or s.scans_dir}")
    return 1 if any(r.status == "failed" for r in reports) else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--pull", action="store_true")
    i = sub.add_parser("ingest")
    i.add_argument("--dir")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--demo-db", action="store_true")
    sc = sub.add_parser("inspect-scans", help="seeding: scans -> inspections table (slow)")
    sc.add_argument("--dir")
    sc.add_argument("--force", action="store_true", help="re-read scans already in the DB")
    args = p.parse_args()
    commands = {
        "check": cmd_check,
        "ingest": cmd_ingest,
        "search": cmd_search,
        "ask": cmd_ask,
        "inspect-scans": cmd_inspect_scans,
    }
    return commands[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
