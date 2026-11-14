"""Bad-actor report (.xlsx) built with openpyxl from the bad-actor ranking."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
PREFERRED = [
    "rank",
    "tag",
    "failure_mode",
    "criticality",
    "score",
    "count_180d",
    "count_total",
    "last_event",
    "mtbf_current_days",
    "mtbf_previous_days",
    "downtime_hrs",
    "cost_inr",
    "work_orders",
    "type",
]


def _columns(rows: list[dict]) -> list[str]:
    keys = {k for r in rows for k, v in r.items() if not isinstance(v, (dict, list))}
    return [c for c in PREFERRED if c in keys] + sorted(keys - set(PREFERRED))


def build_bad_actor_report(
    ranking: dict, out_dir: Path, as_of: str, created: datetime | None = None
) -> Path:
    """`ranking` is analytics.bad_actors(...) output: {"method", "top": [...]}."""
    created = created or datetime.now()
    rows = [{"rank": i, **r} for i, r in enumerate(ranking.get("top", []), start=1)]
    wb = Workbook()
    ws = wb.active
    ws.title = "Bad actors"
    ws["A1"] = "PlantSentinel bad-actor report"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Window ends {as_of}. Generated {created:%Y-%m-%d %H:%M}."
    ws["A3"] = f"Method: {ranking.get('method', 'n/a')}"
    ws["A3"].alignment = Alignment(wrap_text=False)

    cols = _columns(rows)
    for j, col in enumerate(cols, start=1):
        cell = ws.cell(row=5, column=j, value=col.replace("_", " ").title())
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
    for i, r in enumerate(rows, start=6):
        for j, col in enumerate(cols, start=1):
            ws.cell(row=i, column=j, value=r.get(col))
    if not rows:
        ws["A6"] = "No assets ranked."
    for j, col in enumerate(cols, start=1):
        width = max([len(col)] + [len(str(r.get(col, ""))) for r in rows]) + 2
        ws.column_dimensions[get_column_letter(j)].width = min(width, 40)
    ws.freeze_panes = "A6"

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"BAR-{created:%Y%m%d-%H%M%S}.xlsx"
    wb.save(str(path))
    return path
