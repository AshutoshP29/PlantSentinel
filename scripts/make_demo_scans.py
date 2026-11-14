"""Render the demo inspection reports as scanned-looking images in data/scans/.

The team may replace these with real printed-and-photographed copies; the content is the
planted story (INSP-004: P-101 shaft misalignment 0.3 mm at the coupling, vs the manual's
0.05 mm tolerance). Deterministic: same output every run.

    uv run python scripts/make_demo_scans.py
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[1]

REPORTS: list[dict] = [
    {
        "id": "INSP-001",
        "tag": "P-104",
        "date": "2026-09-22",
        "title": "Routine Condition Monitoring - Pump P-104",
        "unit": "Hydrotreater",
        "reason": "Quarterly condition monitoring round.",
        "findings": [
            "Vibration DE bearing 2.1 mm/s RMS, NDE 1.8 mm/s RMS (alarm 4.5). Normal.",
            "Bearing housing temperature 54 C. Normal.",
            "Mechanical seal: no visible leakage. Seal pot level normal.",
            "Coupling guard secure. Base bolts tight.",
        ],
        "recommendations": ["No action. Next round as per schedule."],
        "skew": -0.6,
    },
    {
        "id": "INSP-002",
        "tag": "E-302",
        "date": "2026-10-08",
        "title": "Heat Exchanger Inspection - E-302 VDU Preheat",
        "unit": "VDU",
        "reason": "Follow-up after repeated high differential pressure (WO-0472).",
        "findings": [
            "Tube side differential pressure 1.9 bar (clean design 0.8 bar).",
            "Outlet temperature 14 C below design at normal throughput.",
            "Visual through channel head: heavy scale / coke deposits on tube inlets.",
            "Hydrotest of bundle: no tube leak detected on this date.",
        ],
        "recommendations": [
            "Hydrojet bundle at next opportunity.",
            "Review crude blend and desalter performance (fouling source).",
        ],
        "skew": 0.9,
    },
    {
        "id": "INSP-003",
        "tag": "C-203",
        "date": "2026-10-20",
        "title": "Compressor Inspection - C-203 Recycle Gas",
        "unit": "Offsites",
        "reason": "Follow-up after high bearing temperature trip (WO-0478).",
        "findings": [
            "NDE bearing temperature 92 C at trip (alarm 85 C, trip 95 C).",
            "Lube oil sample: darkened, viscosity 18% below grade, water 0.2%.",
            "Lube oil cooler outlet 9 C above design: cooler fouled on water side.",
            "Bearing clearance within limits; no babbitt damage seen.",
        ],
        "recommendations": [
            "Change lube oil and filters; clean lube oil cooler.",
            "Monthly oil analysis until bearing temperature is stable.",
        ],
        "skew": -1.1,
    },
    {
        "id": "INSP-004",
        "tag": "P-101",
        "date": "2026-11-06",
        "title": "Root Cause Inspection - Crude Feed Pump P-101",
        "unit": "CDU-1",
        "reason": (
            "RCA requested after 4th mechanical seal failure in 6 months (WO-0486). "
            "Pump stopped, isolated and handed over for inspection."
        ),
        "findings": [
            "Mechanical seal (DE): leakage at seal faces. Faces show uneven, one-sided wear "
            "track; carbon face chipped at outer edge.",
            "Coupling alignment check (dial indicator): shaft misalignment 0.3 mm observed at "
            "coupling (parallel offset). Angular 0.12 mm per 100 mm.",
            "Soft foot at motor NDE foot: 0.15 mm.",
            "Vibration before shutdown: DE bearing 7.1 mm/s RMS horizontal (alarm 4.5), "
            "dominant at 2x running speed.",
            "Bearing temperatures 66 C DE / 61 C NDE. Bearings serviceable.",
        ],
        "recommendations": [
            "Correct soft foot, then laser-align pump and motor to manufacturer tolerance.",
            "Replace mechanical seal with new cartridge after alignment.",
            "Re-check vibration within 24 h of restart.",
        ],
        "skew": 0.7,
    },
]


def _page(r: dict) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 points
    y = 60

    def line(text: str, size: float = 10.5, bold: bool = False, indent: int = 0) -> None:
        nonlocal y
        font = "hebo" if bold else "helv"
        box = pymupdf.Rect(60 + indent, y, 535, y + 200)
        used = page.insert_textbox(box, text, fontsize=size, fontname=font)
        y += (200 - used) + size * 0.6 if used >= 0 else 200

    line("PLANT MAINTENANCE DEPARTMENT", 13, bold=True)
    line("Equipment Inspection Report", 11)
    y += 6
    page.draw_line((60, y), (535, y), width=0.8)
    y += 10
    for label, value in [
        ("Report No.", r["id"]),
        ("Equipment tag", r["tag"]),
        ("Unit / area", r["unit"]),
        ("Date of inspection", r["date"]),
        ("Subject", r["title"]),
    ]:
        line(f"{label}:  {value}", 10.5)
    y += 6
    line("Reason for inspection", 11, bold=True)
    line(r["reason"])
    y += 4
    line("Findings", 11, bold=True)
    for i, f in enumerate(r["findings"], 1):
        line(f"{i}. {f}", indent=8)
    y += 4
    line("Recommendations", 11, bold=True)
    for i, rec in enumerate(r["recommendations"], 1):
        line(f"{i}. {rec}", indent=8)
    y += 30
    line("Inspected by: ____________________      Reviewed by: ____________________", 10)
    return doc


def render_scan(r: dict, dpi: int = 130, seed: int = 0) -> bytes:
    """JPEG bytes of the report as a slightly skewed, noisy grayscale scan."""
    page = _page(r)[0]
    mat = pymupdf.Matrix(dpi / 72, dpi / 72).prerotate(r["skew"])
    pix = page.get_pixmap(matrix=mat, colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(float)
    rng = np.random.default_rng(seed)
    paper = 236 + 6 * np.sin(np.linspace(0, 3, img.shape[1]))[None, :]  # uneven lighting
    img = np.where(img > 250, paper, img * 0.9)  # off-white paper, slightly faded ink
    img += rng.normal(0, 7, img.shape)  # sensor noise
    specks = rng.random(img.shape) < 0.0006
    img[specks] = rng.integers(60, 160, specks.sum())  # dust
    out = np.clip(img, 0, 255).astype(np.uint8)
    scan = pymupdf.Pixmap(pymupdf.csGRAY, pix.width, pix.height, out.tobytes(), False)
    return scan.tobytes("jpg", jpg_quality=82)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=ROOT / "data" / "scans")
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(REPORTS):
        path = args.out / f"{r['id']}_{r['tag']}.jpg"
        path.write_bytes(render_scan(r, seed=i))
        print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
