"""Scanned inspection reports -> `inspections` table (raw_text + extracted_json).

Run at seeding time, not during a live question: the vision model is slow on a 6 GB GPU.

    scan (png/jpg/pdf) -> page images -> vision model transcribes each page (raw_text)
    -> vision model extracts structured findings (JSON schema) -> one inspections row

The vision call is injectable (`VisionFn`) so the pipeline is testable without Ollama.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.agent.data import normalise_tag
from app.config import get_settings

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
SCAN_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}

# (prompt, images as PNG/JPEG bytes, optional JSON schema) -> model text
VisionFn = Callable[[str, list[bytes], dict | None], str]

TRANSCRIBE_PROMPT = (
    "This is one page of a scanned equipment inspection report. Transcribe all text on the page "
    "exactly as written, top to bottom, keeping table rows on separate lines. Do not summarise, "
    "correct or add anything. If a value is unreadable write [illegible]."
)

EXTRACT_PROMPT = """Extract the inspection report below into JSON matching the schema.
Use only what the text says. Do not invent values; use null or an empty list when absent.
A finding is flagged when the report marks it as abnormal, out of tolerance, failed or as
needing action. Keep measured values and units exactly as written (e.g. "0.3 mm").
`page` is the page number (from the [page N] markers) the finding appears on.

Report file: {file_name}

{text}
"""


class Finding(BaseModel):
    item: str = Field(description="What was inspected, e.g. 'Coupling alignment'.")
    result: str = Field(description="Result as written, e.g. 'Misalignment observed: 0.3 mm'.")
    flagged: bool = False
    page: int = 1


class InspectionExtract(BaseModel):
    tag: str | None = Field(None, description="Equipment tag, e.g. P-101.")
    date: str | None = Field(None, description="Inspection date as YYYY-MM-DD.")
    inspector: str | None = None
    report_no: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""

    @field_validator("date")
    @classmethod
    def _iso_date(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            return date.fromisoformat(v.strip()[:10]).isoformat()
        except ValueError:
            return None  # unreadable date: leave empty rather than guess


class ScanReport(BaseModel):
    file: str
    status: str  # "added" | "skipped" | "failed"
    inspection_id: str | None = None
    detail: str = ""


# --------------------------------------------------------------------------- vision model


def ollama_vision(prompt: str, images: list[bytes], schema: dict | None = None) -> str:
    """Call the local Ollama vision model. All traffic stays on OLLAMA_HOST."""
    s = get_settings()
    body: dict = {
        "model": s.vision_model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(i).decode() for i in images],
            }
        ],
        "stream": False,
        "keep_alive": s.llm_keep_alive_s,
        "options": {"temperature": 0, "num_ctx": s.llm_num_ctx},
    }
    if schema:
        body["format"] = schema
    r = httpx.post(f"{s.ollama_host}/api/chat", json=body, timeout=s.llm_timeout_s * 2)
    r.raise_for_status()
    return r.json()["message"]["content"]


# --------------------------------------------------------------------------- pipeline


def page_images(path: Path, dpi: int = 150) -> list[bytes]:
    """PNG/JPEG bytes for each page of a scan (PDF pages are rendered)."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return [path.read_bytes()]
    if suffix == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]
    raise ValueError(f"Unsupported scan type: {path.name}")


def _tag_from_name(name: str) -> str | None:
    try:
        return normalise_tag(name.replace("_", " "))
    except ValueError:
        return None


def read_scan(path: Path, vision: VisionFn = ollama_vision) -> tuple[str, InspectionExtract]:
    """Transcribe every page, then extract structured findings. Returns (raw_text, extract)."""
    pages = page_images(path)
    texts = [vision(TRANSCRIBE_PROMPT, [img], None).strip() for img in pages]
    raw_text = "\n\n".join(f"[page {i}]\n{t}" for i, t in enumerate(texts, start=1))
    schema = InspectionExtract.model_json_schema()
    prompt = EXTRACT_PROMPT.format(file_name=path.name, text=raw_text)
    last_err = ""
    for attempt in range(2):
        out = vision(
            prompt if not attempt else f"{prompt}\nPrevious JSON invalid: {last_err}", [], schema
        )
        try:
            extract = InspectionExtract.model_validate_json(out)
            break
        except ValidationError as exc:
            last_err = str(exc)[:300]
    else:
        raise ValueError(f"vision model returned invalid JSON for {path.name}: {last_err}")
    # The file name is a reliable fallback for the tag; the model's reading wins if valid.
    tag = None
    if extract.tag:
        try:
            tag = normalise_tag(extract.tag)
        except ValueError:
            tag = None
    extract.tag = tag or _tag_from_name(path.stem)
    for f in extract.findings:
        f.page = min(max(f.page, 1), len(pages))
    return raw_text, extract


def inspection_id(conn: sqlite3.Connection, tag: str, day: str | None) -> str:
    base = f"INSP-{tag.replace('-', '')}-{(day or 'undated').replace('-', '')}"
    n = conn.execute("SELECT COUNT(*) FROM inspections WHERE id LIKE ?", (f"{base}%",)).fetchone()
    return base if not n[0] else f"{base}-{n[0] + 1}"


def ingest_scans(
    conn: sqlite3.Connection,
    scans_dir: Path | None = None,
    vision: VisionFn = ollama_vision,
    force: bool = False,
) -> list[ScanReport]:
    """Read every scan in `scans_dir` into the inspections table. Idempotent by file path."""
    directory = scans_dir or get_settings().scans_dir
    reports: list[ScanReport] = []
    for path in sorted(p for p in directory.glob("*") if p.suffix.lower() in SCAN_SUFFIXES):
        rel = _rel(path)
        existing = conn.execute("SELECT id FROM inspections WHERE file_path = ?", (rel,)).fetchone()
        if existing and not force:
            reports.append(ScanReport(file=path.name, status="skipped", inspection_id=existing[0]))
            continue
        try:
            raw_text, ex = read_scan(path, vision)
            if not ex.tag:
                raise ValueError("no equipment tag in the report or the file name")
            if not conn.execute("SELECT 1 FROM assets WHERE tag = ?", (ex.tag,)).fetchone():
                raise ValueError(f"tag {ex.tag} is not in the equipment register")
            if existing:
                conn.execute("DELETE FROM inspections WHERE id = ?", (existing[0],))
            iid = inspection_id(conn, ex.tag, ex.date)
            meta = {**ex.model_dump(), "pages": len(page_images(path)), "file_name": path.name}
            conn.execute(
                "INSERT INTO inspections(id, tag, date, file_path, raw_text, extracted_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (iid, ex.tag, ex.date, rel, raw_text, json.dumps(meta)),
            )
            conn.commit()
            reports.append(ScanReport(file=path.name, status="added", inspection_id=iid))
            log.info("inspection %s from %s: %d findings", iid, path.name, len(ex.findings))
        except Exception as exc:
            log.exception("could not read scan %s", path.name)
            reports.append(ScanReport(file=path.name, status="failed", detail=str(exc)))
    return reports


def _rel(path: Path) -> str:
    from app.config import REPO_ROOT

    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


# --------------------------------------------------------------------------- queries


def to_api(row: sqlite3.Row | dict) -> dict:
    """Shape used by the frontend (`Inspection` in frontend/src/api/types.ts)."""
    r = dict(row)
    meta = json.loads(r.get("extracted_json") or "{}")
    findings = meta.get("findings", [])
    flagged = [f for f in findings if f.get("flagged")]
    return {
        "id": r["id"],
        "tag": r["tag"],
        "date": r.get("date"),
        "inspector": meta.get("inspector") or "",
        "report_no": meta.get("report_no") or "",
        "page": (flagged or findings or [{"page": 1}])[0].get("page", 1),
        "pages": meta.get("pages", 1),
        "findings": [
            {"item": f["item"], "result": f["result"], "flagged": bool(f.get("flagged"))}
            for f in findings
        ],
        "file_path": r.get("file_path") or "",
        "summary": meta.get("summary", ""),
    }


def latest_inspection(conn: sqlite3.Connection, tag: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM inspections WHERE tag = ? ORDER BY date DESC, id DESC LIMIT 1", (tag,)
    ).fetchone()
    return dict(row) if row else None


def get_inspection(conn: sqlite3.Connection, inspection_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM inspections WHERE id = ?", (inspection_id,)).fetchone()
    return dict(row) if row else None


INSP_RE = re.compile(r"INSP-[A-Z0-9]+-[A-Za-z0-9]+(?:-\d+)?")
