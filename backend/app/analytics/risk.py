"""F4: failure-risk model (XGBoost on AI4I 2020) with SHAP explanations.

Training lives here so it can be unit-tested; scripts/train_risk_model.py does the IO.
At runtime each asset gets a "current operating condition" (one AI4I row, see
data/synthetic/asset_conditions.csv) and predict_risk(tag) scores + explains it.
"""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from app.analytics.ai4i import (
    FEATURE_LABELS,
    FEATURES,
    NUMERIC_FEATURES,
    TARGET,
    add_features,
)
from app.config import get_settings

UNITS = {
    "air_temp_k": "K",
    "process_temp_k": "K",
    "rpm": "rpm",
    "torque_nm": "Nm",
    "tool_wear_min": "min",
    "temp_diff_k": "K",
    "power_kw": "kW",
    "strain_nm_min": "Nm.min",
    "type_code": "",
}
DUTY = {0: "L", 1: "M", 2: "H"}
HIGH, MEDIUM = 0.6, 0.3


def risk_level(score: float) -> str:
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"


# --------------------------------------------------------------------------- training


def make_model(pos_weight: float, seed: int = 42) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        n_estimators=400,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        scale_pos_weight=pos_weight,
        eval_metric="logloss",
        random_state=seed,
        n_jobs=1,  # deterministic
    )


def best_f1_threshold(y_true: np.ndarray, proba: np.ndarray) -> float:
    grid = np.round(np.arange(0.05, 0.96, 0.01), 2)
    scores = [f1_score(y_true, proba >= t, zero_division=0) for t in grid]
    return float(grid[int(np.argmax(scores))])


def train(df: pd.DataFrame, seed: int = 42) -> tuple[xgb.XGBClassifier, dict, pd.DataFrame]:
    """Stratified train / validation / test split (64/16/20).

    The decision threshold is tuned on validation only; metrics are reported on test.
    Returns (model, metrics, test_frame_with_proba).
    """
    train_df, test_df = train_test_split(df, test_size=0.2, stratify=df[TARGET], random_state=seed)
    fit_df, val_df = train_test_split(
        train_df, test_size=0.2, stratify=train_df[TARGET], random_state=seed
    )
    pos = fit_df[TARGET].sum()
    model = make_model(pos_weight=(len(fit_df) - pos) / pos, seed=seed)
    model.fit(fit_df[FEATURES], fit_df[TARGET])

    threshold = best_f1_threshold(
        val_df[TARGET].to_numpy(), model.predict_proba(val_df[FEATURES])[:, 1]
    )
    proba = model.predict_proba(test_df[FEATURES])[:, 1]
    y, pred = test_df[TARGET].to_numpy(), proba >= threshold
    metrics = {
        "model": "xgboost",
        "dataset": "AI4I 2020",
        "n_train": len(fit_df),
        "n_val": len(val_df),
        "n_test": len(test_df),
        "positive_rate": round(float(df[TARGET].mean()), 4),
        "threshold": threshold,
        "f1": round(float(f1_score(y, pred)), 4),
        "precision": round(float(precision_score(y, pred)), 4),
        "recall": round(float(recall_score(y, pred)), 4),
        "roc_auc": round(float(roc_auc_score(y, proba)), 4),
        "pr_auc": round(float(average_precision_score(y, proba)), 4),
        "features": FEATURES,
    }
    test_out = test_df.copy()
    test_out["proba"] = proba
    return model, metrics, test_out


def feature_medians(df: pd.DataFrame) -> dict[str, float]:
    return {f: round(float(df[f].median()), 2) for f in FEATURES}


# --------------------------------------------------------------------------- asset mapping

# Demo story: P-101 runs overstrained (torque x wear, like a misaligned shaft loading the seal),
# C-203 has a heat-dissipation problem (bearing overheating), E-302 is borderline.
STORY_ROWS = {"P-101": "osf", "C-203": "hdf"}
STORY_MEDIUM = ["E-302"]
EXTRA_MEDIUM = 2


def assign_conditions(tags: list[str], test_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Deterministically give every asset one held-out AI4I row as its operating condition."""
    rng = np.random.default_rng(seed)
    pool = test_df.sort_values("udi").copy()
    chosen: dict[str, int] = {}

    def take(tag: str, candidates: pd.DataFrame, key: pd.Series) -> None:
        candidates = candidates[~candidates["udi"].isin(chosen.values())]
        if candidates.empty:
            candidates = pool[~pool["udi"].isin(chosen.values())]
            key = candidates["proba"]
        chosen[tag] = int(candidates.loc[key.loc[candidates.index].idxmax(), "udi"])

    for tag, flag in STORY_ROWS.items():
        if tag in tags:
            c = pool[(pool[TARGET] == 1) & (pool[flag] == 1)]
            take(tag, c, pool["proba"])

    medium = pool[(pool["proba"] >= 0.35) & (pool["proba"] < 0.55)]
    others = [t for t in tags if t not in chosen]
    extra = list(rng.choice([t for t in others if t not in STORY_MEDIUM], EXTRA_MEDIUM, False))
    for tag in [*[t for t in STORY_MEDIUM if t in tags], *extra]:
        take(tag, medium, -(medium["proba"] - 0.45).abs())

    calm = pool[(pool[TARGET] == 0) & (pool["proba"] < 0.05)]
    calm = calm[~calm["udi"].isin(chosen.values())]
    rest = [t for t in tags if t not in chosen]
    picks = rng.choice(calm.index.to_numpy(), size=len(rest), replace=False)
    for tag, idx in zip(rest, picks, strict=True):
        chosen[tag] = int(pool.loc[idx, "udi"])

    rows = pool.set_index("udi").loc[[chosen[t] for t in tags], ["type", *NUMERIC_FEATURES]]
    rows = rows.reset_index().rename(columns={"udi": "ai4i_udi"})
    rows.insert(0, "tag", tags)
    return rows


# --------------------------------------------------------------------------- runtime


def model_path() -> Path:
    return get_settings().models_dir / "risk_xgb.json"


def meta_path() -> Path:
    return get_settings().models_dir / "risk_meta.json"


def conditions_path() -> Path:
    return get_settings().data_dir / "synthetic" / "asset_conditions.csv"


@lru_cache
def _load(model_file: str, meta_file: str) -> tuple[xgb.XGBClassifier, dict, shap.TreeExplainer]:
    model = xgb.XGBClassifier()
    model.load_model(model_file)
    meta = json.loads(Path(meta_file).read_text(encoding="utf-8"))
    return model, meta, shap.TreeExplainer(model)


def explain(
    row: pd.Series, model: xgb.XGBClassifier, explainer: shap.TreeExplainer, medians: dict
) -> dict:
    """Risk score and top-3 SHAP reasons (features pushing risk up first)."""
    x = row[FEATURES].to_frame().T.astype(float)
    score = float(model.predict_proba(x)[0, 1])
    contrib = explainer(x).values[0]
    order = np.argsort(-contrib)[:3]
    reasons = []
    for i in order:
        f = FEATURES[i]
        value, typical = float(row[f]), float(medians[f])
        if f == "type_code":
            text = f"{FEATURE_LABELS[f]} {DUTY[int(value)]}"
        else:
            rel = "above" if value > typical else "below" if value < typical else "at"
            v, t, u = round(value, 1), round(typical, 1), UNITS[f]
            text = f"{FEATURE_LABELS[f]} {v:g} {u} is {rel} typical ({t:g} {u})"
        reasons.append(
            {
                "feature": f,
                "label": FEATURE_LABELS[f],
                "value": value,
                "typical": typical,
                "unit": UNITS[f],
                "impact": round(float(contrib[i]), 3),
                "text": text,
            }
        )
    return {"risk_score": round(score, 4), "risk_level": risk_level(score), "reasons": reasons}


def predict_risk(
    tag: str,
    model_file: Path | None = None,
    meta_file: Path | None = None,
    conditions_file: Path | None = None,
) -> dict:
    """Risk score + top-3 SHAP reasons for an asset. Raises KeyError for an unknown tag."""
    model, meta, explainer = _load(str(model_file or model_path()), str(meta_file or meta_path()))
    conditions = pd.read_csv(conditions_file or conditions_path()).set_index("tag")
    if tag not in conditions.index:
        raise KeyError(tag)
    row = add_features(conditions.loc[[tag]]).iloc[0]
    result = explain(row, model, explainer, meta["medians"])
    condition = {f: float(row[f]) for f in NUMERIC_FEATURES}
    condition["duty_class"] = str(row["type"])
    return {"tag": tag, **result, "operating_condition": condition, "source": "AI4I 2020 model"}
