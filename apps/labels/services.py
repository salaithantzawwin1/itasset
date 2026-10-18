"""QR + PDF asset labels (DEVELOPMENT.md §2/§13/§16, M3).

- `qr_png(asset)` → PNG bytes of the QR code encoding the asset's URL
- `label_pdf(assets)` → Avery-style L7160 sheet (3×7, 63.5×38.1 mm) PDF
  with QR + human-readable Code-128 line (§13 barcode policy).
"""

from __future__ import annotations

import io

import qrcode
from reportlab.graphics.barcode import code128
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def qr_png(asset, *, box_size: int = 8, border: int = 2) -> bytes:
    """PNG bytes of the QR code for *asset* (encodes its public URL, §13)."""
    from django.urls import reverse

    url = asset.asset_tag  # short, machine-readable content
    try:
        path = reverse("asset-detail", args=[asset.pk])
        url = f"http://itasset.local{path}" if not url else url
    except Exception:  # pragma: no cover - reverse always works in practice
        pass

    img = qrcode.make(asset.asset_tag, box_size=box_size, border=border)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def code128_barcode(text: str, *, height: float = 6 * mm, font_size: float = 7):
    """Code-128 barcode flowable with the human-readable line (§13).

    reportlab ≥4.4 exposes Code128 as a platypus Flowable — draw it with
    `drawOn(canvas, x, y)` rather than adding it to a Drawing.
    """
    return code128.Code128(text, barHeight=height, humanReadable=True, fontSize=font_size)


def label_pdf(assets, *, per_sheet: int = 21) -> bytes:
    """One A4 sheet of labels (3 cols × 7 rows = 21, L7160 geometry).

    Each label: QR (left), asset tag + model/site (right), Code-128 line below.
    Returns PDF bytes; caller sets the Content-Disposition.
    """
    page_w, page_h = A4
    cols, rows = 3, 7
    per_sheet = cols * rows
    margin_x, margin_y = 7.1 * mm, 13.6 * mm  # L7160 sheet margins
    pitch_x, pitch_y = 70.6 * mm, 38.1 * mm
    label_w, label_h = 63.5 * mm, 38.1 * mm

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Asset labels")

    for i, asset in enumerate(assets):
        slot = i % per_sheet
        if i and slot == 0:
            c.showPage()
        col, row = slot % cols, slot // cols
        x = margin_x + col * pitch_x
        y = page_h - margin_y - (row + 1) * pitch_y

        # QR, left side of the label
        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(asset.asset_tag)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        qr_buf = io.BytesIO()
        img.save(qr_buf, format="PNG")
        qr_buf.seek(0)
        c.drawImage(
            ImageReader(qr_buf),
            x + 1 * mm,
            y + 6 * mm,
            width=22 * mm,
            height=22 * mm,
            mask="auto",
        )

        # text block, right side
        tx = x + 25 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(tx, y + 27 * mm, asset.asset_tag)
        c.setFont("Helvetica", 7)
        c.drawString(tx, y + 23 * mm, f"{asset.model_name or asset.category.name}"[:34])
        c.drawString(
            tx, y + 20 * mm, f"Site: {asset.site.code} · SN: {(asset.serial_no or '—')[:20]}"
        )
        c.drawString(tx, y + 17 * mm, f"Warranty: {asset.warranty_end or '—'}")

        # human-readable Code-128 under the QR (§13)
        barcode = code128_barcode(asset.asset_tag, height=5 * mm, font_size=6)
        barcode.drawOn(c, x + 0.5 * mm, y + 0.8 * mm)

        # label border
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        c.rect(x, y, label_w, label_h)

    c.showPage()
    c.save()
    return buf.getvalue()
