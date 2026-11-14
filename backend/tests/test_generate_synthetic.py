import itertools
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

import generate_synthetic as gen

END = gen.DEFAULT_END
WINDOW_START = (END - timedelta(days=gen.WINDOW_DAYS)).isoformat()


@pytest.fixture(scope="module")
def data() -> tuple[pd.DataFrame, pd.DataFrame]:
    return gen.generate(seed=42)


def _mean_gap(dates: list[str]) -> float:
    ds = sorted(date.fromisoformat(d) for d in dates)
    gaps = [(b - a).days for a, b in itertools.pairwise(ds)]
    return sum(gaps) / len(gaps)


def test_deterministic() -> None:
    a1, w1 = gen.generate(seed=42)
    a2, w2 = gen.generate(seed=42)
    pd.testing.assert_frame_equal(a1, a2)
    pd.testing.assert_frame_equal(w1, w2)
    _, w3 = gen.generate(seed=7)
    assert not w1["description"].equals(w3["description"])


def test_assets(data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    assets, _ = data
    assert len(assets) == 30
    assert assets["tag"].is_unique
    assert set(assets["criticality"]) <= {"A", "B", "C"}
    assert {"P-101", "P-115", "C-201", "C-206", "E-301", "E-305", "M-401", "M-404"} <= set(
        assets["tag"]
    )
    crit = assets.set_index("tag")["criticality"]
    assert crit["P-101"] == "A"
    assert crit["C-203"] == "A"


def test_work_orders_shape(data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    assets, wo = data
    assert 430 <= len(wo) <= 570
    assert wo["id"].is_unique
    assert set(wo["tag"]) <= set(assets["tag"])
    assert wo["date"].min() >= (END - timedelta(days=3 * 365)).isoformat()
    assert wo["date"].max() <= END.isoformat()
    assert list(wo["date"]) == sorted(wo["date"])
    assert (wo["downtime_hrs"] > 0).all()
    assert (wo["cost_inr"] > 0).all()


def test_text_is_messy(data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    text = " ".join(data[1]["description"]).lower()
    for token in ("lkg", "brg", "hua", "mech"):
        assert token in text
    assert data[1]["duplicate"].sum() > 0


def test_p101_story(data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    wo = data[1]
    seal = wo[(wo["tag"] == "P-101") & (wo["true_mode"] == "Mechanical seal leakage")]
    recent = seal[seal["date"] >= WINDOW_START]
    previous = seal[seal["date"] < WINDOW_START]
    assert len(recent) == 4
    mtbf_now, mtbf_before = _mean_gap(list(recent["date"])), _mean_gap(list(previous["date"]))
    assert 1 - mtbf_now / mtbf_before > 0.6  # "MTBF down ~60%+"
    # actions never mention alignment: root cause must be discovered, not stated
    assert not seal["action_taken"].str.contains("align", case=False).any()


def test_secondary_bad_actors(data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    wo = data[1]
    recent = wo[wo["date"] >= WINDOW_START]
    counts = recent.groupby(["tag", "true_mode"]).size()
    assert counts[("C-203", "Compressor bearing overheating")] == 3
    assert counts[("E-302", "Tube fouling")] == 3


@pytest.mark.parametrize("seed", [42, 1, 7, 123])
def test_no_accidental_bad_actors(seed: int) -> None:
    _, wo = gen.generate(seed=seed)
    recent = wo[(wo["date"] >= WINDOW_START) & (wo["true_mode"] != "Routine maintenance")]
    counts = recent.groupby(["tag", "true_mode"]).size()
    noisy = counts[counts >= 2].index.tolist()
    assert sorted(noisy) == sorted(gen.PLANTED_PAIRS)


def test_cli_writes_files(tmp_path: Path) -> None:
    assert gen.main(["--out", str(tmp_path)]) == 0
    wo = pd.read_csv(tmp_path / "work_orders.csv")
    assert list(wo.columns) == gen.WO_COLUMNS
    truth = pd.read_csv(tmp_path / "work_orders_truth.csv")
    assert list(truth["id"]) == list(wo["id"])
    assert len(pd.read_csv(tmp_path / "assets.csv")) == 30
