"""Plant-level figures for the dashboard: failure-mode counts, plant MTBF trend, summary.

Pure pandas on the same frames as bad_actors.load_frames(). All windows end at `as_of`
(ANALYSIS_AS_OF if set, otherwise the latest work-order date), like the bad-actor scoring.
"""

import sqlite3
from datetime import timedelta

import pandas as pd

from app.analytics.bad_actors import compute_bad_actors, is_failure_mode, load_frames
from app.analytics.cluster import UNCLASSIFIED
from app.config import get_settings


def resolve_as_of(wo: pd.DataFrame) -> pd.Timestamp:
    pinned = get_settings().analysis_as_of
    if pinned:
        return pd.Timestamp(pinned)
    return pd.to_datetime(wo["date"]).max() if not wo.empty else pd.Timestamp.today().normalize()


def _failures(wo: pd.DataFrame) -> pd.DataFrame:
    out = wo[wo["failure_mode"].map(is_failure_mode).astype(bool)].copy()
    out["date"] = pd.to_datetime(out["date"])
    return out


def _window(df: pd.DataFrame, as_of: pd.Timestamp, days: int, offset: int = 0) -> pd.DataFrame:
    end = as_of - timedelta(days=offset)
    return df[(df["date"] > end - timedelta(days=days)) & (df["date"] <= end)]


def plant_mtbf(n_failures: int, n_assets: int, days: int) -> float | None:
    """Asset-days in the period divided by failures (None if there were none)."""
    return round(n_assets * days / n_failures, 1) if n_failures else None


def failure_mode_counts(
    wo: pd.DataFrame, modes: pd.DataFrame, as_of: pd.Timestamp, window_days: int
) -> list[dict]:
    """Events per failure mode in the window, largest first. Routine work is left out;
    the Unclassified bucket is kept and marked `is_noise`."""
    df = wo.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = _window(df, as_of, window_days)
    keep = df["failure_mode"].map(lambda m: is_failure_mode(m) or m == UNCLASSIFIED).astype(bool)
    counts = df[keep].groupby("failure_mode").size()
    ids = modes.set_index("name")["id"].to_dict()
    rows = [
        {
            "id": int(ids.get(name, 0)),
            "name": name,
            "events": int(n),
            "is_noise": name == UNCLASSIFIED,
        }
        for name, n in counts.items()
    ]
    return sorted(rows, key=lambda r: (r["is_noise"], -r["events"], r["name"]))


def mtbf_trend(
    wo: pd.DataFrame, n_assets: int, as_of: pd.Timestamp, months: int = 12, trailing_days: int = 90
) -> list[dict]:
    """Plant MTBF at each month end, over a trailing window (smooths single-month noise).
    The current, partial month is measured up to `as_of`."""
    fails = _failures(wo)
    ends = list(pd.date_range(end=as_of, periods=months, freq="ME"))
    if ends and ends[-1] < as_of:
        ends = [*ends[1:], as_of]
    points = []
    for end in ends:
        n = len(_window(fails, end, trailing_days))
        value = plant_mtbf(n, n_assets, trailing_days)
        if value is not None:
            points.append({"month": end.strftime("%Y-%m"), "mtbf_days": value})
    return points


def summary(
    wo: pd.DataFrame, assets: pd.DataFrame, as_of: pd.Timestamp, window_days: int, site: str
) -> dict:
    fails = _failures(wo)
    now = _window(fails, as_of, window_days)
    before = _window(fails, as_of, window_days, offset=window_days)
    mtbf_now = plant_mtbf(len(now), len(assets), window_days)
    mtbf_before = plant_mtbf(len(before), len(assets), window_days)
    ba = compute_bad_actors(wo, assets, as_of=as_of, window_days=window_days)
    out = {
        "site": site,
        "assets_monitored": len(assets),
        "work_orders_parsed": len(wo),
        "failure_events": len(now),
        "bad_actors_flagged": int(ba.loc[ba["flagged"], "tag"].nunique()) if len(ba) else 0,
        "plant_mtbf_days": mtbf_now or 0,
        "downtime_hrs": round(float(now["downtime_hrs"].sum()), 1),
        "window_days": window_days,
        "as_of": as_of.date().isoformat(),
    }
    if mtbf_now and mtbf_before:
        out["plant_mtbf_change_pct"] = round((mtbf_now / mtbf_before - 1) * 100, 1)
    return out


def load_all(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    wo, _ = load_frames(conn)
    assets = pd.read_sql_query("SELECT * FROM assets", conn)
    modes = pd.read_sql_query("SELECT id, name FROM failure_modes", conn)
    return wo, assets, modes
