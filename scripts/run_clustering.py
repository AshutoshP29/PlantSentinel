"""Cluster the synthetic work orders with the real models, evaluate, and save artefacts.

Writes:
    data/synthetic/clusters_fallback.json   (used if live clustering fails during the demo)
    models/metrics.json  -> "clustering" section (silhouette, ARI vs ground truth, ...)

Needs Ollama running with the embedding and LLM models.
    uv run python scripts/run_clustering.py
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import adjusted_rand_score, homogeneity_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analytics.bad_actors import compute_bad_actors  # noqa: E402
from app.analytics.cluster import cluster_work_orders, save_fallback  # noqa: E402
from app.analytics.metrics import write_metrics  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic")
    p.add_argument("--min-cluster-size", type=int, default=8)
    p.add_argument("--merge-distance", type=float, default=0.12)
    args = p.parse_args(argv)

    wo = pd.read_csv(args.data / "work_orders.csv")
    result = cluster_work_orders(
        wo, min_cluster_size=args.min_cluster_size, merge_distance=args.merge_distance
    )
    wo["failure_mode"] = wo["id"].map(result.assignments)

    metrics = dict(result.metrics)
    truth_file = args.data / "work_orders_truth.csv"
    if truth_file.exists():
        truth = wo.merge(pd.read_csv(truth_file), on="id")
        metrics["ari_vs_truth"] = round(adjusted_rand_score(truth.true_mode, truth.failure_mode), 4)
        metrics["homogeneity_vs_truth"] = round(
            homogeneity_score(truth.true_mode, truth.failure_mode), 4
        )
        metrics["n_true_modes"] = int(truth.true_mode.nunique())
        print("\ntrue mode -> assigned failure mode (counts)")
        print(pd.crosstab(truth.true_mode, truth.failure_mode).to_string())

    save_fallback(result, args.data / "clusters_fallback.json")
    write_metrics("clustering", metrics)

    print("\nfailure modes:")
    for name, desc in result.modes.items():
        print(f"  {name:35s} {(wo.failure_mode == name).sum():4d}  {desc}")
    print("\nmetrics:", metrics)

    assets = pd.read_csv(args.data / "assets.csv")
    ba = compute_bad_actors(wo, assets)
    cols = ["tag", "failure_mode", "count_180d", "mtbf_current_days", "mtbf_previous_days"]
    print("\ntop bad actors:")
    print(ba[[*cols, "mtbf_drop_pct", "bad_actor_score", "flagged"]].head(8).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
