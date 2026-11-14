"""F3: bad-actor detection per (asset, failure mode). Pure pandas, no ML.

Definitions (window = 180 days ending at `as_of`, default = latest work-order date):
    count_180d          events in the window
    mtbf_current_days   mean gap between consecutive events inside the window (needs >= 2)
    mtbf_previous_days  mean gap between consecutive events before the window (needs >= 2)
    mtbf_drop_pct       1 - current / previous (0 if either is undefined)
    cost_trend_pct      cost in window vs the 180 days before it
    bad_actor_score     count_180d * criticality_weight * (1 + max(0, mtbf_drop_pct))
    flagged             count_180d >= 3 or mtbf_drop_pct > 0.40
"""

import re
import sqlite3
from datetime import date, timedelta

import pandas as pd

WINDOW_DAYS = 180
CRITICALITY_WEIGHT = {"A": 3, "B": 2, "C": 1}
# Failure modes that are not failures and never count towards bad actors.
NON_FAILURE_RE = re.compile(r"routine|preventive|inspection|unclassified|\bpm\b", re.IGNORECASE)

COLUMNS = [
    "tag",
    "failure_mode",
    "criticality",
    "count_180d",
    "count_total",
    "last_event",
    "mtbf_current_days",
    "mtbf_previous_days",
    "mtbf_drop_pct",
    "cost_180d",
    "cost_prev_180d",
    "cost_trend_pct",
    "downtime_180d",
    "bad_actor_score",
    "flagged",
]


def _mean_gap(dates: pd.Series) -> float | None:
    if len(dates) < 2:
        return None
    return float(dates.sort_values().diff().dt.days.dropna().mean())


def is_failure_mode(name: str | None) -> bool:
    return bool(name) and not NON_FAILURE_RE.search(name)


def compute_bad_actors(
    work_orders: pd.DataFrame,
    assets: pd.DataFrame,
    as_of: pd.Timestamp | None = None,
    window_days: int = WINDOW_DAYS,
) -> pd.DataFrame:
    """Score every (tag, failure_mode) pair; return them sorted by score, highest first.

    work_orders needs: tag, date, failure_mode, cost_inr, downtime_hrs.
    assets needs: tag, criticality.
    """
    wo = work_orders.copy()
    wo["date"] = pd.to_datetime(wo["date"])
    wo = wo[wo["failure_mode"].map(is_failure_mode)]
    if wo.empty:
        return pd.DataFrame(columns=COLUMNS)

    as_of = pd.Timestamp(as_of) if as_of is not None else wo["date"].max()
    start = as_of - timedelta(days=window_days)
    prev_start = start - timedelta(days=window_days)
    crit = assets.set_index("tag")["criticality"].to_dict()

    rows = []
    for (tag, mode), g in wo[wo["date"] <= as_of].groupby(["tag", "failure_mode"]):
        recent = g[g["date"] > start]
        before = g[g["date"] <= start]
        prev_window = before[before["date"] > prev_start]
        mtbf_now, mtbf_before = _mean_gap(recent["date"]), _mean_gap(before["date"])
        drop = 1 - mtbf_now / mtbf_before if mtbf_now and mtbf_before else 0.0
        cost_now, cost_prev = float(recent["cost_inr"].sum()), float(prev_window["cost_inr"].sum())
        c = crit.get(tag, "C")
        rows.append(
            {
                "tag": tag,
                "failure_mode": mode,
                "criticality": c,
                "count_180d": len(recent),
                "count_total": len(g),
                "last_event": g["date"].max().date().isoformat(),
                "mtbf_current_days": None if mtbf_now is None else round(mtbf_now, 1),
                "mtbf_previous_days": None if mtbf_before is None else round(mtbf_before, 1),
                "mtbf_drop_pct": round(drop, 3),
                "cost_180d": cost_now,
                "cost_prev_180d": cost_prev,
                "cost_trend_pct": round(cost_now / cost_prev - 1, 3) if cost_prev else None,
                "downtime_180d": round(float(recent["downtime_hrs"].sum()), 1),
                "bad_actor_score": round(
                    len(recent) * CRITICALITY_WEIGHT.get(c, 1) * (1 + max(0.0, drop)), 2
                ),
                "flagged": bool(len(recent) >= 3 or drop > 0.40),
            }
        )
    out = pd.DataFrame(rows, columns=COLUMNS)
    return out.sort_values(
        ["bad_actor_score", "count_180d", "tag"], ascending=[False, False, True]
    ).reset_index(drop=True)


def load_frames(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Work orders joined with failure-mode names, plus assets, from SQLite."""
    wo = pd.read_sql_query(
        """SELECT w.id, w.tag, w.date, w.cost_inr, w.downtime_hrs, f.name AS failure_mode
           FROM work_orders w LEFT JOIN failure_modes f ON f.id = w.failure_mode_id""",
        conn,
    )
    assets = pd.read_sql_query("SELECT tag, criticality FROM assets", conn)
    return wo, assets


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe dicts (NaN -> None)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def score_bad_actors(
    conn: sqlite3.Connection,
    as_of: str | date | pd.Timestamp | None = None,
    window_days: int = WINDOW_DAYS,
) -> list[dict]:
    """Score every (asset, failure mode) pair from the DB, best-first.

    `as_of` ends the window (ISO string, date or Timestamp); None = latest work order.
    Each dict has the keys in COLUMNS (`count_180d` holds the count for `window_days`, the
    name is kept for API stability). Routine / unclassified work is excluded.
    """
    wo, assets = load_frames(conn)
    ts = None if as_of is None else pd.Timestamp(as_of)
    return _records(compute_bad_actors(wo, assets, as_of=ts, window_days=window_days))


def get_bad_actors(
    conn: sqlite3.Connection,
    top_n: int = 10,
    flagged_only: bool = False,
    window_days: int = WINDOW_DAYS,
    as_of: str | date | pd.Timestamp | None = None,
) -> list[dict]:
    """Top-n ranked bad actors as plain dicts (used by the API and the agent tool)."""
    rows = score_bad_actors(conn, as_of, window_days)
    if flagged_only:
        rows = [r for r in rows if r["flagged"]]
    return rows[:top_n]
