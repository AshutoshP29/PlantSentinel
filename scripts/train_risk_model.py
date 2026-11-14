"""Train the XGBoost risk model on AI4I 2020 and map operating conditions to assets.

Writes:
    models/risk_xgb.json                    trained model (git-ignored, rebuilt by `seed`)
    models/risk_meta.json                   threshold + feature medians used for explanations
    models/metrics.json                     "risk_model" section (F1, ROC-AUC, ...)
    data/synthetic/asset_conditions.csv     one held-out AI4I row per asset

    uv run python scripts/train_risk_model.py
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analytics import risk  # noqa: E402
from app.analytics.ai4i import load_ai4i  # noqa: E402
from app.analytics.metrics import write_metrics  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--assets", type=Path, default=ROOT / "data" / "synthetic" / "assets.csv")
    args = p.parse_args(argv)

    df = load_ai4i()
    model, metrics, test_df = risk.train(df, seed=args.seed)

    model_file, meta_file = risk.model_path(), risk.meta_path()
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(model_file)
    meta = {"threshold": metrics["threshold"], "medians": risk.feature_medians(df)}
    meta_file.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    write_metrics("risk_model", metrics)

    tags = pd.read_csv(args.assets)["tag"].tolist()
    conditions = risk.assign_conditions(tags, test_df, seed=args.seed)
    conditions.to_csv(risk.conditions_path(), index=False)

    print("metrics:", {k: v for k, v in metrics.items() if k != "features"})
    print("\nasset risk (top 8):")
    scored = [risk.predict_risk(t) for t in tags]
    for r in sorted(scored, key=lambda r: -r["risk_score"])[:8]:
        why = "; ".join(x["text"] for x in r["reasons"])
        print(f"  {r['tag']:6s} {r['risk_score']:.3f} {r['risk_level']:6s} {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
