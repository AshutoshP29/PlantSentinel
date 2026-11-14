import hashlib
import json
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.analytics import cluster
from app.analytics.abbreviations import clean_text
from app.analytics.embeddings import embed_texts
from app.analytics.metrics import read_metrics, write_metrics
from app.db import connect, init_db

# ---------------------------------------------------------------- fakes (no Ollama needed)

GROUPS = {"seal": 0, "bearing": 1, "fouling": 2, "preventive": 3}
NAMES = {
    "seal": "Mechanical Seal Leakage",
    "bearing": "Bearing Overheating",
    "fouling": "Tube Fouling",
    "preventive": "Routine Maintenance",
}


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Vectors near one axis per keyword group, plus tiny hash-based jitter."""
    out = []
    for t in texts:
        v = np.zeros(8)
        for kw, axis in GROUPS.items():
            if kw in t:
                v[axis] = 1.0
        seed = int(hashlib.md5(t.encode()).hexdigest()[:8], 16)
        v += np.random.default_rng(seed).normal(0, 0.02, 8)
        if not any(kw in t for kw in GROUPS):
            v[4 + seed % 4] = 1.0  # outliers point elsewhere
        out.append(v.tolist())
    return out


def fake_chat(prompt: str) -> dict:
    if "canonical" in prompt:
        names = re.findall(r"^- (.+)$", prompt, re.MULTILINE)
        return {"Mapping": {n: n for n in names}}
    for kw, name in NAMES.items():
        if kw in prompt:
            return {"Name": name, "Description": f"{name} events"}
    return {"name": "", "description": ""}


def make_df() -> pd.DataFrame:
    rows = []
    templates = {
        "seal": ["mech seal lkg", "seal leaking", "mechanical seal leakage", "seal leak hua"],
        "bearing": ["brg temp high", "bearing overheating", "high bearing temp", "brg hot"],
        "fouling": ["fouling high dp", "tubes fouling", "fouling poor heat transfer", "fouling"],
        "preventive": ["PM done", "preventive maintenance ok", "PM ok", "preventive check"],
    }
    i = 0
    for texts in templates.values():
        for rep in range(3):
            for t in texts:
                i += 1
                rows.append({"id": f"WO-{i:04d}", "description": f"{t} {'.' * rep}"})
    rows.append({"id": "WO-9999", "description": "operator reported strange smell"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- abbreviations


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Mech seal lkg", "mechanical seal leakage"),
        ("P-101 BRG TEMP HIGH!!", "bearing temperature high"),
        ("p101 seal leak hua, replaced", "seal leak replaced"),
        ("SEAL LEAK HUA PHIR SE P-101", "seal leak again"),
        ("bearing sound aa raha hai", "bearing sound"),
        ("o/l trip", "overload trip"),
        ("high vib at DE", "high vibration at drive end"),
        ("", ""),
        (None, ""),
    ],
)
def test_clean_text(raw: str | None, clean: str) -> None:
    assert clean_text(raw) == clean


# ---------------------------------------------------------------- embeddings cache


def test_embedding_cache(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def counting_embed(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return fake_embed(texts)

    cache = tmp_path / "cache.json"
    x1 = embed_texts(["a seal", "b bearing", "a seal"], counting_embed, cache)
    assert x1.shape == (3, 8)
    assert len(calls) == 1 and len(calls[0]) == 2  # duplicates embedded once
    assert all(t.startswith("clustering: ") for t in calls[0])
    x2 = embed_texts(["b bearing", "a seal"], counting_embed, cache)
    assert len(calls) == 1  # fully served from cache
    np.testing.assert_allclose(x2[1], x1[0])


# ---------------------------------------------------------------- clustering


def test_cluster_work_orders_groups_and_names(tmp_path: Path) -> None:
    df = make_df()
    res = cluster.cluster_work_orders(
        df, fake_embed, fake_chat, min_cluster_size=5, cache_path=tmp_path / "c.json"
    )
    assert set(res.modes) - {cluster.UNCLASSIFIED} == set(NAMES.values())
    by_mode = pd.Series(res.assignments).groupby(lambda k: res.assignments[k]).size()
    assert by_mode["Mechanical Seal Leakage"] == 12
    assert res.assignments["WO-9999"] == cluster.UNCLASSIFIED
    assert res.metrics["n_clusters"] == 4
    assert res.metrics["silhouette"] > 0.5


def test_name_cluster_handles_bad_output() -> None:
    assert cluster.name_cluster(["x"], lambda p: {"NAME": "seal leak."}, "F1") == ("Seal Leak", "")

    def boom(_: str) -> dict:
        raise ValueError("bad json")

    assert cluster.name_cluster(["x"], boom, "Failure Mode 3") == ("Failure Mode 3", "")


def test_consolidate_names() -> None:
    names = ["Impeller Wear", "Impeller Worn", "Routine Maintenance", "Seal Leak"]
    mapping = {
        "Impeller Worn": "Impeller Wear",
        "Seal Leak": "Routine Maintenance",  # must be refused
    }
    out = cluster.consolidate_names(names, lambda p: {"mapping": mapping})
    assert out == {
        "Impeller Wear": "Impeller Wear",
        "Impeller Worn": "Impeller Wear",
        "Routine Maintenance": "Routine Maintenance",
        "Seal Leak": "Seal Leak",
    }
    assert cluster.consolidate_names(names, lambda p: {"mapping": "nope"}) == {n: n for n in names}


def test_synonym_clusters_merge(tmp_path: Path) -> None:
    def chat(prompt: str) -> dict:
        if "canonical" in prompt:
            return {"mapping": {"Bearing Overheating": "Mechanical Seal Leakage"}}
        return fake_chat(prompt)

    res = cluster.cluster_work_orders(
        make_df(), fake_embed, chat, min_cluster_size=5, cache_path=tmp_path / "c.json"
    )
    assert "Bearing Overheating" not in res.modes
    assert list(res.assignments.values()).count("Mechanical Seal Leakage") == 24


# ---------------------------------------------------------------- database + fallback


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = connect(":memory:")
    init_db(c)
    c.execute("INSERT INTO assets(tag, criticality) VALUES ('P-101', 'A')")
    for _, r in make_df().iterrows():
        c.execute(
            "INSERT INTO work_orders(id, tag, date, description) VALUES (?, 'P-101', ?, ?)",
            (r["id"], "2026-01-01", r["description"]),
        )
    c.commit()
    return c


def test_recluster_writes_db(conn: sqlite3.Connection, tmp_path: Path) -> None:
    res = cluster.recluster(
        conn, fake_embed, fake_chat, min_cluster_size=5, cache_path=tmp_path / "c.json"
    )
    assert res.metrics["source"] == "live"
    rows = conn.execute(
        """SELECT w.description_clean, f.name FROM work_orders w
           JOIN failure_modes f ON f.id = w.failure_mode_id WHERE w.id = 'WO-0001'"""
    ).fetchone()
    assert rows["name"] == "Mechanical Seal Leakage"
    assert rows["description_clean"] == "mechanical seal leakage"
    assert (
        conn.execute("SELECT COUNT(*) FROM work_orders WHERE failure_mode_id IS NULL").fetchone()[0]
        == 0
    )


def test_recluster_uses_fallback_when_ollama_down(conn: sqlite3.Connection, tmp_path: Path) -> None:
    fb = tmp_path / "fallback.json"
    cluster.save_fallback(
        cluster.ClusterResult({"WO-0001": "Seal Leak"}, {"Seal Leak": "d", "Unclassified": ""}),
        fb,
    )

    def down(_: list[str]) -> list[list[float]]:
        raise ConnectionError("ollama not running")

    res = cluster.recluster(conn, down, fake_chat, fallback=fb, cache_path=tmp_path / "c.json")
    assert res.metrics["source"] == "fallback"
    names = dict(
        conn.execute(
            """SELECT w.id, f.name FROM work_orders w
               LEFT JOIN failure_modes f ON f.id = w.failure_mode_id"""
        ).fetchall()
    )
    assert names["WO-0001"] == "Seal Leak"
    assert names["WO-0002"] == "Unclassified"


def test_committed_fallback_is_valid() -> None:
    path = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "clusters_fallback.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "Mechanical Seal Leakage" in data["modes"]
    assert len(data["assignments"]) > 400


def test_metrics_merge(tmp_path: Path) -> None:
    p = tmp_path / "metrics.json"
    write_metrics("risk_model", {"f1": 0.8}, p)
    write_metrics("clustering", {"silhouette": 0.6}, p)
    assert read_metrics(p) == {"risk_model": {"f1": 0.8}, "clustering": {"silhouette": 0.6}}
