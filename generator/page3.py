# page3.py - Sheet 2: trench cross-section (static image chosen by layer count)
# with the backfill / bedding specification text underneath.

import os

from reportlab.lib.colors import black
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader

PW, PH = landscape(A3)
IM = 10 * mm
IX0, IX1 = IM, PW - IM
IW = IX1 - IX0
IY1 = PH - IM
TBAR_TOP = IM + 45 * mm + 6 * mm

FN, FB = "Helvetica", "Helvetica-Bold"

FS_HDR, FS_BODY, LEAD, SEC_GAP = 10, 9.5, 12.3, 9

LEFT_SECTIONS = [
    ("FINAL BACKFILL", [
        "Depth: 500mm minimum",
        "Compaction: To 95% MDD minimum - Compact in 100mm layers",
        "Material Shape: Angular",
        "Size: Not larger than 20mm diameter",
        "Consistency: Free of lumps, debris and sharp objects that could puncture the geotextile",
        "Applicability: Stone, road-base or compacted granular material (non-cohesive) is acceptable "
        "if it meets these requirements. In NO case shall clays/cohesive soils be used. Ensure that "
        "any site specifications are considered for pavement make-up",
    ]),
    ("INITIAL BACKFILL", [
        "Depth: 100mm",
        "Compaction: 300kg Walk Behind Reversible Compactor",
        "Material Shape: Sand or crushed rock",
        "Size: Not larger than 20mm diameter",
        "Consistency: Free of lumps, debris and sharp objects that could puncture the geotextile",
        "Applicability: Clean washed Sand with no clay or foreign particles. In NO case shall "
        "clays/cohesive soils be used",
    ]),
]

RIGHT_SECTIONS = [
    ("SIDES BACKFILL", [
        "Width: 500-600mm (each side) or as required onsite",
        "Compaction: To 95% MDD minimum - Compact in layers",
        "Material Shape: Angular",
        "Size: Not larger than 20mm diameter",
        "Consistency: Free of lumps, debris and sharp objects that could puncture the geotextile",
        "Applicability: Stone or sand is acceptable if it meets these requirements. In NO case "
        "shall clays/cohesive soils be used",
    ]),
    ("BASE / BEDDING", [
        "Depth: 50mm-100mm",
        "Compaction: To 95% MDD minimum",
        "Material Shape: Angular",
        "Size: Not larger than 20mm diameter",
        "Consistency: Free of lumps, debris and sharp objects that could puncture the geotextile",
        "Applicability: Stone or sand is acceptable if it meets these requirements. In NO case "
        "shall clays/cohesive soils be used",
    ]),
    ("SUBGRADE", ["Compaction: To 100kPa"]),
]


def _wrap(text, font, size, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if stringWidth(test, font, size) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def draw_page2(c, image_path):
    """Cross-section image across the top, specification text in two columns below."""
    top = IY1 - 5 * mm
    img_w, img_h = IW * 0.95, (IY1 - TBAR_TOP) * 0.56
    if os.path.isfile(image_path):
        iw, ih = ImageReader(image_path).getSize()
        k = min(img_w / iw, img_h / ih)
        img_w, img_h = iw * k, ih * k
        c.drawImage(image_path, IX0 + (IW - img_w) / 2, top - img_h, width=img_w, height=img_h,
                    mask="auto")
    else:
        img_h = 0

    text_top = top - img_h - 18
    floor = TBAR_TOP + 4
    left_x = IX0 + 37
    right_x = IX0 + IW * 0.55
    left_w = right_x - left_x - 20
    right_w = IX1 - right_x - 24

    def column(x, sections, width, y):
        for hdr, lines in sections:
            c.setFont(FB, FS_HDR)
            c.setFillColor(black)
            c.drawString(x, y, hdr)
            y -= LEAD + 1
            c.setFont(FN, FS_BODY)
            for entry in lines:
                for wl in _wrap(entry, FN, FS_BODY, width):
                    if y < floor:
                        return
                    c.drawString(x, y, wl)
                    y -= LEAD
            y -= SEC_GAP

    column(left_x, LEFT_SECTIONS, left_w, text_top)
    column(right_x, RIGHT_SECTIONS, right_w, text_top)
