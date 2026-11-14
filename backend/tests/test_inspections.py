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


# ------------------------------------------------- text-LLM extraction and fallbacks

P101_TRANSCRIPT = """[page 1]
PLANT MAINTENANCE DEPARTMENT
Equipment Inspection Report
Report No.: INSP-004
Equipment tag: P-101
Date of inspection: 2026-11-06
Findings
1. Mechanical seal (DE): leakage at seal faces. Faces show uneven, one-sided wear track;
carbon face chipped at outer edge.
2. Coupling alignment check (dial indicator): shaft misalignment 0.3 mm observed at coupling
(parallel offset). Angular 0.12 mm per 100 mm.
3. Soft foot at motor NDE foot: 0.15 mm.
4. Bearing temperatures 66 C DE / 61 C NDE. Bearings serviceable.
Recommendations
1. Correct soft foot, then laser-align pump and motor to manufacturer tolerance.
Inspected by: [illegible]"""


def test_findings_and_date_from_text() -> None:
    assert inspections.date_from_text(P101_TRANSCRIPT) == "2026-11-06"
    assert inspections.printed_report_id(P101_TRANSCRIPT) == "INSP-004"
    found = inspections.findings_from_text(P101_TRANSCRIPT)
    assert [f.item for f in found] == [
        "Mechanical seal (DE)",
        "Coupling alignment check (dial indicator)",
        "Soft foot at motor NDE foot",
        "Bearing temperatures 66 C DE / 61 C NDE. Bearings serviceable.",
    ]
    assert "shaft misalignment 0.3 mm observed at coupling (parallel offset)" in found[1].result
    assert "carbon face chipped" in found[0].result  # wrapped line joined
    assert [f.flagged for f in found] == [True, True, True, False]
    assert all(f.page == 1 for f in found)
    # recommendations are not findings
    assert not any("laser-align" in f.result for f in found)


def test_empty_model_reply_falls_back_to_the_transcript(tmp_path) -> None:
    """The real failure seen with qwen2.5vl:3b: findings [] and date null."""
    scan = tmp_path / "INSP-004_P-101.png"
    scan.write_bytes(make_png())
    empty = json.dumps({"tag": "P-101", "date": None, "report_no": None, "findings": []})
    calls: list[str] = []

    def vision(prompt, images, schema):
        calls.append("vision")
        return P101_TRANSCRIPT.split("\n", 1)[1]

    def extract(prompt, schema):
        calls.append("extract")
        assert "shaft misalignment 0.3 mm" in prompt and schema
        return empty

    _, ex = inspections.read_scan(scan, vision, extract)
    assert calls == ["vision", "extract"]
    assert ex.date == "2026-11-06" and ex.report_no == "INSP-004"
    assert len(ex.findings) == 4 and ex.findings[1].flagged


def test_model_findings_win_over_fallback(tmp_path) -> None:
    scan = tmp_path / "s.png"
    scan.write_bytes(make_png())
    reply = {"tag": "P-101", "date": "2026-11-06", "findings": [{"item": "x", "result": "y"}]}
    _, ex = inspections.read_scan(
        scan, lambda p, i, s: P101_TRANSCRIPT, lambda p, s: json.dumps(reply)
    )
    assert [(f.item, f.result) for f in ex.findings] == [("x", "y")]
    assert not ex.findings[0].flagged


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("Coupling alignment: shaft misalignment 0.3 mm observed", True),
        ("Vibration DE 7.1 mm/s RMS (alarm 4.5), dominant at 2x", True),
        ("Vibration DE 2.1 mm/s RMS (alarm 4.5). Normal.", False),
        ("Mechanical seal: no visible leakage. Seal pot level normal.", False),
        ("Bearing clearance within limits; no babbitt damage seen.", False),
        ("Lube oil sample: darkened, viscosity 18% below grade", True),
        ("Bearing temperatures 66 C DE / 61 C NDE. Bearings serviceable.", False),
        ("Hydrotest of bundle: no tube leak detected", False),
    ],
)
def test_looks_abnormal(text: str, flag: bool) -> None:
    assert inspections.looks_abnormal(text) is flag


def test_model_findings_get_flagged_from_wording(tmp_path) -> None:
    scan = tmp_path / "s.png"
    scan.write_bytes(make_png())
    reply = {
        "tag": "P-101",
        "findings": [
            {"item": "Coupling alignment check", "result": "shaft misalignment 0.3 mm"},
            {"item": "Bearing temperatures", "result": "66 C DE. Bearings serviceable"},
        ],
    }
    _, ex = inspections.read_scan(
        scan, lambda p, i, s: P101_TRANSCRIPT, lambda p, s: json.dumps(reply)
    )
    assert [f.flagged for f in ex.findings] == [True, False]


def test_default_extractor_uses_text_model_and_vision_is_capped(monkeypatch) -> None:
    sent: list[dict] = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "{}"}}

    monkeypatch.setattr(
        inspections.httpx, "post", lambda url, json, timeout: sent.append(json) or Resp()
    )
    inspections.ollama_extract("structure this", {"type": "object"})
    inspections.ollama_vision("read", [b"\x89PNG"], None)
    extract_body, vision_body = sent
    assert extract_body["model"] == "qwen2.5:7b-instruct-q3_K_M"
    assert (
        extract_body["format"] == {"type": "object"} and "images" not in extract_body["messages"][0]
    )
    assert vision_body["model"] == "qwen2.5vl:3b"
    assert vision_body["options"]["num_predict"] == 1500
    assert vision_body["options"]["repeat_penalty"] > 1
