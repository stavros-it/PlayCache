"""Export the SQLite catalog to an .xlsx file matching Game_Library.xlsx layout."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .db import Database

HEADERS = [
    "GAME NAME", "PLATFORM", "GOG / STEAM", "USER RATING",
    "GAME TYPE", "SHORT DESCRIPTION",
]


def export_xlsx(db: Database, output_path: str) -> str:
    rows = db.list_excel_view()
    wb = Workbook()
    ws = wb.active
    ws.title = "Game Library"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="305496")
    for col, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    for r, row in enumerate(rows, start=2):
        for c, header in enumerate(HEADERS, 1):
            val = row.get(header, "")
            if val is None:
                val = ""
            cell = ws.cell(row=r, column=c, value=val)
            if header == "SHORT DESCRIPTION":
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            else:
                cell.alignment = Alignment(vertical="top")

    # Column widths
    widths = [42, 16, 16, 14, 24, 90]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    # Auto-filter on the header row so users can sort/filter in Excel.
    ws.auto_filter.ref = ws.dimensions

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(out)
    except PermissionError as e:
        raise PermissionError(
            f"Cannot write to '{out}'. The file may be open in another "
            f"program (e.g. Excel). Close it and try again."
        ) from e
    return str(out)
