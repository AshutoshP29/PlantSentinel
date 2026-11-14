"""Registry of generated documents (work orders, reports) kept next to the files.

Each document is `<outputs_dir>/<id>.<ext>` plus `<id>.json` holding the `DocumentItem` the
frontend expects. If a documents table is added to the schema later, only this module changes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app.config import get_settings

ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def outputs_dir() -> Path:
    d = get_settings().outputs_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def register(
    path: Path,
    kind: str,
    tag: str | None,
    created_by: str = "PlantSentinel agent",
    work_order: dict | None = None,
) -> dict:
    """Write the sidecar metadata for a generated file and return the DocumentItem."""
    item = {
        "id": path.stem,
        "file_name": path.name,
        "kind": kind,  # "work_order" | "bad_actor_report"
        "tag": tag,
        "created_by": created_by,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if work_order is not None:
        item["work_order"] = work_order
    path.with_suffix(".json").write_text(json.dumps(item, indent=2), encoding="utf-8")
    return item


def list_documents() -> list[dict]:
    items = []
    for meta in outputs_dir().glob("*.json"):
        try:
            items.append(json.loads(meta.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(items, key=lambda d: d.get("created_at", ""), reverse=True)


def get_document(doc_id: str) -> tuple[dict, Path] | None:
    """Metadata and file for an id. Rejects anything that isn't a plain id (no traversal)."""
    if not ID_RE.match(doc_id) or doc_id.startswith("."):
        return None
    base = outputs_dir().resolve()
    meta = (base / f"{doc_id}.json").resolve()
    if meta.parent != base or not meta.is_file():
        return None
    item = json.loads(meta.read_text(encoding="utf-8"))
    path = (base / item["file_name"]).resolve()
    if path.parent != base or not path.is_file():
        return None
    return item, path
