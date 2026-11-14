"""Read/merge models/metrics.json (shared by clustering and the risk model)."""

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


def metrics_path() -> Path:
    return get_settings().models_dir / "metrics.json"


def read_metrics(path: Path | None = None) -> dict[str, Any]:
    p = path or metrics_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write_metrics(section: str, values: dict[str, Any], path: Path | None = None) -> None:
    """Replace one top-level section of metrics.json, keeping the others."""
    p = path or metrics_path()
    data = read_metrics(p)
    data[section] = values
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
