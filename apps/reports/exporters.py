"""Report registry + exporters (DEVELOPMENT.md §4, M7).

Reports are read-only queries over the register, exported via CSV/XLSX
(openpyxl) or PDF (reportlab) — §4 "same service layer as the UI". Each report
is a `Report` with a query returning `(headers, rows)`; the `export_*` helpers
render those to the requested format. Heavy exports run in Celery, never in the
request cycle (§17).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class Report:
    slug: str
    title: str  # already localized by the caller (§8 i18n)
    query: Callable[..., tuple[list[str], list[list[Any]]]]
    formats: tuple[str, ...] = ("csv", "xlsx")
    description: str = ""


# --------------------------------------------------------------------------
# Exporters
# --------------------------------------------------------------------------


def export_csv(headers: list[str], rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for row in rows:
        w.writerow(["" if c is None else c for c in row])
    # utf-8-sig so Excel opens Myanmar text correctly
    return buf.getvalue().encode("utf-8-sig")


def export_xlsx(title: str, headers: list[str], rows: list[list[Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    # Excel forbids / \ ? * [ ] in sheet names (§4 titles come from i18n strings)
    clean = "".join("-" if ch in r"/:\?*[]" else ch for ch in title).strip()
    ws.title = clean[:31] or "Report"
    ws.append(headers)
    for row in rows:
        ws.append(["" if c is None else c for c in row])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_pdf(title: str, headers: list[str], rows: list[list[Any]], subtitle: str = "") -> bytes:
    """Landscape A4 table with a running header; wraps long cells."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        topMargin=15 * mm,
        bottomMargin=12 * mm,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"])]
    if subtitle:
        story.append(Paragraph(subtitle, styles["Normal"]))
    story.append(Spacer(1, 4 * mm))

    maxw = landscape(A4)[0] - 24 * mm
    ncol = max(1, len(headers))
    colw = maxw / ncol
    table_data = [headers] + [
        [Paragraph(str("" if c is None else c)[:120], styles["Normal"]) for c in row]
        for row in rows
    ]
    t = Table(table_data, colWidths=[colw] * ncol, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f4c81")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f9")]),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(t)
    doc.build(story)
    return buf.getvalue()


def export(
    fmt: str, title: str, headers: list[str], rows: list[list[Any]], subtitle: str = ""
) -> tuple[bytes, str, str]:
    """Render to `fmt` → (content, content_type, filename)."""
    stamp = date.today().isoformat()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in title)[:40] or "report"
    if fmt == "csv":
        return export_csv(headers, rows), "text/csv; charset=utf-8", f"{safe}-{stamp}.csv"
    if fmt == "xlsx":
        return (
            export_xlsx(title, headers, rows),
            ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            f"{safe}-{stamp}.xlsx",
        )
    if fmt == "pdf":
        return export_pdf(title, headers, rows, subtitle), "application/pdf", f"{safe}-{stamp}.pdf"
    raise ValueError(f"unsupported format: {fmt}")


# --------------------------------------------------------------------------
# Registry — populated by registry.py once query fns are defined
# --------------------------------------------------------------------------

REGISTRY: dict[str, Report] = {}


def register(report: Report) -> Report:
    REGISTRY[report.slug] = report
    return report


def get(slug: str) -> Report:
    if slug not in REGISTRY:
        raise KeyError(slug)
    return REGISTRY[slug]
