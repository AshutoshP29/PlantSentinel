"""Load everything the demo needs, in one command. Safe to re-run.

    uv run python scripts/seed_demo.py              # local
    uv run python scripts/seed_demo.py --reset      # start from an empty database
    docker compose run --rm backend python /app/scripts/seed_demo.py   # inside the stack

Steps (paths come from app.config, so DATA_DIR / DB_PATH / MODELS_DIR are respected):
  1 data         synthetic assets + work orders (generated only if missing, or --regenerate)
  2 scans        inspection report images (rendered only if missing)
  3 database     schema + equipment register + work orders
  4 clustering   failure modes: precomputed (default, deterministic) or --cluster live (Ollama)
  5 risk model   XGBoost on AI4I (trained only if missing, or --retrain)
  6 manuals      chunk + embed manuals into ChromaDB (needs Ollama embeddings)
  7 inspections  OCR scans into the inspections table (when the ingestion pipeline exists)
  8 verify       the planted story: P-101, C-203, E-302 are the top bad actors

Required steps (1-5, 8) fail the run; Ollama-dependent steps (6, 7) warn and continue.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd  # noqa: E402

from app.config import get_settings  # noqa: E402

STORY = ["P-101", "C-203", "E-302"]
OK, WARN, FAIL = "ok", "warn", "FAIL"


class StepError(RuntimeError):
    """A required step failed."""


class Skipped(RuntimeError):  # noqa: N818 - control flow, not an error
    """An optional step could not run; the message says why."""


# --------------------------------------------------------------------------- steps


def step_data(args: argparse.Namespace) -> str:
    syn = get_settings().data_dir / "synthetic"
    needed = [syn / "assets.csv", syn / "work_orders.csv"]
    if args.regenerate or not all(p.exists() for p in needed):
        import generate_synthetic

        generate_synthetic.main(["--seed", str(args.seed), "--out", str(syn)])
        return "generated"
    wo = pd.read_csv(needed[1])
    return f"{len(pd.read_csv(needed[0]))} assets, {len(wo)} work orders (existing files)"


def step_scans(args: argparse.Namespace) -> str:
    scans = get_settings().data_dir / "scans"
    found = sorted(scans.glob("INSP-*.jpg"))
    if found and not args.regenerate:
        return f"{len(found)} reports (existing files)"
    import make_demo_scans

    make_demo_scans.main(["--out", str(scans)])
    return f"{len(list(scans.glob('INSP-*.jpg')))} reports rendered"


def step_database(args: argparse.Namespace) -> str:
    from app.db import connect, init_db
    from app.ingestion.work_orders import ingest_assets, ingest_work_orders

    s = get_settings()
    if args.reset and s.db_path.exists():
        s.db_path.unlink()
    syn = s.data_dir / "synthetic"
    conn = connect(s.db_path)
    try:
        init_db(conn)
        a = ingest_assets(conn, pd.read_csv(syn / "assets.csv"))
        w = ingest_work_orders(conn, pd.read_csv(syn / "work_orders.csv"))
    finally:
        conn.close()
    if a["rejected"] or w["rejected"]:
        raise StepError(f"rejected rows: assets {a['rejected']}, work orders {w['errors']}")
    return f"{s.db_path.name}: {a['upserted']} assets, {w['inserted']} new work orders"


def step_clustering(args: argparse.Namespace) -> str:
    from app.analytics import cluster
    from app.db import connect

    conn = connect(get_settings().db_path)
    try:
        if args.cluster == "live":
            result = cluster.recluster(conn)  # falls back by itself if Ollama fails
        else:
            result = cluster.load_fallback()
            cluster.apply_to_db(conn, result)
        unassigned = conn.execute(
            "SELECT COUNT(*) FROM work_orders WHERE failure_mode_id IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    n_modes = len([m for m in result.modes if m != cluster.UNCLASSIFIED])
    source = result.metrics.get("source", "fallback")
    return f"{n_modes} failure modes ({source}), {unassigned} work orders unassigned"


def step_risk(args: argparse.Namespace) -> str:
    from app.analytics import risk

    if risk.model_path().exists() and risk.meta_path().exists() and not args.retrain:
        return f"model present ({risk.model_path().name})"
    import train_risk_model

    assets = get_settings().data_dir / "synthetic" / "assets.csv"
    train_risk_model.main(["--assets", str(assets)])
    return "trained"


def step_manuals(args: argparse.Namespace) -> str:
    if args.skip_manuals:
        raise Skipped("skipped (--skip-manuals)")
    from app.agent.llm import check_ollama

    s = get_settings()
    status = check_ollama([s.embed_model])
    if not status.ready:
        raise Skipped(f"Ollama not ready ({status.error or 'missing ' + str(status.missing)})")
    from app.agent.rag import ManualStore, ingest_directory

    store = ManualStore.from_settings()
    reports = ingest_directory(store, s.manuals_dir)
    changed = sum(r.chunks for r in reports if r.status in ("added", "replaced"))
    return f"{len(reports)} manuals, {store.count()} chunks indexed ({changed} new)"


def step_inspections(args: argparse.Namespace) -> str:
    if args.skip_inspections:
        raise Skipped("skipped (--skip-inspections)")
    try:
        mod = importlib.import_module("app.ingestion.inspections")
    except ImportError:
        raise Skipped("pipeline not built yet (app.ingestion.inspections)") from None
    fn = getattr(mod, "ingest_scans", None)
    if fn is None:
        raise Skipped("app.ingestion.inspections has no ingest_scans(conn, directory)")
    from app.db import connect

    conn = connect(get_settings().db_path)
    try:
        result = fn(conn, get_settings().data_dir / "scans")
    finally:
        conn.close()
    return str(result)


def step_verify(args: argparse.Namespace) -> str:
    from app.analytics.bad_actors import score_bad_actors
    from app.db import connect

    s = get_settings()
    conn = connect(s.db_path)
    try:
        latest = conn.execute("SELECT MAX(date) FROM work_orders").fetchone()[0]
        rows = score_bad_actors(conn, s.analysis_as_of)
    finally:
        conn.close()
    top = [r["tag"] for r in rows[:3]]
    if top != STORY:
        raise StepError(f"top bad actors are {top}, expected {STORY}")
    p101 = rows[0]
    msg = (
        f"top 3 = {', '.join(top)}; P-101 {p101['failure_mode']}: "
        f"{p101['count_180d']} in 180 d, MTBF {p101['mtbf_previous_days']:.0f} -> "
        f"{p101['mtbf_current_days']:.0f} d"
    )
    if s.analysis_as_of is None and latest and (date.today() - date.fromisoformat(latest)).days > 3:
        msg += f". Tip: set ANALYSIS_AS_OF={latest} so 'today' matches the data"
    return msg


STEPS: list[tuple[str, Callable[[argparse.Namespace], str], bool]] = [
    ("data", step_data, True),
    ("scans", step_scans, True),
    ("database", step_database, True),
    ("clustering", step_clustering, True),
    ("risk model", step_risk, True),
    ("manuals", step_manuals, False),
    ("inspections", step_inspections, False),
    ("verify", step_verify, True),
]


# --------------------------------------------------------------------------- runner


def run(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    results = []
    for i, (name, fn, required) in enumerate(STEPS, 1):
        t = time.perf_counter()
        try:
            status, detail = OK, fn(args)
        except Skipped as exc:
            status, detail = WARN, str(exc)
        except Exception as exc:
            status = FAIL if required else WARN
            detail = f"{type(exc).__name__}: {exc}"
        took = time.perf_counter() - t
        print(f"[{i}/{len(STEPS)}] {name:<12} {status:<4} {detail}  ({took:.1f}s)", flush=True)
        results.append((name, status, detail))
        if status == FAIL:
            break
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reset", action="store_true", help="delete the database first")
    p.add_argument("--regenerate", action="store_true", help="regenerate synthetic data/scans")
    p.add_argument("--seed", type=int, default=42, help="seed for --regenerate")
    p.add_argument("--cluster", choices=["fallback", "live"], default="fallback")
    p.add_argument("--retrain", action="store_true", help="retrain the risk model")
    p.add_argument("--skip-manuals", action="store_true")
    p.add_argument("--skip-inspections", action="store_true")
    args = p.parse_args(argv)

    results = run(args)
    failed = [n for n, s, _ in results if s == FAIL]
    warned = [n for n, s, _ in results if s == WARN]
    if failed:
        print(f"\nSeed FAILED at: {failed[0]}")
        return 1
    print(f"\nSeed complete{' with warnings: ' + ', '.join(warned) if warned else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
