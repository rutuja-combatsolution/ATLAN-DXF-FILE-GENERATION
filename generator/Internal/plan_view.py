# ==========================================================
# plan_view.py
# Plan view of the tank + the drawing-annotation helpers
# (dimensions, leader callouts, underlined titles) shared by
# the elevation view.
#
# All model sizes are millimetres; `s` is points per millimetre.
# ==========================================================

from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth

FN, FB = "Helvetica", "Helvetica-Bold"
DARK_RED = colors.Color(0.5, 0, 0)
CUBE_GREY = 0.6

EXC_MARGIN_MM = 525        # excavation edge beyond the module (500 + 25)
PIPE_STUB = 22             # pipe stub outside the module edge, pt
ARROW_OUT = 36             # pipe stub + flow arrow, measured beyond the red border


# ==========================================================
# SMALL DRAWING HELPERS
# ==========================================================

def arrowhead(c, x, y, direction, size=4.5):
    """Filled arrowhead, tip at (x, y), pointing r / l / u / d."""
    dx, dy = {"r": (1, 0), "l": (-1, 0), "u": (0, 1), "d": (0, -1)}[direction]
    bx, by = x - dx * size, y - dy * size
    px, py = -dy * size * 0.35, dx * size * 0.35
    p = c.beginPath()
    p.moveTo(x, y)
    p.lineTo(bx + px, by + py)
    p.lineTo(bx - px, by - py)
    p.close()
    c.setFillColor(colors.black)
    c.drawPath(p, stroke=0, fill=1)


def draw_flow_arrow(c, center_x, center_y, side, flow_type, pipe_extension=18):
    """Hollow flow arrow beyond a pipe stub. INLET (red) points into the tank, OUTLET (blue) away."""
    side = {"TOP": "NORTH", "BOTTOM": "SOUTH", "LEFT": "WEST", "RIGHT": "EAST"}.get(
        side.upper(), side.upper())
    flow_type = flow_type.upper()

    c.setStrokeColor(colors.red if flow_type == "INLET" else colors.blue)
    c.setLineWidth(0.8)

    GAP, LEN, HALF, SHAFT, TIP = 6, 18, 4.5, 5, 2.5
    near_d = pipe_extension + GAP
    far_d = near_d + LEN

    if side in ("EAST", "WEST"):
        dx = 1 if side == "EAST" else -1
        near, far = center_x + dx * near_d, center_x + dx * far_d
        tip, back = (near, far) if flow_type == "INLET" else (far, near)
        sgn = 1 if tip > back else -1
        c.line(back - sgn * SHAFT, center_y, tip + sgn * TIP, center_y)
        c.line(back, center_y + HALF, tip, center_y)
        c.line(back, center_y - HALF, tip, center_y)
        c.line(back, center_y - HALF, back, center_y + HALF)
    else:
        dy = 1 if side == "NORTH" else -1
        near, far = center_y + dy * near_d, center_y + dy * far_d
        tip, back = (near, far) if flow_type == "INLET" else (far, near)
        sgn = 1 if tip > back else -1
        c.line(center_x, back - sgn * SHAFT, center_x, tip + sgn * TIP)
        c.line(center_x - HALF, back, center_x, tip)
        c.line(center_x + HALF, back, center_x, tip)
        c.line(center_x - HALF, back, center_x + HALF, back)

    c.setStrokeColor(colors.black)
    c.setLineWidth(1)


def underlined_title(c, text, cx, y, size=11):
    c.setFont(FB, size)
    c.setFillColor(colors.black)
    c.drawCentredString(cx, y, text)
    w = stringWidth(text, FB, size)
    c.setLineWidth(0.9)
    c.line(cx - w / 2, y - 2.5, cx + w / 2, y - 2.5)


def text_block(c, x, y, lines, size=7.5, align="l", leading=None, bold_last=False):
    """Draw lines from baseline y downwards; align l / r / c about x. Returns (x0, y0, x1, y1) box."""
    leading = leading or size * 1.15
    w = max(stringWidth(t, FN, size) for t in lines)
    for i, t in enumerate(lines):
        font = FB if (bold_last and i == len(lines) - 1) else FN
        c.setFont(font, size)
        c.setFillColor(colors.black)
        yy = y - i * leading
        if align == "r":
            c.drawRightString(x, yy, t)
        elif align == "c":
            c.drawCentredString(x, yy, t)
        else:
            c.drawString(x, yy, t)
    x0 = {"l": x, "r": x - w, "c": x - w / 2}[align]
    return (x0, y - (len(lines) - 1) * leading - size * 0.25, x0 + w, y + size * 0.85)


def leader(c, x0, y0, ax, ay):
    """Thin leader from text edge (x0, y0) to anchor (ax, ay) with a short landing."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    land = 5 if ax >= x0 else -5
    c.line(x0, y0, x0 + land, y0)
    c.line(x0 + land, y0, ax, ay)


def _fit_label(text, span, size=5.0, max_lines=3, min_size=4.0):
    """(lines, font size) that fit inside `span` pt, or None (the caller then leaves the label out).
    `text` is a string, or a list of alternatives from fullest to shortest: the first one that fits
    is used, so a small tank gets "STACK" where a big one gets "SINGLE STACK (1000L)"."""
    for alt in ([text] if isinstance(text, str) else text):
        fit = _fit_one(alt, span, size, max_lines, min_size)
        if fit:
            return fit
    return None


def _fit_one(text, span, size, max_lines, min_size):
    """One line if it fits by shrinking a little, else wrapped at spaces to at most max_lines lines."""
    words = text.split()
    sz = size
    while sz >= min_size - 1e-6:
        if stringWidth(text, FN, sz) <= span:
            return [text], sz
        sz -= 0.25
    sz = size
    while sz >= min_size - 1e-6:
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if not cur or stringWidth(t, FN, sz) <= span:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= max_lines and all(stringWidth(t, FN, sz) <= span for t in lines):
            return lines, sz
        sz -= 0.25
    return None


def dim_h(c, x1, x2, y, value, label=None, ext_to=None, narrow=None, size=8,
          text_right=False, arrow=4.5, skip_short=False, fit_label=False, value_above=False):
    """Horizontal dimension. value above the line, label (small) below. ext_to = y of the feature.

    narrow = ("MIN.", "500"): arrows sit outside the extension lines and the text
    goes left of x1 (or right of x2 when text_right). A segment too short for its
    value gets the outside-arrow form; skip_short drops its text (chain dimensions).
    fit_label: a label longer than the dimension wraps to fit between the extension lines
    (left out if it cannot) instead of running across them.
    value_above: a segment too short for its value keeps the value centred above the line
    instead of to the right of it (where a neighbouring dimension's text may be).
    """
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    if ext_to is not None:
        sg = 1 if y > ext_to else -1
        for xe in (x1, x2):
            c.line(xe, ext_to, xe, y + sg * 3)
    tw_ = stringWidth(value or "", FN, size)
    if narrow or (x2 - x1) < max(2 * arrow + 3, tw_ + 2 * arrow + 3):
        c.line(x1 - 9, y, x1, y)
        c.line(x2, y, x2 + 9, y)
        arrowhead(c, x1, y, "r", arrow)
        arrowhead(c, x2, y, "l", arrow)
        c.setFont(FN, size)
        c.setFillColor(colors.black)
        if narrow:
            put = c.drawString if text_right else c.drawRightString
            tx = x2 + 11 if text_right else x1 - 11
            put(tx, y + 2, narrow[0])
            put(tx, y - size, narrow[1])
        elif value and not skip_short:
            if value_above:
                c.drawCentredString((x1 + x2) / 2, y + 2.5, value)
            else:
                c.drawString(x2 + 11, y - size / 2.5, value)
        return
    c.line(x1, y, x2, y)
    arrowhead(c, x1, y, "l", arrow)
    arrowhead(c, x2, y, "r", arrow)
    c.setFillColor(colors.black)
    c.setFont(FN, size)
    c.drawCentredString((x1 + x2) / 2, y + 2.5, value)
    if label:
        fit = _fit_label(label, x2 - x1 - 4) if fit_label else ([label], 5)
        if fit:
            lines, fs = fit
            c.setFont(FN, fs)
            for k, t in enumerate(lines):
                c.drawCentredString((x1 + x2) / 2, y - (6.5 if len(lines) == 1 else 6.0) - k * (fs + 0.6), t)


def _clear_runs(y1, y2, cross, pad=2.5):
    """Stretches of a vertical dimension (y1..y2) that no line crosses: [(centre offset from the middle,
    usable length)], longest first. `cross` = y of lines that run across the dimension."""
    ys = [y1] + sorted(y for y in (cross or []) if y1 < y < y2) + [y2]
    runs = [((a + b) / 2 - (y1 + y2) / 2, b - a - 2 * pad) for a, b in zip(ys, ys[1:])]
    return sorted(runs, key=lambda r: -r[1])


def dim_v(c, x, y1, y2, value, label=None, ext_to=None, narrow=None, size=8,
          narrow_below=False, arrow=4.5, skip_short=False, fit_label=False, label_lines=3, cross=None):
    """Vertical dimension (y1 < y2). value/label are rotated and sit left of the line.

    narrow = "MIN. 500": arrows sit outside the extension lines; text above y2,
    or below y1 when narrow_below. Short segments behave as in dim_h.
    fit_label: as in dim_h - a label longer than the dimension shrinks / wraps (up to label_lines lines,
    stacked to the left) or, given as a list of alternatives, falls back to a shorter wording.
    cross: y of other lines that run across this dimension (the extension lines of dimensions further out):
    the label is fitted into the longest stretch they leave, and the value moves off any of them.
    """
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    if ext_to is not None:
        sg = 1 if x > ext_to else -1
        for ye in (y1, y2):
            c.line(ext_to, ye, x + sg * 3, ye)
    tw_ = stringWidth(value or "", FN, size)
    if narrow or (y2 - y1) < max(2 * arrow + 3, tw_ + 2 * arrow + 3):
        c.line(x, y1 - 9, x, y1)
        c.line(x, y2, x, y2 + 9)
        arrowhead(c, x, y1, "u", arrow)
        arrowhead(c, x, y2, "d", arrow)
        if narrow:
            c.saveState()
            c.translate(x - 2.5, (y1 - 11) if narrow_below else (y2 + 11))
            c.rotate(90)
            c.setFont(FN, size)
            c.setFillColor(colors.black)
            (c.drawRightString if narrow_below else c.drawString)(0, 0, narrow)
            c.restoreState()
        elif value and not skip_short:                    # value to the right of the line, centred
            c.saveState()
            c.translate(x + 10, (y1 + y2) / 2)
            c.rotate(90)
            c.setFont(FN, size)
            c.setFillColor(colors.black)
            c.drawCentredString(0, 0, value)
            c.restoreState()
        return
    c.line(x, y1, x, y2)
    arrowhead(c, x, y1, "d", arrow)
    arrowhead(c, x, y2, "u", arrow)
    runs = _clear_runs(y1, y2, cross)
    vshift = 0.0
    if cross and any(abs(yc - (y1 + y2) / 2) < tw_ / 2 + 2 for yc in cross):   # a line would cross the value
        roomy = [r for r in runs if r[1] >= tw_]
        if roomy:
            vshift = roomy[0][0]
    c.saveState()
    c.translate(x - 2.5, (y1 + y2) / 2)
    c.rotate(90)
    c.setFillColor(colors.black)
    c.setFont(FN, size)
    c.drawCentredString(vshift, 0, value)
    if label:
        fit = (_fit_label(label, runs[0][1], max_lines=label_lines) if fit_label
               else ([label if isinstance(label, str) else label[0]], 5))
        if fit:
            lines, fs = fit
            c.setFont(FN, fs)
            for k, t in enumerate(lines):
                c.drawCentredString(runs[0][0] if fit_label else 0, 10.5 + k * (fs + 0.6), t)
    c.restoreState()


# ==========================================================
# CUBE GRID
# ==========================================================

CUBE_FORM = "atlancube_plan"


def _define_cube_form(c):
    """One cube as a form in unit coordinates (the line width scales with the cube)."""
    from Internal import cube_plan_art as art

    c.beginForm(CUBE_FORM, -0.05, -0.05, 1.05, 1.05)
    c.setStrokeGray(0)
    c.setLineWidth(art.STROKE)
    c.setLineCap(1)
    c.setLineJoin(1)
    path = c.beginPath()
    for ops in art.PATHS:
        pen = None                                   # current point, to chain connected lines
        for op in ops:
            kind, v = op[0], op[1:]
            if kind == "l":
                if pen is None or abs(pen[0] - v[0]) > 1e-4 or abs(pen[1] - v[1]) > 1e-4:
                    path.moveTo(v[0], v[1])
                path.lineTo(v[2], v[3])
                pen = (v[2], v[3])
            elif kind == "qu":
                path.moveTo(v[0], v[1])
                for i in (2, 4, 6):
                    path.lineTo(v[i], v[i + 1])
                path.close()
                pen = None
            elif kind == "re":
                path.rect(min(v[0], v[2]), min(v[1], v[3]), abs(v[2] - v[0]), abs(v[3] - v[1]))
                pen = None
    c.drawPath(path, stroke=1, fill=0)
    c.endForm()


def draw_panel_grid(c, x, y, w, h, cols, rows):
    """Cube grid in the reference style: grey field, cube art flush to the cube edges."""
    cw, ch = w / cols, h / rows

    c.setFillGray(CUBE_GREY)
    c.rect(x, y, w, h, stroke=0, fill=1)

    if not c.hasForm(CUBE_FORM):
        _define_cube_form(c)
    for col in range(cols):
        for row in range(rows):
            c.saveState()
            c.translate(x + col * cw, y + row * ch)
            c.scale(cw, ch)
            c.doForm(CUBE_FORM)
            c.restoreState()


# ==========================================================
# MARGINS THE PLAN NEEDS AROUND ITS RED BORDER
# ==========================================================

def plan_margins(d):
    sides = {p["side"] for p in d["pipes"]}
    n_bottom = sum(1 for p in d["pipes"] if p["side"] == "bottom")
    left = (ARROW_OUT if "left" in sides else 8) + 36 + 58          # arrows + chain dims + callouts
    right = (ARROW_OUT if "right" in sides else 8) + 78 + (56 if sides - {"left"} else 0)
    top = (ARROW_OUT if "top" in sides else 8) + 46
    bottom = ((ARROW_OUT + 16) if "bottom" in sides else 14) + (48 if "bottom" in sides else 40)
    if n_bottom >= 3:                                   # crowded wall: room for a second callout row
        bottom += 20
    return left, right, top, bottom


# ==========================================================
# PLAN VIEW
# ==========================================================

def _seg_hits_box(p1, p2, box):
    """True when segment p1-p2 touches the axis-aligned box (x0, y0, x1, y1) - Liang-Barsky."""
    x0_, y0_, x1_, y1_ = box
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, p1[0] - x0_), (dx, x1_ - p1[0]), (-dy, p1[1] - y0_), (dy, y1_ - p1[1])):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return False
                t0 = max(t0, t)
            else:
                if t < t0:
                    return False
                t1 = min(t1, t)
    return True


def _round_rect(c, x, y, w, h, r, lw):
    c.setLineWidth(lw)
    c.roundRect(x, y, w, h, r, stroke=1, fill=0)


def _group_pipes(pipes):
    """Pipes sharing a wall position are drawn together (arrows side by side)."""
    groups = []
    for p in pipes:
        for g in groups:
            if g[0]["side"] == p["side"] and abs(g[0]["along"] - p["along"]) < 5:
                g.append(p)
                break
        else:
            groups.append([p])
    return groups


def group_lines(grp):
    """Text of the ONE callout for the pipes on one line (same wall position) - repeats collapse.

    One size/level  -> INLET (or OUTLET, or INLET/OUTLET) / Ø150 PIPE / IL 97.00
    Several         -> each kind as a header, then a line per level listing its diameters:
                       INLET / Ø750 / Ø150  IL 97.00 / OUTLET / Ø150  IL 98.00
    """
    from data_mapper import fmt_rl                      # local import keeps Internal/ standalone-importable
    kinds = [k for k in ("INLET", "OUTLET") if any(p["kind"] == k for p in grp)]
    specs = {(p["diameter"], round(p["il"], 3)) for p in grp}
    if len(specs) == 1:
        (dia, il), = specs
        return ["/".join(kinds), f"Ø{dia:g} PIPE", f"IL {fmt_rl(il)}"]
    lines = []
    for k in kinds:
        by_il = {}
        for p in grp:
            if p["kind"] == k:
                by_il.setdefault(round(p["il"], 3), set()).add(p["diameter"])
        lines.append(k)
        lines += [f"{' / '.join(f'Ø{x:g}' for x in sorted(by_il[il], reverse=True))}  IL {fmt_rl(il)}"
                  for il in sorted(by_il)]
    return lines


STATS = {"masked": 0}          # callouts that found no clear spot (diagnostics / tests)


def draw_plan_view(c, d, x0, y0, s, floor_y=None):
    """x0, y0 = bottom-left of the cube module (pt); s = pt per mm.

    floor_y: lowest y the plan's text may use (the sheet places the elevation below it).
    Returns {"red": (l, b, r, t), "mod": (l, b, r, t), "title_y": y}.
    """
    from data_mapper import fmt_rl                      # local import keeps Internal/ standalone-importable

    L, W = d["length"] * s, d["width"] * s
    gx, gy = x0, y0
    ex = max(EXC_MARGIN_MM * s, 12)                      # red excavation border offset

    mod = (gx, gy, gx + L, gy + W)
    red = (gx - ex, gy - ex, gx + L + ex, gy + W + ex)
    sides = {p["side"] for p in d["pipes"]}

    # ---- cube grid + borders ------------------------------------------------
    draw_panel_grid(c, gx, gy, L, W, d["cubes_long"], d["cubes_wide"])

    c.setStrokeColor(colors.black)
    # two concentric borders with a small corner radius, clear of the square grid corners
    for off in (3.5, 7.5):
        _round_rect(c, gx - off, gy - off, L + 2 * off, W + 2 * off, off - 1, 2.2)

    c.setStrokeColor(DARK_RED)
    c.setLineWidth(1.2)
    c.rect(red[0], red[1], red[2] - red[0], red[3] - red[1], stroke=1, fill=0)
    c.setStrokeColor(colors.black)

    # ---- manholes -----------------------------------------------------------
    # drawn at their true size (square 600x600, circular 300, circular 600 ...); if the
    # scale is so small that the smallest would vanish, all are enlarged by one common
    # factor so the size differences stay visible
    mhs = d["manholes"]
    boost = 1.0
    if mhs:
        smallest = min(min(h["w_mm"], h["h_mm"]) for h in mhs) / 2 * s
        boost = max(1.0, 2.6 / smallest) if smallest > 0 else 1.0
    for mh in mhs:
        mx, my = gx + mh["x"] * s, gy + mh["y"] * s
        hw, hh = mh["w_mm"] / 2 * s * boost, mh["h_mm"] / 2 * s * boost
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.black)
        c.setLineWidth(1)
        if mh["shape"] == "square":
            c.rect(mx - hw, my - hh, 2 * hw, 2 * hh, stroke=1, fill=1)
        else:
            c.circle(mx, my, hw, stroke=1, fill=1)
            if mh["w_mm"] >= 500:                       # large lid: second, inner ring
                c.setLineWidth(0.7)
                c.circle(mx, my, hw * 0.6, stroke=1, fill=0)
            else:                                       # small lid: centre dot
                c.setFillColor(colors.black)
                c.circle(mx, my, max(hw * 0.22, 0.7), stroke=0, fill=1)

    # ---- pipes (stubs + flow arrows) ---------------------------------------
    anchors = []                                         # (group, ax, ay)
    for grp in _group_pipes(d["pipes"]):
        side, along = grp[0]["side"], grp[0]["along"] * s
        c.setFillGray(0.75)
        c.setStrokeColor(colors.black)
        c.setLineWidth(1)
        ph = max(max(q["diameter"] for q in grp) * s, 4)

        if side in ("left", "right"):
            yc = gy + along
            xe = gx if side == "left" else gx + L
            xs = xe - PIPE_STUB if side == "left" else xe
            c.rect(xs, yc - ph / 2, PIPE_STUB, ph, stroke=1, fill=1)
            for k, q in enumerate(grp):
                off = 0 if len(grp) == 1 else (3.5 if k % 2 == 0 else -3.5)
                draw_flow_arrow(c, xe, yc + off, "WEST" if side == "left" else "EAST",
                                q["kind"], pipe_extension=PIPE_STUB)
            anchors.append((grp, xs if side == "left" else xs + PIPE_STUB, yc))
        else:
            xc = gx + along
            ye = gy + W if side == "top" else gy
            ys = ye if side == "top" else ye - PIPE_STUB
            c.rect(xc - ph / 2, ys, ph, PIPE_STUB, stroke=1, fill=1)
            for k, q in enumerate(grp):
                off = 0 if len(grp) == 1 else (3.5 if k % 2 == 0 else -3.5)
                draw_flow_arrow(c, xc + off, ye, "NORTH" if side == "top" else "SOUTH",
                                q["kind"], pipe_extension=PIPE_STUB)
            anchors.append((grp, xc, ys + PIPE_STUB if side == "top" else ys))

    # ---- agg drain stub (standard perimeter drain, bottom-left corner) --------
    c.setFillGray(0.75)
    c.setLineWidth(0.8)
    c.rect(gx - PIPE_STUB + 6, gy + 1.5, PIPE_STUB - 6, 3, stroke=1, fill=1)
    agg_anchor = (gx - PIPE_STUB + 6, gy + 3)

    # ---- centre information box --------------------------------------------
    cap = f"{d['tank_storage']:g}m3"
    info = ["AtlanCube 1000L MODULE",
            f"({d['cubes_wide']}-CUBES ROW x {d['cubes_long']}-CUBES LONG)",
            d["stack_label"],
            f"FSL {fmt_rl(d['fsl'])}",
            f"TOP OF STORAGE RL {fmt_rl(d['top_rl'])}",
            f"TOTAL STORAGE CAPACITY: {cap}"]
    fs, lead = 9, 10.4
    bw = max(stringWidth(t, FN, fs) for t in info) + 8
    bh = lead * len(info) + 3
    bx = gx + L / 2 - bw / 2
    chain_y = red[1] - ((ARROW_OUT + 16) if "bottom" in sides else 14)

    # a narrow tank cannot hold the box: hang it under the dimension chain instead
    narrow_tank = W < bh + 10
    by = (chain_y - 14 - bh) if narrow_tank else (gy + W / 2 - bh / 2)
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.6)
    c.rect(bx, by, bw, bh, stroke=1, fill=1)
    for i, t in enumerate(info):
        c.setFont(FN, fs)
        c.setFillColor(colors.black)
        c.drawCentredString(gx + L / 2, by + bh - lead * (i + 1) + 1.5, t)

    # ---- dimensions: excavation length / module length (top rows) --------------
    top_base = red[3] + (ARROW_OUT if "top" in sides else 8)
    y_mod = top_base + 12
    y_exc = top_base + 32
    dim_h(c, red[0], red[2], y_exc, f"{d['exc_length']:.0f}", "EXCAVATION LENGTH", ext_to=red[3],
          fit_label=True)
    dim_h(c, red[0], mod[0], y_mod, "", narrow=("MIN.", "500"), ext_to=red[3])
    dim_h(c, mod[2], red[2], y_mod, "", narrow=("MIN.", "500"), ext_to=red[3], text_right=True)
    dim_h(c, mod[0], mod[2], y_mod, f"{d['length']:.0f}",
          f"({d['cubes_long']}x) AtlanCube @1150mm 1000L MODULE", ext_to=mod[3] + 7.5, fit_label=True,
          value_above=True)

    # ---- dimensions: module width / excavation width (right columns) ------------
    right_base = red[2] + (ARROW_OUT if "right" in sides else 8)
    x_mod = right_base + 34
    x_exc = right_base + 66
    dim_v(c, x_exc, red[1], red[3], f"{d['exc_width']:.0f}", "EXCAVATION WIDTH", ext_to=red[2],
          fit_label=True)
    dim_v(c, x_mod, mod[1], mod[3], f"{d['width']:.0f}",
          f"({d['cubes_wide']}x) AtlanCube @1150mm 1000L MODULE", ext_to=mod[2] + 7.5, fit_label=True)
    dim_v(c, x_mod, red[1], mod[1], "", narrow="MIN. 500", ext_to=red[2], narrow_below=True)
    dim_v(c, x_mod, mod[3], red[3], "", narrow="MIN. 500", ext_to=red[2])

    # ---- chain dims for positions of pipes / manholes ---------------------------
    xs = {0.0, d["length"]}
    ys = {0.0, d["width"]}
    for p in d["pipes"]:
        (xs if p["side"] in ("top", "bottom") else ys).add(p["along"])
    for m in d["manholes"]:
        xs.add(m["x"])
        ys.add(m["y"])
    xs = sorted(xs)
    ys = sorted(ys)
    if len(xs) > 2:
        for a, b in zip(xs, xs[1:]):
            if b - a > 1:
                dim_h(c, gx + a * s, gx + b * s, chain_y, f"{round((b - a) / 10) * 10:.0f}",
                      ext_to=gy - 7.5, size=6, arrow=3, skip_short=True)
    if len(ys) > 2:
        x_chain = red[0] - (ARROW_OUT if "left" in sides else 8) - 10
        for a, b in zip(ys, ys[1:]):
            if b - a > 1:
                dim_v(c, x_chain, gy + a * s, gy + b * s, f"{round((b - a) / 10) * 10:.0f}",
                      ext_to=gx - 7.5, size=6, arrow=3, skip_short=True)

    # ---- keep-out areas: callout text must never sit on a line or on other text -----------
    # (rectangles x0, y0, x1, y1 in points)
    obst = []

    def keep_out(x0_, y0_, x1_, y1_):
        obst.append((min(x0_, x1_), min(y0_, y1_), max(x0_, x1_), max(y0_, y1_)))

    # pipe stubs + flow arrows
    ARW = PIPE_STUB + 6 + 18 + 3
    for grp, ax, ay in anchors:
        side_ = grp[0]["side"]
        half = max(7.0, max(max(q["diameter"] for q in grp) * s, 4) / 2 + 1.5)   # wide stubs too
        if side_ == "left":
            keep_out(gx - ARW, ay - half, gx, ay + half)
        elif side_ == "right":
            keep_out(gx + L, ay - half, gx + L + ARW, ay + half)
        elif side_ == "top":
            keep_out(ax - half, gy + W, ax + half, gy + W + ARW)
        else:
            keep_out(ax - half, gy - ARW, ax + half, gy)
    keep_out(gx - PIPE_STUB, gy, gx, gy + 6)                          # agg drain stub

    # top dimension rows: extension lines, the lines themselves, the MIN. 500 texts
    for xe, y_to in ((red[0], y_exc + 3), (red[2], y_exc + 3),
                     (mod[0], y_mod + 3), (mod[2], y_mod + 3)):
        keep_out(xe - 0.9, red[3], xe + 0.9, y_to)
    keep_out(red[0] - 10, y_exc - 1, red[2] + 10, y_exc + 11)
    keep_out(red[0] - 36, y_mod - 10, red[2] + 36, y_mod + 12)

    # right-hand width dimensions (lines + rotated texts, incl. the MIN. 500 labels)
    keep_out(x_mod - 14, red[1] - 46, x_exc + 4, red[3] + 46)

    # dimension chains below / left of the module
    if len(xs) > 2:
        for xb in xs:
            keep_out(gx + xb * s - 0.9, chain_y - 3, gx + xb * s + 0.9, gy - 7.5)
        keep_out(gx - 10, chain_y - 1, gx + L + 10, chain_y + 1)
        for a, b in zip(xs, xs[1:]):
            tw_ = stringWidth(f"{round((b - a) / 10) * 10:.0f}", FN, 6)
            if b - a > 1 and (b - a) * s >= tw_ + 9:
                mid = gx + (a + b) / 2 * s
                keep_out(mid - tw_ / 2 - 1, chain_y + 1, mid + tw_ / 2 + 1, chain_y + 10)
    if len(ys) > 2:
        keep_out(x_chain - 14, gy - 10, x_chain + 3, gy + W + 10)
        for yb in ys:
            keep_out(x_chain, gy + yb * s - 0.9, gx - 7.5, gy + yb * s + 0.9)

    # info box when it hangs below a narrow tank, and the PLAN VIEW title
    title_y = (by - 18) if narrow_tank else (chain_y - 34)
    if narrow_tank:
        keep_out(bx, by, bx + bw, by + bh)
    t_w = stringWidth("PLAN VIEW", FB, 11)
    keep_out(gx + L / 2 - t_w / 2 - 2, title_y - 5, gx + L / 2 + t_w / 2 + 2, title_y + 13)
    if floor_y is not None:                                   # nothing may reach into the elevation
        keep_out(-1e6, -1e6, 1e6, floor_y)

    # ---- pipe callouts ----------------------------------------------------------
    placed = []                                          # text boxes already placed
    drawn_leaders = []                                   # leader segments already drawn
    SIZE, LEAD = 7, 8.0

    def free(box):
        if not all(box[2] < o[0] or box[0] > o[2] or box[3] < o[1] or box[1] > o[3]
                   for o in placed + obst):
            return False
        # a new text block must not sit on a leader that is already there
        return not any(_seg_hits_box(a, b, box) for a, b in drawn_leaders)

    col_left = red[0] - (ARROW_OUT if "left" in sides else 8) - 36      # right edge of left text
    col_right = red[2] + (ARROW_OUT if "right" in sides else 8) + 80    # left edge of right text (clear of the width dims)

    def put(lines, anchor, candidates):
        """candidates: (x_edge, align 'l'|'r', y_top). First spot clear of every line and text
        wins; if none is, the text goes on its first spot over a white mask (stays legible)."""
        w = max(stringWidth(t, FN, SIZE) for t in lines)
        h = LEAD * len(lines)

        def box_of(cand):
            x_edge, align, ytop = cand
            bx0 = x_edge - w if align == "r" else x_edge
            return (bx0 - 1, ytop - h, bx0 + w + 1, ytop + 2)

        def leader_of(cand):
            x_edge, align, ytop = cand
            lx = x_edge + (2 if align == "r" else -2)
            ly_ = ytop - SIZE + 2.4
            land = 5 if anchor[0] >= lx else -5
            return [((lx, ly_), (lx + land, ly_)), ((lx + land, ly_), (anchor[0], anchor[1]))]

        def ok(cand):
            if not free(box_of(cand)):
                return False
            # the leader must not run through any text block that is already placed
            return not any(_seg_hits_box(a, b, pb) for a, b in leader_of(cand) for pb in placed)

        chosen, masked = None, False
        for cand in candidates:
            if ok(cand):
                chosen = cand
                break
        if chosen is None:
            chosen, masked = candidates[0], True
            STATS["masked"] += 1
        x_edge, align, ytop = chosen
        box = box_of(chosen)
        placed.append(box)
        if masked:
            c.setFillColor(colors.white)
            c.rect(box[0], box[1], box[2] - box[0], box[3] - box[1], stroke=0, fill=1)
        text_block(c, x_edge, ytop - SIZE, lines, size=SIZE, align=align, leading=LEAD)
        lx = x_edge + (2 if align == "r" else -2)
        leader(c, lx, ytop - SIZE + 2.4, anchor[0], anchor[1])
        drawn_leaders.extend(leader_of(chosen))

    def margin(x_edge, align, pref_y, direction, lines=3):
        """Slots stacked in a side margin: direction 0 = alternate about pref_y, +1 up, -1 down."""
        step = LEAD * lines + 3
        out = []
        for k in range(16):
            n = k if direction else (k + 1) // 2
            sgn = direction or (1 if k % 2 else -1)
            out.append((x_edge, align, pref_y + n * step * sgn))
        return out

    def beside(ax_, y_top, n=18):
        """Slots left/right of a pipe at ax_, moving further out until one is clear."""
        out = []
        for k in range(n):
            off = 9 + 6 * k
            out.append((ax_ + off, "l", y_top))
            out.append((ax_ - off, "r", y_top))
        return out

    for grp, ax, ay in sorted(anchors, key=lambda t: (t[0][0]["side"], t[2], t[1])):
        lines = group_lines(grp)                            # one callout per line of pipes
        side = grp[0]["side"]
        if side == "left":
            put(lines, (ax, ay), margin(col_left, "r", ay + 14, 0, len(lines)))
        elif side == "right":
            put(lines, (ax, ay), margin(col_right, "l", ay + 14, 0, len(lines)))
        elif side == "top":      # beside the arrow, between the border and the dimension rows
            put(lines, (ax, ay), beside(ax, red[3] + 34))
        else:                    # beside the arrow, then below the chain, then a staircase of rows
            rows_y = [chain_y - 12 - k * (LEAD * len(lines) + 4) for k in range(3)]
            stair = [c_ for y_ in rows_y for c_ in ((ax + 4, "l", y_), (ax - 4, "r", y_))]
            put(lines, (ax, ay), beside(ax, red[1] - 3) + beside(ax, chain_y - 12) + stair)

    agg = ["AGG DRAIN", "Ø100", f"IL {fmt_rl(d['base_rl'])}"]
    put(agg, agg_anchor, margin(col_left, "r", gy + 12, -1))

    # ---- title ------------------------------------------------------------------
    underlined_title(c, "PLAN VIEW", gx + L / 2, title_y, size=11)

    return {"red": red, "mod": mod, "title_y": title_y}
