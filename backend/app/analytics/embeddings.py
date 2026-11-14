"""Embedding with an on-disk cache keyed by (model, text hash)."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np

from app import ollama_client
from app.config import get_settings

EmbedFn = Callable[[list[str]], list[list[float]]]

# nomic-embed-text is trained with task prefixes; this one suits clustering.
PREFIX = "clustering: "


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_cache_path() -> Path:
    s = get_settings()
    safe = s.embed_model.replace(":", "_").replace("/", "_")
    return s.data_dir / "embeddings_cache" / f"{safe}.json"


def embed_texts(
    texts: list[str],
    embed_fn: EmbedFn | None = None,
    cache_path: Path | None = None,
    batch_size: int = 64,
) -> np.ndarray:
    """Return an (n, d) array of embeddings, computing only texts missing from the cache."""
    embed_fn = embed_fn or ollama_client.embed
    path = cache_path or default_cache_path()
    cache: dict[str, list[float]] = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    )

    missing = sorted({t for t in texts if _key(t) not in cache})
    for i in range(0, len(missing), batch_size):
        batch = missing[i : i + batch_size]
        vectors = embed_fn([PREFIX + t for t in batch])
        cache.update({_key(t): v for t, v in zip(batch, vectors, strict=True)})

    if missing:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache), encoding="utf-8")
    return np.array([cache[_key(t)] for t in texts], dtype=np.float32)
