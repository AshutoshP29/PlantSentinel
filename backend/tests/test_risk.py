import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.analytics import risk
from app.analytics.ai4i import FEATURES, LEAKY, NUMERIC_FEATURES, add_features, load_ai4i

REPO = Path(__file__).resolve().parents[2]
TAGS = pd.read_csv(REPO / "data" / "synthetic" / "assets.csv")["tag"].tolist()


@pytest.fixture(scope="module")
def trained(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Train once on the real AI4I file (CPU, a few seconds) and save artefacts to tmp."""
    df = load_ai4i(REPO / "data" / "raw" / "ai4i2020.csv")
    model, metrics, test_df = risk.train(df, seed=42)
    d = tmp_path_factory.mktemp("risk")
    model.save_model(d / "m.json")
    (d / "meta.json").write_text(json.dumps({"medians": risk.feature_medians(df)}))
    cond = risk.assign_conditions(TAGS, test_df, seed=42)
    cond.to_csv(d / "cond.csv", index=False)
    files = {
        "model_file": d / "m.json",
        "meta_file": d / "meta.json",
        "conditions_file": d / "cond.csv",
    }
    return {"metrics": metrics, "test_df": test_df, "cond": cond, "files": files}


def test_add_features() -> None:
    row = pd.DataFrame(
        [
            {
                "air_temp_k": 300.0,
                "process_temp_k": 310.0,
                "rpm": 1500.0,
                "torque_nm": 40.0,
                "tool_wear_min": 100.0,
                "type": "H",
            }
        ]
    )
    out = add_features(row).iloc[0]
    assert out["temp_diff_k"] == pytest.approx(10.0)
    assert out["power_kw"] == pytest.approx(40 * 1500 * 2 * np.pi / 60 / 1000)
    assert out["strain_nm_min"] == pytest.approx(4000.0)
    assert out["type_code"] == 2


def test_no_leaky_features() -> None:
    assert not set(LEAKY) & set(FEATURES)
    assert "failure" not in FEATURES


def test_best_threshold_and_levels() -> None:
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.4, 0.6, 0.9])
    assert 0.4 <= risk.best_f1_threshold(y, p) < 0.6
    assert [risk.risk_level(s) for s in (0.1, 0.3, 0.59, 0.6)] == [
        "low",
        "medium",
        "medium",
        "high",
    ]


def test_metrics(trained: dict) -> None:
    m = trained["metrics"]
    assert m["n_train"] + m["n_val"] + m["n_test"] == 10_000
    assert m["roc_auc"] > 0.95
    assert m["f1"] > 0.7
    assert 0 < m["threshold"] < 1
    assert m["features"] == FEATURES


def test_assign_conditions(trained: dict) -> None:
    cond, test_df = trained["cond"], trained["test_df"]
    assert list(cond["tag"]) == TAGS
    assert cond["ai4i_udi"].is_unique
    assert set(cond["ai4i_udi"]) <= set(test_df["udi"])  # held-out rows only
    by_udi = test_df.set_index("udi")
    p101 = by_udi.loc[cond.set_index("tag").loc["P-101", "ai4i_udi"]]
    c203 = by_udi.loc[cond.set_index("tag").loc["C-203", "ai4i_udi"]]
    assert p101["failure"] == 1 and p101["osf"] == 1
    assert c203["failure"] == 1 and c203["hdf"] == 1
    assert list(cond.columns) == ["tag", "ai4i_udi", "type", *NUMERIC_FEATURES]

    again = risk.assign_conditions(TAGS, test_df, seed=42)
    pd.testing.assert_frame_equal(cond, again)


def test_predict_risk(trained: dict) -> None:
    files = trained["files"]
    p101 = risk.predict_risk("P-101", **files)
    assert p101["risk_level"] == "high"
    assert len(p101["reasons"]) == 3
    assert all(r["feature"] in FEATURES and r["text"] for r in p101["reasons"])
    assert p101["reasons"][0]["impact"] >= p101["reasons"][1]["impact"]
    assert set(p101["operating_condition"]) == {*NUMERIC_FEATURES, "duty_class"}
    json.dumps(p101)  # API / agent friendly

    scores = {t: risk.predict_risk(t, **files)["risk_score"] for t in TAGS}
    top2 = sorted(scores, key=scores.get, reverse=True)[:2]
    assert set(top2) == {"P-101", "C-203"}
    assert sum(risk.risk_level(s) == "high" for s in scores.values()) == 2


def test_unknown_tag(trained: dict) -> None:
    with pytest.raises(KeyError):
        risk.predict_risk("X-999", **trained["files"])


def test_committed_conditions_file() -> None:
    cond = pd.read_csv(REPO / "data" / "synthetic" / "asset_conditions.csv")
    assert list(cond["tag"]) == TAGS
    assert cond[NUMERIC_FEATURES].notna().all().all()
