from pathlib import Path

import pymupdf

import make_demo_scans as scans


def test_story_report_content() -> None:
    p101 = next(r for r in scans.REPORTS if r["tag"] == "P-101")
    assert p101["id"] == "INSP-004"
    text = scans._page(p101)[0].get_text()
    assert "shaft misalignment 0.3 mm observed at" in text
    assert "laser-align" in text
    assert "WO-0486" in text


def test_scans_render_deterministically(tmp_path: Path) -> None:
    assert scans.main(["--out", str(tmp_path)]) == 0
    files = sorted(tmp_path.glob("*.jpg"))
    assert [f.name for f in files] == [f"{r['id']}_{r['tag']}.jpg" for r in scans.REPORTS]
    pix = pymupdf.Pixmap(str(files[-1]))
    assert pix.width > 1000 and pix.n == 1  # grayscale, readable resolution
    again = tmp_path / "again"
    scans.main(["--out", str(again)])
    assert (again / files[-1].name).read_bytes() == files[-1].read_bytes()
