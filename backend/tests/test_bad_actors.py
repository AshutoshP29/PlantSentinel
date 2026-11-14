import sqlite3
from datetime import date, timedelta

import pandas as pd
import pytest

from app.analytics.bad_actors import compute_bad_actors, get_bad_actors, is_failure_mode
from app.db import connect, init_db

END = date(2026, 11, 14)


def wo_rows(tag: str, mode: str, days_ago: list[int], cost: float = 1000.0) -> list[dict]:
    return [
        {
            "tag": tag,
            "date": (END - timedelta(days=d)).isoformat(),
            "failure_mode": mode,
            "cost_inr": cost,
            "downtime_hrs": 2.0,
        }
        for d in days_ago
    ]


ASSETS = pd.DataFrame(
    {"tag": ["P-101", "C-203", "M-401", "E-301"], "criticality": ["A", "A", "C", "B"]}
)


@pytest.fixture
def frame() -> pd.DataFrame:
    rows = (
        # P-101: 4 in window, gaps 50/55/48 -> mtbf 51; before: gaps 150 -> mtbf 150
        wo_rows("P-101", "Seal Leakage", [0, 48, 103, 153, 303, 453, 603])
        # C-203: 3 in window, no history -> drop 0
        + wo_rows("C-203", "Bearing Overheating", [10, 70, 130])
        # M-401: 1 recent event only
        + wo_rows("M-401", "Motor Trip", [5, 400])
        # Routine work must never count
        + wo_rows("E-301", "Routine Maintenance", [1, 2, 3, 4])
        + wo_rows("E-301", "Unclassified", [1, 2, 3])
    )
    return pd.DataFrame(rows)


def test_scores_and_order(frame: pd.DataFrame) -> None:
    out = compute_bad_actors(frame, ASSETS)
    assert list(out["tag"]) == ["P-101", "C-203", "M-401"]
    p101 = out.iloc[0]
    assert p101["count_180d"] == 4
    assert p101["mtbf_current_days"] == pytest.approx(51.0)
    assert p101["mtbf_previous_days"] == pytest.approx(150.0)
    assert p101["mtbf_drop_pct"] == pytest.approx(0.66)
    assert p101["bad_actor_score"] == pytest.approx(4 * 3 * 1.66)
    assert p101["flagged"]

    c203 = out.iloc[1]
    assert c203["mtbf_drop_pct"] == 0
    assert c203["bad_actor_score"] == 9
    assert c203["flagged"]  # count >= 3

    m401 = out.iloc[2]
    assert m401["count_180d"] == 1
    assert m401["bad_actor_score"] == 1
    assert not m401["flagged"]


def test_mtbf_drop_alone_flags() -> None:
    rows = wo_rows("M-401", "Motor Trip", [0, 20, 400, 600])  # 2 recent, gap 20 vs 200
    out = compute_bad_actors(pd.DataFrame(rows), ASSETS)
    assert out.iloc[0]["count_180d"] == 2
    assert out.iloc[0]["flagged"]


def test_window_uses_as_of(frame: pd.DataFrame) -> None:
    out = compute_bad_actors(frame, ASSETS, as_of=pd.Timestamp(END - timedelta(days=200)))
    p101 = out[out["tag"] == "P-101"].iloc[0]
    assert p101["count_180d"] == 1  # only the event 303 days before END


def test_cost_trend() -> None:
    rows = wo_rows("P-101", "Seal", [10], cost=3000) + wo_rows("P-101", "Seal", [200], cost=1000)
    out = compute_bad_actors(pd.DataFrame(rows), ASSETS)
    assert out.iloc[0]["cost_trend_pct"] == pytest.approx(2.0)


def test_empty_and_non_failure_only() -> None:
    assert compute_bad_actors(
        pd.DataFrame(wo_rows("E-301", "Routine Maintenance", [1])), ASSETS
    ).empty


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Mechanical Seal Leakage", True),
        ("Routine Maintenance", False),
        ("Preventive Check", False),
        ("Unclassified", False),
        ("PM", False),
        ("Pump Bearing Failure", True),
        (None, False),
    ],
)
def test_is_failure_mode(name: str | None, expected: bool) -> None:
    assert is_failure_mode(name) is expected


def test_get_bad_actors_from_db(frame: pd.DataFrame) -> None:
    conn: sqlite3.Connection = connect(":memory:")
    init_db(conn)
    conn.executemany(
        "INSERT INTO assets(tag, criticality) VALUES (?, ?)", ASSETS.itertuples(index=False)
    )
    modes = {m: i for i, m in enumerate(frame["failure_mode"].unique(), start=1)}
    conn.executemany(
        "INSERT INTO failure_modes(id, name) VALUES (?, ?)", [(i, m) for m, i in modes.items()]
    )
    for i, r in enumerate(frame.itertuples(index=False)):
        conn.execute(
            """INSERT INTO work_orders(id, tag, date, cost_inr, downtime_hrs, failure_mode_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f"WO-{i}", r.tag, r.date, r.cost_inr, r.downtime_hrs, modes[r.failure_mode]),
        )
    top = get_bad_actors(conn, top_n=2)
    assert [r["tag"] for r in top] == ["P-101", "C-203"]
    assert top[1]["mtbf_current_days"] == 60.0
    assert top[1]["mtbf_previous_days"] is None  # JSON-safe, not NaN
    assert [r["tag"] for r in get_bad_actors(conn, flagged_only=True)] == ["P-101", "C-203"]
