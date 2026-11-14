"""Adapter between the agent tools and the analytics package (Person A).

Contract expected from app.analytics (to be confirmed with Person A):

* Clustering writes `work_orders.failure_mode_id` and fills `failure_modes`. When present,
  failure patterns are grouped by that mode.
* `app.analytics.bad_actors.score_bad_actors(conn, as_of) -> list[dict]`, each dict with at
  least `tag` and `score`, sorted best-first. Extra fields (drivers, SHAP values) are passed
  through to the agent unchanged.

Until those exist, the functions below return transparent, labelled *preliminary* figures
computed directly from the work orders (counts, intervals, downtime). They never invent a
score or a cluster.
"""

from __future__ import annotations

import importlib
import logging
import re
import sqlite3
from collections import defaultdict
from datetime import date
from itertools import pairwise
from statistics import mean

from app.agent import data

log = logging.getLogger(__name__)

PRELIMINARY = "preliminary (computed from raw work orders; analytics model not available yet)"


def _intervals(dates: list[date]) -> list[int]:
    d = sorted(dates)
    return [(b - a).days for a, b in pairwise(d)]


def _event_stats(rows: list[dict], window_start: date) -> dict:
    dates = [date.fromisoformat(r["date"]) for r in rows]
    gaps = _intervals(dates)
    recent = [d for d in dates if d >= window_start]
    recent_gaps = _intervals(recent)
    earlier_gaps = _intervals([d for d in dates if d < window_start])
    return {
        "events": len(rows),
        "events_in_window": len(recent),
        "first": min(dates).isoformat() if dates else None,
        "last": max(dates).isoformat() if dates else None,
        "mean_days_between": round(mean(gaps), 1) if gaps else None,
        "mean_days_between_before_window": round(mean(earlier_gaps), 1) if earlier_gaps else None,
        "mean_days_between_in_window": round(mean(recent_gaps), 1) if recent_gaps else None,
        "total_downtime_hrs": round(sum(r["downtime_hrs"] or 0 for r in rows), 1),
        "total_cost_inr": round(sum(r["cost_inr"] or 0 for r in rows)),
        "work_order_ids": [r["id"] for r in sorted(rows, key=lambda r: r["date"])],
    }


def failure_patterns(
    conn: sqlite3.Connection,
    tag: str,
    keywords: list[str] | None = None,
    window_days: int | None = None,
) -> dict:
    """Failure statistics for one asset.

    `keywords` filters work-order text (case-insensitive, any match), e.g. ["seal"]. This is a
    query, not a classifier: the matched work orders are listed so the result is checkable.
    """
    start = data.window_start(conn, window_days)
    rows = data.work_orders(conn, tag)
    out: dict = {"tag": tag, "as_of": data.as_of_date(conn).isoformat(), "window_start": str(start)}
    if not rows:
        return {**out, "events": 0, "note": "no work orders recorded for this asset"}

    if any(r["failure_mode"] for r in rows):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[r["failure_mode"] or "Unclassified"].append(r)
        out["method"] = "failure modes from clustering (app.analytics)"
        out["by_failure_mode"] = {
            mode: _event_stats(g, start)
            for mode, g in sorted(groups.items(), key=lambda kv: -len(kv[1]))
        }
    else:
        out["method"] = PRELIMINARY

    if keywords:
        pattern = re.compile("|".join(re.escape(k) for k in keywords if k.strip()), re.I)
        matched = [r for r in rows if pattern.search(f"{r['description']} {r['action_taken']}")]
        out["keyword_filter"] = keywords
        out["matching"] = _event_stats(matched, start) if matched else {"events": 0}
        out["matching_examples"] = [
            {k: r[k] for k in ("id", "date", "description", "action_taken")} for r in matched[:12]
        ]
    out["all_work_orders"] = _event_stats(rows, start)
    return out


def _model_bad_actors(conn: sqlite3.Connection) -> list[dict] | None:
    try:
        mod = importlib.import_module("app.analytics.bad_actors")
    except ImportError:
        return None
    fn = getattr(mod, "score_bad_actors", None)
    if fn is None:
        return None
    try:
        ranked = list(fn(conn, data.as_of_date(conn)))
    except Exception:
        log.exception("app.analytics.bad_actors.score_bad_actors failed; using fallback")
        return None
    # Empty = no work order has a failure mode yet (clustering not run): use the fallback.
    return ranked or None


def bad_actors(conn: sqlite3.Connection, top_n: int = 5, tag: str | None = None) -> dict:
    """Ranking of problem assets, and the position of `tag` if given."""
    ranked = _model_bad_actors(conn)
    if ranked is not None:
        method = "bad-actor model (app.analytics.bad_actors)"
    else:
        start = data.window_start(conn)
        ranked = data.asset_totals(conn, start)
        method = f"{PRELIMINARY}; ranked by downtime since {start}, not a bad-actor score"
    out: dict = {"method": method, "top": ranked[:top_n]}
    if tag:
        pos = next((i for i, r in enumerate(ranked) if r.get("tag") == tag), None)
        out["asset"] = (
            {"tag": tag, "rank": pos + 1, "of": len(ranked), **ranked[pos]}
            if pos is not None
            else {"tag": tag, "rank": None, "note": "asset not in ranking"}
        )
    return out
