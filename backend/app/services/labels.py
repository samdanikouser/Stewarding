import io

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from .traceability import lot_code

LABEL_W_MM, LABEL_H_MM = 75, 50
LABEL = (LABEL_W_MM * mm, LABEL_H_MM * mm)


def _fit(text: str, font: str, size: float, width: float, limit: int) -> list[str]:
    lines = simpleSplit(text, font, size, width)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = lines[-1][: max(len(lines[-1]) - 1, 1)] + "..."
    return lines


def _facts(info: dict) -> list[str]:
    """The readable lines under the item: who supplied it, the original dates, and when it was received or portioned."""
    lot_is_code = info.get("supplier_lot") and info["code"].startswith(lot_code(info["supplier_lot"]))
    supplier = " - ".join(part for part in (info.get("supplier"), f"lot {info['supplier_lot']}" if info.get("supplier_lot") and not lot_is_code else "") if part)
    dates = "   ".join(part for part in (f"Produced {info['produced']}" if info.get("produced") else "",
                                         f"Expiry {info['expiry']}" if info.get("expiry") else "") if part)
    stamped = f"{info.get('stamp_label', 'Received')} {info['stamped']}" + (f"  by {info['by']}" if info.get("by") else "") if info.get("stamped") else ""
    return [line for line in (f"Supplier: {supplier}" if supplier else "", dates, stamped) if line]


def labels_pdf(labels: list[dict]) -> bytes:
    """One 75 x 50 mm page per label: QR, the readable facts, a bold use-by band and the lot code."""
    buf = io.BytesIO()
    page = canvas.Canvas(buf, pagesize=LABEL)
    for info in labels:
        side, size = 3 * mm, 21 * mm
        widget = qr.QrCodeWidget(info["code"], barLevel="M")
        x0, y0, x1, y1 = widget.getBounds()
        drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
        drawing.add(widget)
        renderPDF.draw(drawing, page, side, LABEL[1] - side - size)
        page.setFillColor(colors.black)
        page.setFont("Helvetica", 6.5)
        for n, line in enumerate(_fit(info.get("condition") or "", "Helvetica", 6.5, size + 2 * mm, 2)):
            page.drawString(side, LABEL[1] - side - size - 7 - n * 6.8, line)

        left = 29 * mm
        width = LABEL[0] - left - side
        y = LABEL[1] - 6 * mm
        page.setFont("Helvetica-Bold", 10)
        for line in _fit(info["item"], "Helvetica-Bold", 10, width, 2):
            page.drawString(left, y, line)
            y -= 11.5
        page.setFont("Helvetica", 7.2)
        for line in _fit(info.get("detail") or "", "Helvetica", 7.2, width, 2):
            page.drawString(left, y, line)
            y -= 8.6

        page.setFont("Helvetica", 7.4)
        y = 18.3 * mm
        for line in _facts(info):
            for part in _fit(line, "Helvetica", 7.4, LABEL[0] - 2 * side, 1):
                page.drawString(side, y, part)
            y -= 8.2

        band_y, band_h = 6.6 * mm, 5.6 * mm
        page.rect(side, band_y, LABEL[0] - 2 * side, band_h, stroke=0, fill=1)
        page.setFillColor(colors.white)
        page.setFont("Helvetica-Bold", 12)
        page.drawCentredString(LABEL[0] / 2, band_y + 1.6 * mm, f"USE BY {info['use_by']}" if info.get("use_by") else "NO USE-BY SET")
        page.setFillColor(colors.black)
        page.setFont("Helvetica-Bold", 12.5)
        page.drawCentredString(LABEL[0] / 2, 2.2 * mm, info["code"])
        page.showPage()
    page.save()
    return buf.getvalue()


def _zpl_text(text: str) -> str:
    return text.replace("^", " ").replace("~", " ")


def labels_zpl(labels: list[dict], dpi: int = 203) -> str:
    """The same label in Zebra's own language, sized for the given printer resolution."""
    dot = dpi / 25.4
    width, height = round(LABEL_W_MM * dot), round(LABEL_H_MM * dot)
    side = round(3 * dot)
    magnification = max(2, int(21 * dot / 29))
    full = width - 2 * side
    out = []
    for info in labels:
        left = round(29 * dot)
        block = width - left - side
        small, big = round(2.6 * dot), round(3.6 * dot)
        facts = _facts(info)
        out += ["^XA", f"^PW{width}", f"^LL{height}", "^LH0,0", "^CI28",
                f"^FO{side},{side}^BQN,2,{magnification}^FDMA,{_zpl_text(info['code'])}^FS",
                f"^FO{side},{round(25 * dot)}^A0N,{round(2.3 * dot)},{round(2.3 * dot)}^FB{round(23 * dot)},2,0,L^FD{_zpl_text(info.get('condition') or '')}^FS",
                f"^FO{left},{side}^A0N,{big},{big}^FB{block},2,0,L^FD{_zpl_text(info['item'])}^FS",
                f"^FO{left},{side + 2 * big + round(1.2 * dot)}^A0N,{small},{small}^FB{block},2,0,L^FD{_zpl_text(info.get('detail') or '')}^FS"]
        for n, line in enumerate(facts):
            out.append(f"^FO{side},{round((29.8 + n * 2.9) * dot)}^A0N,{small},{small}^FB{full},1,0,L^FD{_zpl_text(line)}^FS")
        out += [f"^FO{side},{round(37.8 * dot)}^GB{full},{round(5.6 * dot)},{round(5.6 * dot)}^FS",
                f"^FO{side},{round(38.9 * dot)}^A0N,{round(3.6 * dot)},{round(3.6 * dot)}^FB{full},1,0,C^FR^FD"
                f"{_zpl_text('USE BY ' + info['use_by'] if info.get('use_by') else 'NO USE-BY SET')}^FS",
                f"^FO{side},{round(43.6 * dot)}^A0N,{round(4.2 * dot)},{round(4.2 * dot)}^FB{full},1,0,C^FD{_zpl_text(info['code'])}^FS",
                "^XZ"]
    return "\n".join(out) + "\n"
