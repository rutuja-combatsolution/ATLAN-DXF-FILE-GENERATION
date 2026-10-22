# page1.py - Sheet 1: general arrangement.
#
# Right-hand column, top to bottom: tank storage capacity, parts list, site level
# confirmation, notes, approval stamp. The blocks are scaled up to fill the full column
# height and spaced evenly, so no empty band is left under the tables.
#
# Plan and front elevation are drawn at ONE scale in the area left of that column - the
# scale shrinks until every dimension and callout fits, so a long tank can never run into
# the column. Normally the elevation sits below the plan (spare height shared evenly above the
# plan, between plan and elevation, and below the elevation); a tall narrow tank, where that
# leaves too little room, puts the elevation to the right of the plan instead - whichever
# layout gives the larger scale wins.

import io

from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import black
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

from data_mapper import fmt_rl
from Internal.plan_view import draw_plan_view, plan_margins, FN, FB
from Internal.elevation_view import (draw_elevation_view, left_need, elev_base, right_need,
                                      ELEV_ABOVE)

PW, PH = landscape(A3)
IM = 10 * mm
IX0, IX1 = IM, PW - IM
IY0, IY1 = IM, PH - IM
TB_TOP = IY0 + 45 * mm                      # top of the title block
TBAR_TOP = TB_TOP + 6 * mm                  # top of the tolerance bar

NOTES = ["NOTES:",
         "1. THE EXCAVATION MUST HAVE A MINIMUM OF",
         "    500mm CLEARANCE AROUND THE ENTIRETY OF THE TANK OR",
         "    AS REQUIRED ON-SITE.",
         "2. ACCESS MANHOLES Ø375 ROUND LIDS - CLASS 'D' (BY ATLAN)",
         "    Ø300 PVC RISERS (BY OTHERS)."]

RIGHT_W = 276                       # width of the right-hand column
RIGHT_X = IX1 - 8 - RIGHT_W         # its left edge
LIMIT = RIGHT_X - 8                 # plan + elevation, labels included, stay left of this

COL_TOP = IY1 - 10                  # column spans from here ...
COL_BOTTOM = TB_TOP + 5             # ... down to the stamp's bottom edge
KMAX = 1.4                          # largest enlargement of the column blocks
GAP_MIN = 14


# ----------------------------------------------------------------------------------
# COLUMN BLOCKS  (k = enlargement factor, 1.0 = compact)
# ----------------------------------------------------------------------------------

def _notes_fs():
    return min(9.5, (RIGHT_W - 4) / max(stringWidth(t, FN, 1) for t in NOTES))


def _notes_h(k):
    fs = _notes_fs()
    return fs + (len(NOTES) - 1) * fs * 1.28 * k + 3


def _notes(c, x, top, k):
    fs = _notes_fs()
    lead = fs * 1.28 * k
    c.setFillColor(black)
    for i, t in enumerate(NOTES):
        c.setFont(FB if i == 0 else FN, fs)
        c.drawString(x + 2, top - fs - i * lead, t)


def _capacity_h(k):
    return 19 * k


def _capacity_box(c, x, top, text, k):
    """Boxed heading across the column width; text shrinks to fit."""
    h = _capacity_h(k)
    fs = min(13.0 * min(k, 1.2), (RIGHT_W - 8) / stringWidth(text, FN, 1))
    c.setStrokeColor(black)
    c.setLineWidth(0.8)
    c.rect(x, top - h, RIGHT_W, h, stroke=1, fill=0)
    c.setFont(FN, fs)
    c.setFillColor(black)
    c.drawCentredString(x + RIGHT_W / 2, top - h / 2 - fs * 0.35, text)


def _parts_h(n, k):
    return (16 + 13 + max(n, 1) * 12.5) * k


def _parts_list(c, x, top, rows, k):
    w = RIGHT_W
    props = [0.10, 0.63, 0.10, 0.17]
    ws = [w * p for p in props]
    xs = [x]
    for cw in ws[:-1]:
        xs.append(xs[-1] + cw)
    title_h, hdr_h, row_h = 16 * k, 13 * k, 12.5 * k
    # text size: bigger with k, but the longest description must fit its column
    fs = 8.0 * min(k, 1.15)
    longest = max((stringWidth(r[1], FN, 1) for r in rows), default=0)
    if longest:
        fs = min(fs, (ws[1] - 6) / longest)
    fs_hdr = min(8.0 * min(k, 1.15), fs + 0.5)
    h = _parts_h(len(rows), k)
    bot = top - h

    c.setStrokeColor(black)
    c.setFillColor(black)
    c.setLineWidth(1.2)
    c.rect(x, bot, w, h, stroke=1, fill=0)
    c.setLineWidth(0.5)
    c.line(x, top - title_h, x + w, top - title_h)
    c.line(x, top - title_h - hdr_h, x + w, top - title_h - hdr_h)
    for i in range(1, len(rows)):
        yy = top - title_h - hdr_h - i * row_h
        c.line(x, yy, x + w, yy)
    for cx in xs[1:]:
        c.line(cx, bot, cx, top - title_h)

    c.setFont(FN, fs_hdr)
    c.drawCentredString(x + w / 2, top - title_h / 2 - fs_hdr * 0.35, "PARTS LIST")
    for hdr, cx, cw in zip(["ITEM", "DESCRIPTION", "QTY", "REMARKS"], xs, ws):
        c.drawCentredString(cx + cw / 2, top - title_h - hdr_h / 2 - fs_hdr * 0.35, hdr)
    c.setFont(FN, fs)
    for i, (item, desc, qty, rem) in enumerate(rows):
        base = top - title_h - hdr_h - (i + 0.5) * row_h - fs * 0.35
        c.drawCentredString(xs[0] + ws[0] / 2, base, item)
        c.drawString(xs[1] + 3, base, desc)
        c.drawCentredString(xs[2] + ws[2] / 2, base, qty)
        if rem:
            c.drawString(xs[3] + 3, base, rem)


def _site_h(k):
    return (22 + 7 * 15) * k


def _site_level(c, x, top, d, k):
    w = RIGHT_W
    title_h, row_h = 22 * k, 15 * k
    h = _site_h(k)
    bot = top - h
    c.setStrokeColor(black)
    c.setFillColor(black)
    c.setLineWidth(1.4)
    c.rect(x, bot, w, h, stroke=1, fill=0)
    c.setLineWidth(0.5)
    t_bot = top - title_h
    c.line(x, t_bot, x + w, t_bot)
    for i in range(1, 7):
        c.line(x, t_bot - i * row_h, x + w, t_bot - i * row_h)
    div = x + w * 0.58                       # value column wide enough for two or three inverts
    foot_div = x + w * 0.30
    c.line(div, t_bot, div, t_bot - 4 * row_h)
    c.line(foot_div, bot, foot_div, t_bot - 4 * row_h)

    fs_t = 11 * min(k, 1.2)
    c.setFont(FB, fs_t)
    c.drawCentredString(x + w / 2, top - title_h / 2 - fs_t * 0.35, "Site Level Confirmation")

    def rl(kind):   # every distinct invert of that kind, highest first; bare "RL:" when the tank has none
        ils = sorted({p["il"] for p in d["pipes"] if p["kind"] == kind}, reverse=True)
        return "RL: " + " / ".join(fmt_rl(v) for v in ils) if ils else "RL:"

    rows = [("Finished Surface Level (FSL)", f"RL: {fmt_rl(d['fsl'])}", "l"),
            ("Access Cover Thickness", f"{d['access_cover']:g} mm" if d["access_cover"] else "mm", "r"),
            ("Inlet Invert Level", rl("INLET"), "l"), ("Outlet Invert Level", rl("OUTLET"), "l")]
    fs = min(8.5 * min(k, 1.15),
             (div - x - 8) / max(stringWidth(r[0], FN, 1) for r in rows))
    for i, (lbl, val, al) in enumerate(rows):
        c.setFont(FN, fs)
        yy = t_bot - (i + 0.5) * row_h - fs * 0.35
        c.drawRightString(div - 3, yy, lbl)
        if al == "l":
            c.setFont(FN, min(fs, (x + w - div - 6) / stringWidth(val, FN, 1)))   # shrink to the cell
            c.drawString(div + 3, yy, val)
        else:
            c.drawRightString(x + w - 3, yy, val)
    for i, lbl in enumerate(["Company:", "Name:", "Date:"]):
        c.drawString(x + 3, t_bot - (4 + i + 0.5) * row_h - fs * 0.35, lbl)


def _stamp_h(k):
    return 32 * min(k, 1.25)


def _stamp(c, x, y, w, k):
    h = _stamp_h(k)
    fs = 15 * min(k, 1.25)
    red = colors.Color(0.85, 0.1, 0.1)
    c.saveState()                                # keeps the outline text mode from leaking
    c.setStrokeColor(red)
    c.setLineWidth(2)
    c.roundRect(x, y, w, h, 7, stroke=1, fill=0)
    t = c.beginText()
    t.setFont(FB, fs)
    t.setTextRenderMode(1)                       # outline letters
    c.setLineWidth(0.8)
    txt = "ISSUE FOR APPROVAL"
    t.setTextOrigin(x + (w - stringWidth(txt, FB, fs)) / 2, y + h - fs - 3)
    t.textOut(txt)
    c.drawText(t)
    c.restoreState()

    c.saveState()
    c.setFillColor(red)
    c.setFont(FB, 7.5 * min(k, 1.25))
    c.drawCentredString(x + w / 2, y + 6, "NOT FOR CONSTRUCTION")
    c.restoreState()


def _draw_column(c, d):
    """Draw the right-hand column, scaled to span COL_TOP .. COL_BOTTOM."""
    n = len(d["parts_list"])
    avail = COL_TOP - COL_BOTTOM - 4 * GAP_MIN
    # heights are linear in k apart from the fixed part of the notes block
    fs = _notes_fs()
    fixed = fs + 3
    per_k = 19 + (len(NOTES) - 1) * fs * 1.28 + (29 + 12.5 * max(n, 1)) + (22 + 105) + 32
    k = max(1.0, min(KMAX, (avail - fixed) / per_k))
    gap = (COL_TOP - COL_BOTTOM - (_capacity_h(k) + _notes_h(k) + _parts_h(n, k)
                                   + _site_h(k) + _stamp_h(k))) / 4
    gap = min(gap, 60)

    y = COL_TOP
    _capacity_box(c, RIGHT_X, y, f"TANK STORAGE CAPACITY: {d['tank_storage']:g}m3", k)
    y -= _capacity_h(k) + gap
    _parts_list(c, RIGHT_X, y, d["parts_list"], k)
    y -= _parts_h(n, k) + gap
    _site_level(c, RIGHT_X, y, d, k)
    y -= _site_h(k) + gap
    _notes(c, RIGHT_X, y, k)                    # plain text goes after the three tables
    # stamp keeps the bottom of the column, just above the title block
    sw = min(RIGHT_W, 232)
    _stamp(c, RIGHT_X + (RIGHT_W - sw) / 2, COL_BOTTOM, sw, k)


# ----------------------------------------------------------------------------------
# SCALE / LAYOUT
# ----------------------------------------------------------------------------------

def _x_extent(d, s, l, r):
    """(offset of module left from region left, total width) for scale s."""
    ex = max(525 * s, 12)
    off = max(l + ex, left_need(d))             # plan margin, or the elevation's dimension columns
    return off, off + d["length"] * s + ex + r


def _scale(d, left, top, bottom):
    """Largest common plan/elevation scale (pt per mm) that fits left of the column."""
    l, r, t, b = plan_margins(d)
    s = (LIMIT - left) / (d["length"] + 2 * 525)
    for _ in range(4):                          # width depends on s through the red offset
        off, _w = _x_extent(d, s, l, r)
        ex = max(525 * s, 12)
        s = min((LIMIT - left - off - ex - r) / d["length"],
                (LIMIT - left - off - right_need(d)) / d["length"])
    avail = top - bottom - t - b
    s_fixed = (avail - elev_base(d) - ELEV_ABOVE) / (d["exc_width"] + d["stack_h"])
    s_cover = (avail - elev_base(d) - 44) / (d["exc_width"] + d["stack_h"] + d["cover"])
    return min(s, s_fixed, s_cover)


def _measure_elev(d, s):
    """(room above top of storage, room left of the tank, room right of it) in pt that the front
    elevation really takes at scale s, found by drawing it once on a scratch canvas: on a narrow tank
    its callouts stack upward and sprawl sideways, outgrowing any fixed allowance."""
    m = draw_elevation_view(Canvas(io.BytesIO()), d, 0, 0, s, view="front")
    return (max(m["used_top"] - d["stack_h"] * s, ELEV_ABOVE, d["cover"] * s + 44),
            max(left_need(d), -m["used_x"][0]),
            max(right_need(d), m["used_x"][1] - d["length"] * s))


def _plan_h(d, s):
    l, r, t, b = plan_margins(d)
    return t + d["width"] * s + 2 * max(525 * s, 12) + b


def _stack_scale(d, left, top, bottom):
    """Scale when the plan sits above the elevation: _scale() with the elevation's real height."""
    s = _scale(d, left, top, bottom)
    fits = lambda s: (_plan_h(d, s) + elev_base(d) + d["stack_h"] * s + _measure_elev(d, s)[0]
                      <= top - bottom + 0.5)
    if fits(s):
        return s
    lo, hi = 0.0, s
    for _ in range(14):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def _side_scale(d, left, top, bottom, floor=0.0, gap=10):
    """Scale when the elevation sits right of the plan: the plan may use the full height, but both
    views' margins (callouts, dimensions) now share the sheet width. An estimate first; only when it
    could beat `floor` (the stacked scale) is it refined against the elevation's measured size."""
    l, r, t, b = plan_margins(d)
    avail, width = top - bottom, LIMIT - left
    s = 0.01
    for _ in range(6):                                  # the red offset depends on s
        ex = max(525 * s, 12)
        s = min((avail - t - b - 2 * ex) / d["width"],
                (width - gap - l - r - 2 * ex - left_need(d) - right_need(d)) / (2 * d["length"]),
                (avail - elev_base(d) - 44) / (d["stack_h"] + d["cover"]))
    if s <= floor:
        return s

    def fits(s):
        above, nl, nr = _measure_elev(d, s)
        return (l + 2 * max(525 * s, 12) + d["length"] * s + r + gap + nl + d["length"] * s + nr <= width
                and elev_base(d) + d["stack_h"] * s + above <= avail)
    if fits(s):
        return s
    lo, hi = 0.0, s
    for _ in range(12):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def draw_page1(c, d):
    bottom = TBAR_TOP + 6
    left = IX0 + 6
    top = IY1 - 6                                         # whole left area is free for the drawings
    s_stack = _stack_scale(d, left, top, bottom)
    s_side = _side_scale(d, left, top, bottom, floor=s_stack)
    side = s_side > s_stack     # tall narrow tank: stacking leaves no room, so go side by side
    s = s_side if side else s_stack

    _draw_column(c, d)

    l, r, t, b = plan_margins(d)
    ex = max(525 * s, 12)
    plan_h = _plan_h(d, s)
    above, need_l, need_r = _measure_elev(d, s)
    elev_h = elev_base(d) + d["stack_h"] * s + above

    if side:   # plan left, elevation right, both centred on the sheet's free height
        plan_w = l + 2 * ex + d["length"] * s + r
        elev_w = need_l + d["length"] * s + need_r
        pad = max((LIMIT - left - plan_w - elev_w) / 3, 0)
        cy = (top + bottom) / 2
        mx = left + pad + l + ex
        my = cy - plan_h / 2 + b + ex
        draw_plan_view(c, d, mx, my, s)
        draw_elevation_view(c, d, left + pad + plan_w + pad + need_l,
                            cy - elev_h / 2 + elev_base(d), s, view="front")
        return

    # --- plan + elevation, one scale; spare height shared in three equal gaps -------------
    gap3 = max((top - bottom) - plan_h - elev_h, 0) / 3   # above plan / between / below elevation
    off, _w = _x_extent(d, s, l, r)
    block_w = off + d["length"] * s + max(ex + r, need_r)
    mx = left + max((LIMIT - left - block_w) / 2, 0) + off   # module left edge; block centred in the free width
    my = top - gap3 - t - ex - d["width"] * s            # module bottom edge
    ey = bottom + gap3 + elev_base(d)                    # elevation base
    elev_top = ey + d["stack_h"] * s + above
    draw_plan_view(c, d, mx, my, s, floor_y=elev_top + 2)
    draw_elevation_view(c, d, mx, ey, s, view="front")
