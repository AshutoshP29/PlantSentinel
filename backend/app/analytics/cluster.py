"""F2: messy work-order text -> embeddings -> HDBSCAN -> LLM-named failure modes."""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN, AgglomerativeClustering
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

from app import ollama_client
from app.analytics.abbreviations import clean_text
from app.analytics.embeddings import EmbedFn, embed_texts
from app.config import get_settings

ChatFn = Callable[[str], dict]
UNCLASSIFIED = "Unclassified"
NAMING_PROMPT = """You are a reliability engineer. These maintenance work-order notes were grouped
together because they describe the same kind of equipment failure:

{samples}

Name the common failure mode, naming the component that failed (e.g. "Mechanical Seal Leakage",
"Bearing Overheating"). If the notes describe routine or preventive work with no failure, use
the name "Routine Maintenance".
Reply with JSON only, using lowercase keys:
{{"name": "<2-4 word failure mode, Title Case>", "description": "<one sentence>"}}"""


@dataclass
class ClusterResult:
    assignments: dict[str, str]  # work order id -> failure mode name
    modes: dict[str, str]  # failure mode name -> description
    metrics: dict = field(default_factory=dict)


def _centroids(x: np.ndarray, labels: np.ndarray, ks: list[int]) -> np.ndarray:
    return normalize(np.array([x[labels == k].mean(axis=0) for k in ks]))


def cluster_embeddings(
    x: np.ndarray,
    min_cluster_size: int = 8,
    merge_distance: float = 0.15,
    attach_similarity: float = 0.8,
) -> np.ndarray:
    """Cluster embeddings into failure modes.

    1. HDBSCAN on L2-normalised vectors (euclidean on unit vectors ~ cosine). On short
       templated text it finds wording-level clusters ("seal leaking" vs "mech seal lkg").
    2. Merge clusters whose centroids are within `merge_distance` cosine distance.
    3. Attach noise points to the nearest cluster if cosine similarity >= `attach_similarity`;
       the rest stay -1 ("Unclassified").
    """
    xn = normalize(x)
    labels = HDBSCAN(min_cluster_size=min_cluster_size, copy=True).fit_predict(xn)
    ks = sorted(set(labels.tolist()) - {-1})
    if not ks:
        return labels

    if merge_distance > 0 and len(ks) > 1:
        groups = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=merge_distance,
        ).fit_predict(_centroids(xn, labels, ks))
    else:
        groups = np.arange(len(ks))
    remap = dict(zip(ks, groups.tolist(), strict=True))
    merged = np.array([remap.get(int(lab), -1) for lab in labels])

    if attach_similarity < 1:
        gs = sorted(set(merged.tolist()) - {-1})
        sims = xn @ _centroids(xn, merged, gs).T
        for i in np.flatnonzero(merged == -1):
            if sims[i].max() >= attach_similarity:
                merged[i] = gs[int(sims[i].argmax())]
    return merged


def silhouette(x: np.ndarray, labels: np.ndarray) -> float | None:
    mask = labels != -1
    if len(set(labels[mask])) < 2:
        return None
    return float(silhouette_score(normalize(x[mask]), labels[mask], metric="cosine"))


def name_cluster(samples: list[str], chat_fn: ChatFn, fallback: str) -> tuple[str, str]:
    """Ask the LLM to name one cluster; fall back to a generic name on bad output."""
    prompt = NAMING_PROMPT.format(samples="\n".join(f"- {s}" for s in samples[:5]))
    try:
        out = {str(k).lower(): v for k, v in chat_fn(prompt).items()}  # models vary key case
        name = str(out.get("name", "")).strip().strip(".").title()
        desc = str(out.get("description", "")).strip()
    except Exception:
        return fallback, ""
    return (name or fallback), desc


CONSOLIDATE_PROMPT = """These failure-mode names were produced for clusters of maintenance notes:

{names}

Some may be synonyms for the same failure on the same component (e.g. "Impeller Wear" and
"Impeller Worn"). Map every name to a canonical name. Only merge names that describe the SAME
failure of the SAME component; keep different components (seal vs gasket vs tube, pump bearing
vs compressor bearing) separate. Prefer the clearest existing name as the canonical one.
Reply with JSON only: {{"mapping": {{"<name>": "<canonical name>", ...}}}}"""


def consolidate_names(names: list[str], chat_fn: ChatFn) -> dict[str, str]:
    """Map each cluster name to a canonical name via one LLM call; identity on any failure."""
    identity = {n: n for n in names}
    if len(names) < 2:
        return identity
    try:
        out = {
            str(k).lower(): v
            for k, v in chat_fn(
                CONSOLIDATE_PROMPT.format(names="\n".join(f"- {n}" for n in names))
            ).items()
        }
        mapping = out.get("mapping", {})
        if not isinstance(mapping, dict):
            return identity
    except Exception:
        return identity
    result = {}
    for n in names:
        target = str(mapping.get(n, n)).strip().strip(".").title() or n
        # Never fold real failures into the non-failure bucket or vice versa.
        if (n == "Routine Maintenance") != (target == "Routine Maintenance"):
            target = n
        result[n] = target
    return result


def _representative_samples(texts: list[str], x: np.ndarray, k: int = 5) -> list[str]:
    """Up to k distinct texts closest to the cluster centroid."""
    xn = normalize(x)
    centroid = xn.mean(axis=0)
    order = np.argsort(-(xn @ centroid))
    seen: list[str] = []
    for i in order:
        if texts[i] not in seen:
            seen.append(texts[i])
        if len(seen) == k:
            break
    return seen


def cluster_work_orders(
    df: pd.DataFrame,
    embed_fn: EmbedFn | None = None,
    chat_fn: ChatFn | None = None,
    min_cluster_size: int = 8,
    cache_path: Path | None = None,
    merge_distance: float = 0.12,
) -> ClusterResult:
    """Cluster work orders (columns: id, description) into named failure modes."""
    chat_fn = chat_fn or ollama_client.chat_json
    texts = [clean_text(d) for d in df["description"]]
    x = embed_texts(texts, embed_fn=embed_fn, cache_path=cache_path)
    labels = cluster_embeddings(x, min_cluster_size, merge_distance)

    label_names: dict[int, str] = {}
    descriptions: dict[str, str] = {}
    for label in sorted(set(labels) - {-1}):
        idx = np.flatnonzero(labels == label)
        samples = _representative_samples([texts[i] for i in idx], x[idx])
        name, desc = name_cluster(samples, chat_fn, fallback=f"Failure Mode {label + 1}")
        label_names[label] = name
        descriptions.setdefault(name, desc)

    # Clusters given the same (or a synonymous) name become one failure mode.
    canonical = consolidate_names(list(descriptions), chat_fn)
    label_names = {k: canonical[v] for k, v in label_names.items()}
    modes: dict[str, str] = {}
    for old, new in canonical.items():
        if not modes.get(new):
            modes[new] = descriptions.get(new) or descriptions[old]
    if (labels == -1).any():
        modes[UNCLASSIFIED] = "Work orders that did not fit any recurring failure pattern."

    assignments = {
        wo_id: label_names.get(int(label), UNCLASSIFIED)
        for wo_id, label in zip(df["id"], labels, strict=True)
    }
    sil = silhouette(x, labels)
    metrics = {
        "n_work_orders": len(df),
        "n_clusters": len(label_names),
        "n_failure_modes": len(modes) - (UNCLASSIFIED in modes),
        "noise_fraction": round(float((labels == -1).mean()), 4),
        "silhouette": None if sil is None else round(sil, 4),
        "min_cluster_size": min_cluster_size,
        "merge_distance": merge_distance,
    }
    return ClusterResult(assignments, modes, metrics)


# --------------------------------------------------------------------------- fallback


def fallback_path() -> Path:
    return get_settings().data_dir / "synthetic" / "clusters_fallback.json"


def save_fallback(result: ClusterResult, path: Path | None = None) -> None:
    p = path or fallback_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"modes": result.modes, "assignments": result.assignments}
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_fallback(path: Path | None = None) -> ClusterResult:
    data = json.loads((path or fallback_path()).read_text(encoding="utf-8"))
    return ClusterResult(data["assignments"], data["modes"], {"source": "fallback"})


# --------------------------------------------------------------------------- database


def apply_to_db(conn: sqlite3.Connection, result: ClusterResult) -> None:
    """Replace failure_modes and set failure_mode_id + description_clean on work orders."""
    rows = conn.execute("SELECT id, description FROM work_orders").fetchall()
    with conn:
        conn.execute("UPDATE work_orders SET failure_mode_id = NULL")
        conn.execute("DELETE FROM failure_modes")
        ids = {}
        for name, desc in result.modes.items():
            cur = conn.execute(
                "INSERT INTO failure_modes(name, description) VALUES (?, ?)", (name, desc)
            )
            ids[name] = cur.lastrowid
        for r in rows:
            mode = result.assignments.get(r["id"], UNCLASSIFIED)
            conn.execute(
                "UPDATE work_orders SET description_clean = ?, failure_mode_id = ? WHERE id = ?",
                (clean_text(r["description"]), ids.get(mode), r["id"]),
            )


def recluster(
    conn: sqlite3.Connection,
    embed_fn: EmbedFn | None = None,
    chat_fn: ChatFn | None = None,
    min_cluster_size: int = 8,
    fallback: Path | None = None,
    cache_path: Path | None = None,
) -> ClusterResult:
    """Cluster all work orders in the DB. Uses the precomputed fallback if Ollama fails
    or clustering collapses (fewer than 3 clusters)."""
    df = pd.read_sql_query("SELECT id, description, action_taken FROM work_orders", conn)
    try:
        result = cluster_work_orders(df, embed_fn, chat_fn, min_cluster_size, cache_path)
        if result.metrics["n_clusters"] < 3:
            raise RuntimeError("clustering collapsed")
        result.metrics["source"] = "live"
    except Exception:
        result = load_fallback(fallback)
    apply_to_db(conn, result)
    return result
