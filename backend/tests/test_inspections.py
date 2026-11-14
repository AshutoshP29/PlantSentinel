import json

import pymupdf
import pytest

from app.agent import inspections
from tests.agent_helpers import seeded_conn

EXTRACT = {
    "tag": "P 101",
    "date": "2026-11-02",
    "inspector": "R. Iyer",
    "report_no": "IR-2026-118",
    "findings": [
        {"item": "Mechanical seal", "result": "Leakage at gland", "flagged": True, "page": 1},
        {
            "item": "Coupling alignment",
            "result": "Misalignment observed: 0.3 mm",
            "flagged": True,
            "page": 2,
        },
        {"item": "Bearing temperature", "result": "68 degC", "flagged": False, "page": 9},
    ],
    "summary": "Seal leaking; coupling misaligned.",
}


def make_pdf(path, pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Inspection report page {i + 1}")
    doc.save(str(path))
    doc.close()


class FakeVision:
    def __init__(self, extract=EXTRACT, bad_first=False):
        self.calls = []
        self.extract = extract
        self.bad_first = bad_first

    def __call__(self, prompt, images, schema):
        self.calls.append((prompt, len(images), schema is not None))
        if schema is None:
            return f"transcribed page {len([c for c in self.calls if not c[2]])}"
        if self.bad_first:
            self.bad_first = False
            return "{not json"
        return json.dumps(self.extract)


def test_scan_to_inspection_row(tmp_path) -> None:
    make_pdf(tmp_path / "P-101_inspection_2026-11-02.pdf")
    conn = seeded_conn()
    vision = FakeVision(bad_first=True)
    (rep,) = inspections.ingest_scans(conn, tmp_path, vision)
    assert rep.status == "added" and rep.inspection_id == "INSP-P101-20261102"
    # 2 page transcriptions (one image each), then extraction (no image) with one retry
    assert [(n, s) for _, n, s in vision.calls] == [(1, False), (1, False), (0, True), (0, True)]
    assert "[page 2]\ntranscribed page 2" in vision.calls[2][0]

    row = inspections.latest_inspection(conn, "P-101")
    assert row["date"] == "2026-11-02" and row["file_path"].endswith(".pdf")
    assert "[page 1]\ntranscribed page 1" in row["raw_text"]
    api = inspections.to_api(row)
    assert api["tag"] == "P-101" and api["pages"] == 2 and api["page"] == 1
    assert api["findings"][2]["flagged"] is False
    assert json.loads(row["extracted_json"])["findings"][2]["page"] == 2  # clamped to pages


def test_rerun_is_idempotent_and_force_replaces(tmp_path) -> None:
    make_pdf(tmp_path / "P-101_inspection.pdf", pages=1)
    conn = seeded_conn()
    inspections.ingest_scans(conn, tmp_path, FakeVision())
    (again,) = inspections.ingest_scans(conn, tmp_path, FakeVision())
    assert again.status == "skipped" and again.inspection_id == "INSP-P101-20261102"
    (forced,) = inspections.ingest_scans(conn, tmp_path, FakeVision(), force=True)
    assert forced.status == "added"
    assert conn.execute("SELECT COUNT(*) FROM inspections").fetchone()[0] == 1


def test_tag_falls_back_to_file_name_and_bad_dates_are_dropped(tmp_path) -> None:
    (tmp_path / "C-203_scan.png").write_bytes(make_png())
    conn = seeded_conn()
    ex = {**EXTRACT, "tag": None, "date": "14/11/2026"}
    (rep,) = inspections.ingest_scans(conn, tmp_path, FakeVision(ex))
    assert rep.status == "added" and rep.inspection_id == "INSP-C203-undated"


def test_unknown_tag_fails_without_writing(tmp_path) -> None:
    make_pdf(tmp_path / "scan.pdf", pages=1)
    conn = seeded_conn()
    (rep,) = inspections.ingest_scans(conn, tmp_path, FakeVision({**EXTRACT, "tag": "X-999"}))
    assert rep.status == "failed" and "not in the equipment register" in rep.detail
    assert conn.execute("SELECT COUNT(*) FROM inspections").fetchone()[0] == 0


def test_unsupported_file_is_ignored(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("x")
    assert inspections.ingest_scans(seeded_conn(), tmp_path, FakeVision()) == []


def test_ollama_vision_request_is_local(monkeypatch) -> None:
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}}

    def fake_post(url, json, timeout):
        sent.update(url=url, body=json)
        return Resp()

    monkeypatch.setattr(inspections.httpx, "post", fake_post)
    assert inspections.ollama_vision("read", [b"\x89PNG"], {"type": "object"}) == "ok"
    assert sent["url"].endswith("/api/chat") and sent["url"].startswith("http://localhost")
    msg = sent["body"]["messages"][0]
    assert msg["images"] == ["iVBORw=="] and sent["body"]["format"] == {"type": "object"}
    assert sent["body"]["model"] == "qwen2.5vl:3b"


def make_png() -> bytes:
    doc = pymupdf.open()
    doc.new_page(width=100, height=100)
    png = doc[0].get_pixmap(dpi=20).tobytes("png")
    doc.close()
    return png


@pytest.mark.parametrize("name,tag", [("P-101_report.pdf", "P-101"), ("random.pdf", None)])
def test_tag_from_name(name, tag) -> None:
    assert inspections._tag_from_name(name) == tag
