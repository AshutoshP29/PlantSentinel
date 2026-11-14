import shutil
from pathlib import Path

import pytest

import seed_demo
from app import config
from app.db import connect

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private copy of the committed data, so the seed never rewrites tracked files."""
    d = tmp_path / "data"
    for sub in ("synthetic", "scans", "raw"):
        shutil.copytree(REPO / "data" / sub, d / sub)
    monkeypatch.setenv("DATA_DIR", str(d))
    monkeypatch.setenv("DB_PATH", str(d / "seed.db"))
    config.get_settings.cache_clear()
    return d


def test_full_seed_without_ollama(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert seed_demo.main(["--reset", "--skip-manuals", "--skip-inspections"]) == 0
    out = capsys.readouterr().out
    assert "verify       ok   top 3 = P-101, C-203, E-302" in out
    assert "risk model   ok   trained" in out  # tmp MODELS_DIR starts empty
    assert "Seed complete with warnings: manuals, inspections." in out

    conn = connect(data_dir / "seed.db")
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("assets", "work_orders", "failure_modes")
    }
    unassigned = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE failure_mode_id IS NULL"
    ).fetchone()[0]
    conn.close()
    assert counts == {"assets": 30, "work_orders": 491, "failure_modes": 16}
    assert unassigned == 0

    # Second run: idempotent, nothing re-inserted, model reused
    assert seed_demo.main(["--skip-manuals", "--skip-inspections"]) == 0
    out = capsys.readouterr().out
    assert "0 new work orders" in out and "model present" in out


def test_missing_data_is_generated(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (data_dir / "synthetic" / "work_orders.csv").unlink()
    for f in (data_dir / "scans").glob("*.jpg"):
        f.unlink()
    ns = seed_demo.argparse.Namespace(regenerate=False, seed=42)
    assert seed_demo.step_data(ns) == "generated"
    assert (data_dir / "synthetic" / "work_orders.csv").exists()
    assert seed_demo.step_scans(ns) == "4 reports rendered"


def test_broken_story_fails_the_run(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wo = data_dir / "synthetic" / "work_orders.csv"
    lines = wo.read_text(encoding="utf-8").splitlines()
    wo.write_text("\n".join(x for x in lines if ",P-101," not in x) + "\n", encoding="utf-8")
    assert seed_demo.main(["--reset", "--skip-manuals", "--skip-inspections"]) == 1
    out = capsys.readouterr().out
    assert "verify       FAIL" in out and "Seed FAILED at: verify" in out


def test_inspection_step_uses_agent_pipeline(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agent import inspections

    seen: list[Path] = []

    def fake_ingest(conn, directory):  # defined here, so no Ollama readiness check
        seen.append(directory)
        return [
            inspections.ScanReport(file="INSP-004_P-101.jpg", status="added", inspection_id="x"),
            inspections.ScanReport(file="INSP-001_P-104.jpg", status="skipped"),
        ]

    monkeypatch.setattr(inspections, "ingest_scans", fake_ingest)
    ns = seed_demo.argparse.Namespace(skip_inspections=False)
    assert seed_demo.step_inspections(ns) == "2 scans: 1 added, 1 skipped"
    assert seen == [data_dir / "scans"]


def test_failed_scan_is_a_warning(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import inspections

    def fake_ingest(conn, directory):
        return [inspections.ScanReport(file="a.jpg", status="failed", detail="bad json")]

    monkeypatch.setattr(inspections, "ingest_scans", fake_ingest)
    with pytest.raises(seed_demo.Skipped, match=r"1 failed; failed: a.jpg: bad json"):
        seed_demo.step_inspections(seed_demo.argparse.Namespace(skip_inspections=False))
