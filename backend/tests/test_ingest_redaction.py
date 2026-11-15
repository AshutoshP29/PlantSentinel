"""PII redaction on ingest: work orders (API and seed path) and scanned inspections."""

import json
from pathlib import Path

import pandas as pd
import pymupdf
import pytest

from app.agent import inspections
from app.db import connect, init_db
from app.guard.audit import count_redactions
from app.guard.redaction import redact, redact_text, redact_value
from app.ingestion.work_orders import ingest_assets, ingest_work_orders

REPO = Path(__file__).resolve().parents[2]
SYN = REPO / "data" / "synthetic"

PII_ROWS = [
    {
        "id": "WO-9001",
        "tag": "P-101",
        "date": "2026-11-10",
        "description": "seal lkg, call Ravi on 98765 43210",
        "action_taken": "report sent to ravi.k@plant.co.in",
    },
    {
        "id": "WO-9002",
        "tag": "P-101",
        "date": "2026-11-11",
        "description": "DCS login password: hunter2 shared on site",
        "action_taken": "seal replaced",
    },
]


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    ingest_assets(c, pd.read_csv(SYN / "assets.csv"))
    return c


def test_plant_text_is_never_touched() -> None:
    """No false positives on the whole synthetic history or on measurement-heavy text."""
    wo = pd.read_csv(SYN / "work_orders.csv")
    texts = [*wo["description"].dropna(), *wo["action_taken"].dropna()]
    assert sum(redact(t)[1] for t in texts) == 0
    sample = (
        "INSP-004 2026-11-06 WO-0486 misalignment 0.3 mm, angular 0.12 mm per 100 mm, "
        "7.1 mm/s RMS, 113400.0, 12537.6 Nm.min, P-101 at 2950 rpm, 18% below grade"
    )
    assert redact(sample) == (sample, 0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call Ravi on 98765 43210", "call Ravi on [REDACTED:phone]"),
        ("+91 9876543210 urgent", "[REDACTED:phone] urgent"),
        ("mail ravi.k@plant.co.in", "mail [REDACTED:email]"),
        ("password: hunter2", "password: [REDACTED:secret]"),
        ("Aadhaar 1234 5678 9012", "Aadhaar [REDACTED:id]"),
    ],
)
def test_personal_data_is_redacted(text: str, expected: str) -> None:
    assert redact_text(text) == expected


def test_redact_value_walks_nested_data() -> None:
    value = {"findings": [{"result": "ok"}, {"result": "ring 9876543210"}], "pages": 1}
    out, n = redact_value(value)
    assert n == 1 and out["findings"][1]["result"] == "ring [REDACTED:phone]"
    assert out["pages"] == 1 and value["findings"][1]["result"] == "ring 9876543210"


def test_ingest_redacts_by_default_and_counts(conn) -> None:
    res = ingest_work_orders(conn, pd.DataFrame(PII_ROWS))
    assert res["inserted"] == 2 and res["redacted"] == 3
    rows = dict(
        (r["id"], f"{r['description']} | {r['action_taken']}")
        for r in conn.execute("SELECT id, description, action_taken FROM work_orders")
    )
    assert rows["WO-9001"] == (
        "seal lkg, call Ravi on [REDACTED:phone] | report sent to [REDACTED:email]"
    )
    assert "hunter2" not in rows["WO-9002"] and "[REDACTED:secret]" in rows["WO-9002"]
    assert count_redactions(conn) == 3


def test_ingest_without_redactor_stores_text_unchanged(conn) -> None:
    res = ingest_work_orders(conn, pd.DataFrame(PII_ROWS[:1]), redact=None)
    assert res["redacted"] == 0
    (desc,) = conn.execute("SELECT description FROM work_orders").fetchone()
    assert desc == "seal lkg, call Ravi on 98765 43210"


def test_synthetic_history_ingests_with_nothing_redacted(conn) -> None:
    res = ingest_work_orders(conn, pd.read_csv(SYN / "work_orders.csv"))
    assert res["inserted"] == 491 and res["redacted"] == 0


def test_upload_endpoint_redacts(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import config
    from app.main import app

    db = tmp_path / "up.db"
    monkeypatch.setenv("DB_PATH", str(db))
    config.get_settings.cache_clear()
    c = connect(db)
    init_db(c)
    ingest_assets(c, pd.read_csv(SYN / "assets.csv"))
    c.close()
    csv = pd.DataFrame(PII_ROWS).to_csv(index=False).encode()
    r = TestClient(app).post(
        "/api/ingest/work-orders", files={"file": ("export.csv", csv, "text/csv")}
    )
    assert r.status_code == 200 and r.json()["redacted"] == 3
    c = connect(db)
    stored = " ".join(row[0] for row in c.execute("SELECT description FROM work_orders"))
    c.close()
    assert "98765" not in stored and "hunter2" not in stored


def test_scanned_inspection_is_redacted_before_storage(conn, tmp_path) -> None:
    pdf = tmp_path / "INSP-007_P-101.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "scan")
    doc.save(str(pdf))
    doc.close()
    transcript = "Report No.: INSP-007\nInspector: R. Mehta, 98765 43210\nFindings\n1. Seal ok"
    extract = {
        "tag": "P-101",
        "date": "2026-11-12",
        "report_no": "INSP-007",
        "inspector": "R. Mehta (mehta@plant.co.in)",
        "findings": [{"item": "Seal", "result": "ok, call 9876543210 if it leaks"}],
    }

    def vision(prompt, images, schema):
        return json.dumps(extract) if schema else transcript

    (rep,) = inspections.ingest_scans(conn, tmp_path, vision)
    assert rep.status == "added"
    raw, ex = conn.execute("SELECT raw_text, extracted_json FROM inspections").fetchone()
    assert "98765" not in raw and "[REDACTED:phone]" in raw
    stored = json.loads(ex)
    assert stored["inspector"] == "R. Mehta ([REDACTED:email])"
    assert stored["findings"][0]["result"] == "ok, call [REDACTED:phone] if it leaks"
    assert count_redactions(conn) == 3
