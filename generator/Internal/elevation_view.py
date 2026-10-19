# ==========================================================
# elevation_view.py
# Elevation of the tank seen from one face (front / back / left / right).
#
# Every view carries the general-arrangement callouts and level dimensions (front
# elevation on the GA sheet, back / left / right on their own sheets).
#
# All model sizes are millimetres; `s` is points per millimetre and
# (x0, y0) is the bottom-left of the cube stack in points.
# ==========================================================

from reportlab.lib import colors
from reportlab.pdfgen.canvas import FILL_EVEN_ODD
from reportlab.lib.units import mm

from reportlab.pdfbase.pdfmetrics import stringWidth

from Internal import cube_art
from Internal.plan_view import (FN, FB, arrowhead, dim_h, dim_v, draw_flow_arrow,
                                leader, text_block, underlined_title, _seg_hits_box,
                                _group_pipes, group_lines)

# view -> (face we look at, side shown at picture-left, side shown at picture-right)
# Plan orientation: front = bottom edge ("bottom"), back = top edge ("top").
VIEWS = {
    "front": ("bottom", "left",   "right"),
    "back":  ("top",    "right",  "left"),
    "left":  ("left",   "top",    "bottom"),
    "right": ("right",  "bottom", "top"),
}
MIRROR = {"front": False, "back": True, "left": True, "right": False}

WRAP_EXT_MM = 500          # geofab / liner extended above top of storage
STUB = 20                  # pipe stub length, pt
COL_PITCH = 20             # spacing of the left-hand dimension columns, pt

ELEV_BASE = 46             # room under the tank: base RL label + title
ELEV_ABOVE = 72            # room above top of storage: callouts, 500 extension
ELEV_RIGHT_NEED = 52       # 500 dimension, right pipe stub + arrow

LS, LD = 7, 8.0            # pipe callout text size / leading (same as the plan view)
NL = 3                     # text lines of a single-pipe callout


def _stub_labels(pipes):
    """Pipes of one side wall seen side-on, grouped by invert level: pipes at one level sit on one
    line however their sizes differ, so each level gets ONE callout (lowest first)."""
    by = {}
    for p in pipes:
        by.setdefault(round(p["il"], 3), []).append(p)
    return sorted(by.values(), key=lambda g: min(q["z"] - q["diameter"] / 2 for q in g))


def _stub_lbl_w(d, side):
    """Width (pt) of the widest callout beside the side-on stubs of one wall (0: no stubs)."""
    return max((stringWidth(t, FN, LS)
                for g in _stub_labels([p for p in d["pipes"] if p["side"] == side])
                for t in group_lines(g)), default=0)


def _face_groups(d, view):
    """Pipes on the wall we look at, grouped by position: each group (one line) gets one callout."""
    face = VIEWS[view][0]
    return _group_pipes([p for p in d["pipes"] if p["side"] == face])


def _row_h(d, view):
    """Height (pt) of one row of face-pipe callouts: the tallest callout plus a gap."""
    return LD * max((len(group_lines(g)) for g in _face_groups(d, view)), default=NL) + 8


def _stub_groups(pipes):
    """Pipes of one side wall seen side-on: one stub per (diameter, IL); an inlet and an outlet
    of the same size/level share it ("kinds" has both). Lowest first."""
    by = {}
    for p in pipes:
        by.setdefault((p["diameter"], p["il"]), []).append(p)
    return sorted(({"p": ps[0], "kinds": sorted({q["kind"] for q in ps})} for ps in by.values()),
                  key=lambda g: g["p"]["z"])


def label_rows(d, view):
    """Rows of callouts under the tank for the face pipes (staggered when there are several)."""
    return min(len(_face_groups(d, view)), 2)


def elev_base(d, view="front"):
    """Room (pt) needed under the tank: base RL label, pipe callout rows, title."""
    return ELEV_BASE + _row_h(d, view) * label_rows(d, view)


def right_need(d, view="front"):
    """Room (pt) right of the tank: 500 dimension, or the stub + arrow + callout on that side."""
    w = _stub_lbl_w(d, VIEWS[view][2])
    return max(ELEV_RIGHT_NEED, 55 + w)                 # stub + arrow (47) + gap + callout


def level_items(d):
    """IIL / OIL entries: first inlet and first outlet (merged when identical)."""
    first_in = next((p for p in d["pipes"] if p["kind"] == "INLET"), None)
    first_out = next((p for p in d["pipes"] if p["kind"] == "OUTLET"), None)
    depth = lambda p: (d["fsl"] - p["il"]) * 1000
    if first_in and first_out and abs(depth(first_in) - depth(first_out)) < 1 and \
            first_in["diameter"] == first_out["diameter"]:
        return [("IIL/OIL", first_in)]
    return ([("IIL", first_in)] if first_in else []) + ([("OIL", first_out)] if first_out else [])


def left_shift(d, side_l="left"):
    """Room (pt) the stubs, arrows and their callouts take left of the tank, before the dimensions."""
    w = _stub_lbl_w(d, side_l)
    return 34 + w if w else 0                           # stub + arrow (47) + gap + callout, less the column pad


def left_need(d, side_l="left"):
    """Space (pt) an annotated elevation needs left of the tank (side_l = wall at picture-left)."""
    shift = left_shift(d, side_l)
    n = len(level_items(d))
    cols = 3 + n                                        # stack, cover, [IIL/OIL...], excavation depth
    need = 24 + COL_PITCH * (cols - 1) + 20
    return shift + max(need, 130 if n else 0)

# ======================================================
# ATLANCUBE SIDE FACE (vector artwork traced from CAD)
# ======================================================

FACE_FORM = "atlancube_face"


def _define_face_form(c):
    c.beginForm(FACE_FORM, -2, -2, cube_art.WIDTH + 2, cube_art.HEIGHT + 2)
    c.setFillGray(0)
    c.rect(-2, -2, cube_art.WIDTH + 4, cube_art.HEIGHT + 4, stroke=0, fill=1)
    c.transform(1, 0, 0, -1, 0, cube_art.HEIGHT)                 # artwork is y-down
    for rings, tone in zip(cube_art.TIERS, cube_art.TONES):
        c.setFillGray(tone)
        path = c.beginPath()
        for ring in rings:
            path.moveTo(ring[0], ring[1])
            for i in range(2, len(ring), 2):
                path.lineTo(ring[i], ring[i + 1])
            path.close()
        c.drawPath(path, stroke=0, fill=1, fillMode=FILL_EVEN_ODD)
    c.endForm()


def draw_side_panel(c, x, y, w, h):
    if not c.hasForm(FACE_FORM):
        _define_face_form(c)
    c.saveState()
    c.translate(x, y)
    c.scale(w / cube_art.WIDTH, h / cube_art.HEIGHT)
    c.doForm(FACE_FORM)
    c.restoreState()


# ======================================================
# ELEVATION VIEW
# ======================================================

def _picture_pos(d, view, side_pos_mm, plan_axis):
    """Position along the picture (mm from picture-left) of something at `side_pos_mm`
    along the plan axis ('x' = length, 'y' = width)."""
    full = d["length"] if plan_axis == "x" else d["width"]
    return full - side_pos_mm if MIRROR[view] else side_pos_mm


def draw_elevation_view(c, d, x0, y0, s, view="front", span_dim=False, title=True):
    """span_dim: add the overall width dimension under the tank (sheets that have no plan)."""
    from data_mapper import fmt_rl

    face, side_l, side_r = VIEWS[view]
    end_on = view in ("left", "right")
    span = d["width"] if end_on else d["length"]
    cols = d["cubes_wide"] if end_on else d["cubes_long"]

    tw = span * s
    th = d["stack_h"] * s
    cell_w = tw / cols
    x1 = x0 + tw
    y_top = y0 + th                                         # top of storage
    y_fsl = y_top + d["cover"] * s
    ext = max(WRAP_EXT_MM * s, 8)

    # ---- cube faces, layer by layer (the top layer may be a half layer) ---------
    y = y0
    for row_mm in d["rows_mm"]:
        rh = row_mm * s
        for col in range(cols):
            draw_side_panel(c, x0 + col * cell_w, y, cell_w, rh)
        y += rh

    c.setStrokeColor(colors.black)
    c.setLineWidth(1.5)
    c.rect(x0, y0, tw, th, stroke=1, fill=0)

    # ---- geofab wrap: inner blue dash, pink line, outer blue dash -----------------
    c.setStrokeColor(colors.blue)
    c.setLineWidth(1.6)
    c.setDash(14, 3)
    c.rect(x0 - 1, y0 - 1, tw + 2, th + 2, stroke=1, fill=0)
    c.setDash()

    pl, pr, pb, pt = x0 - 5, x1 + 5, y0 - 5, y_top + ext
    c.setStrokeColorRGB(1, 0, 1)
    c.setLineWidth(1.2)
    c.line(pl, pb, pl, pt)
    c.line(pl, pb, pr, pb)
    c.line(pr, pb, pr, pt)

    c.setStrokeColor(colors.blue)
    c.setLineWidth(1.4)
    c.setDash(14, 3)
    bl, br, bb, bt = x0 - 9, x1 + 9, y0 - 9, y_top + ext + 4
    c.line(bl, bb, bl, bt)
    c.line(bl, bb, br, bb)
    c.line(br, bb, br, bt)
    c.setDash()
    c.setStrokeColor(colors.black)
    c.setLineWidth(1)

    # ---- manhole risers (on top of the tank, up to FSL) ------------------------
    # as wide as the manhole itself (600 square / 600 round / 300 round ...) - the plan's size
    # differences carry over. Every shape (square or round) is drawn the same: riser + flat lid slab.
    # Like the plan, a scale too small to show the smallest riser enlarges all by one factor.
    mh_w = [(mh["h_mm"] if end_on else mh["w_mm"]) * s for mh in d["manholes"]]
    boost = max(1.0, 5.2 / min(mh_w)) if mh_w and min(mh_w) > 0 else 1.0
    risers = []
    riser_boxes = []                                   # keep-out rectangles for the callouts
    for mh, w_pt in zip(d["manholes"], mh_w):
        pos = _picture_pos(d, view, mh["y"] if end_on else mh["x"], "y" if end_on else "x")
        mx = x0 + pos * s
        rw = w_pt * boost
        rh = max(y_fsl - y_top, 6)
        c.setFillGray(0.72)
        c.setLineWidth(0.8)
        c.rect(mx - rw / 2, y_top, rw, rh, stroke=1, fill=1)
        c.setFillGray(0.45)
        c.rect(mx - rw / 2 - 1.2, y_top + rh - 2.4, rw + 2.4, 2.4, stroke=1, fill=1)
        risers.append(mx)
        riser_boxes.append((mx - rw / 2 - 2, y_top, mx + rw / 2 + 2, y_top + rh + 3))

    # ---- pipes ---------------------------------------------------------------
    # wall we look at: pipe ends (circles); the two side walls: stubs with flow arrows;
    # the opposite wall is hidden
    face_axis = "y" if end_on else "x"
    face_cx = lambda p: x0 + _picture_pos(d, view, p["along"], face_axis) * s
    for p in (q for q in d["pipes"] if q["side"] == face):
        c.setFillGray(0.75)
        c.setLineWidth(1)
        c.setStrokeColor(colors.red if p["kind"] == "INLET" else colors.blue)
        c.circle(face_cx(p), y0 + p["z"] * s, max(p["diameter"] * s, 3.5) / 2 + 0.6, stroke=1, fill=1)

    stub_items = []                                    # (wall x, direction, y, callout lines)
    for sd, xw, sgn, compass in ((side_l, x0, -1, "WEST"), (side_r, x1, 1, "EAST")):
        wall = [q for q in d["pipes"] if q["side"] == sd]
        for lvl in _stub_labels(wall):                 # one callout per level, beside the middle of its stubs
            lo = min(q["z"] - q["diameter"] / 2 for q in lvl)
            hi = max(q["z"] + q["diameter"] / 2 for q in lvl)
            stub_items.append((xw, sgn, y0 + (lo + hi) / 2 * s, group_lines(lvl)))
        for g in _stub_groups(wall):
            ph, py = max(g["p"]["diameter"] * s, 3.5), y0 + g["p"]["z"] * s
            c.setFillGray(0.75)
            c.setStrokeColor(colors.black)
            c.setLineWidth(1)
            c.rect(xw if sgn > 0 else xw - STUB, py - ph / 2, STUB, ph, stroke=1, fill=1)
            for k, kind in enumerate(g["kinds"]):      # inlet + outlet share a stub: arrows side by side
                off = 0 if len(g["kinds"]) == 1 else (3.5 if k % 2 == 0 else -3.5)
                draw_flow_arrow(c, xw, py + off, compass, kind, pipe_extension=STUB)

    c.setStrokeColor(colors.black)
    c.setFillColor(colors.black)
    c.setLineWidth(1)

    # ======================================================
    # GENERAL-ARRANGEMENT ANNOTATIONS
    # ======================================================
    SZ = LS

    # dimension columns sit left of the tank (and of any pipe stub + arrow + callout on that side)
    shift = left_shift(d, side_l)
    col = x0 - shift - 24
    dim_obst = []                                      # what the dimensions occupy (callouts keep clear)

    def column(y_a, y_b, value, label):
        nonlocal col
        dim_v(c, col, y_a, y_b, value, label, ext_to=x0 - 9)
        dim_obst.append((col - 14, y_a, col + 3, y_b))
        dim_obst.extend((col - 3, y_ - 1, x0 - 9, y_ + 1) for y_ in (y_a, y_b))   # extension lines
        col -= COL_PITCH

    column(y0, y_top, f"{d['stack_h']:.0f}", f"{d['stack_label']} (1000L)")
    column(y_top, y_fsl, f"{d['cover']:.0f}", "COVER")

    items = level_items(d)
    depth = lambda p: (d["fsl"] - p["il"]) * 1000
    notes = []
    for tag, p in items:
        lowest = y0 + (p["il"] - d["base_rl"]) * 1000 * s
        column(lowest, y_fsl, f"{depth(p):.0f}", tag)
        notes.append(f"{tag}: Ø{p['diameter']:g} PIPE  IL {fmt_rl(p['il'])}")
    keep = list(riser_boxes)
    if notes:
        keep.append(text_block(c, x0 - shift - 24 + 4, y_fsl + 22 + 7.5 * (len(notes) - 1), notes,
                               size=6.5, align="r", leading=7.5))

    column(y0, y_fsl, f"{d['exc_depth']:.0f}", "EXCAVATION DEPTH")

    # ---- callouts -------------------------------------------------------------------
    # Every block is placed on a spot that touches no riser, no line and no other block;
    # blocks that have no clear spot (very small tanks) get a white mask as last resort.
    keep += dim_obst
    keep.append((x1 + 24, y_top - 2, x1 + 40, y_top + ext + 2))       # the "500" dimension
    for p in d["pipes"]:                                              # side stubs + their arrows
        py_ = y0 + p["z"] * s
        half_ = max(p["diameter"] * s, 3.5) / 2 + 6
        if p["side"] == side_l:
            keep.append((x0 - STUB - 28, py_ - half_, x0, py_ + half_))
        elif p["side"] == side_r:
            keep.append((x1, py_ - half_, x1 + STUB + 28, py_ + half_))

    def clear(box):
        return all(box[2] < o[0] or box[0] > o[2] or box[3] < o[1] or box[1] > o[3] for o in keep)

    def block_box(xl, yb, w, n, size=SZ, lead=LD):
        return (xl - 1, yb - (n - 1) * lead - 2, xl + w + 1, yb + size + 1)

    def free_anchor(xa):
        """Point on the top edge for a leader, moved off any riser."""
        for bx0, _, bx1, _ in riser_boxes:
            if bx0 <= xa <= bx1:
                xa = bx0 - 2 if xa - bx0 < bx1 - xa else bx1 + 2
        return min(max(xa, x0 + 2), x1 - 2)

    # FSL label: right of the leftmost riser (or of a ground tick); left of it near the right end
    if risers:
        ax = min(risers)
    else:
        ax = x0 + 8
        c.setLineWidth(0.6)
        c.line(x0 - 4, y_fsl, x0 + 16, y_fsl)
    fsl_txt = f"FSL {fmt_rl(d['fsl'])}"
    fw = stringWidth(fsl_txt, FN, 8)
    c.setFont(FN, 8)
    c.setFillColor(colors.black)
    if ax + 22 + fw <= x1:                               # must not reach the liner callout's leader
        c.drawString(ax + 22, y_fsl + 12, fsl_txt)
        leader(c, ax + 20, y_fsl + 14.5, ax, y_fsl)
        keep.append((ax + 20, y_fsl + 9, ax + 24 + fw, y_fsl + 22))
    else:
        c.drawRightString(ax - 22, y_fsl + 12, fsl_txt)
        leader(c, ax - 20, y_fsl + 14.5, ax, y_fsl)
        keep.append((ax - 24 - fw, y_fsl + 9, ax - 20, y_fsl + 22))

    # ---- pipe callouts (same text as the plan view) ----------------------------------
    def masked(box):
        c.setFillColor(colors.white)
        c.rect(box[0], box[1], box[2] - box[0], box[3] - box[1], stroke=0, fill=1)

    # base RL
    keep.append(text_block(c, x0 - 34, y0 - 20, ["ATLAN CUBE", f"BASE RL: {fmt_rl(d['base_rl'])}"],
                           size=7, align="r", leading=8))
    leader(c, x0 - 32, y0 - 17.6, x0 + 3, y0 - 1)
    below_leaders = [((x0 - 32, y0 - 17.6), (x0 - 27, y0 - 17.6)), ((x0 - 27, y0 - 17.6), (x0 + 3, y0 - 1))]

    # side-on stubs: the callout sits beyond the flow arrow, level with the stub; when that spot
    # is taken (a dimension line, another callout) it slides up / down and a short leader links it
    for xw, sgn, py, lines in stub_items:
        n = len(lines)
        mid = 4 * n - 7                                   # first baseline above the block's vertical centre
        w = max(stringWidth(t, FN, LS) for t in lines)
        edge = xw + sgn * 51                              # text edge nearest the arrow tip
        xl = edge if sgn > 0 else edge - w
        spots = [0] + [k * 4 * sg for k in range(1, 25) for sg in (1, -1)]
        link = lambda dy: ((xw + sgn * 49, py), (edge - sgn * 1.5, py + dy))
        # first choice: a spot whose leader crosses nothing; then any clear spot; then a mask
        found = next(((dy, block_box(xl, py + dy + mid, w, n)) for strict in (True, False) for dy in spots
                      if clear(block_box(xl, py + dy + mid, w, n)) and
                      not (strict and abs(dy) > 5 and any(_seg_hits_box(*link(dy), o) for o in keep))), None)
        if found:
            dy, box = found
        else:
            dy, box = 0, block_box(xl, py + mid, w, n)
            masked(box)
        keep.append(box)
        text_block(c, edge, py + dy + mid, lines, size=LS, align="r" if sgn < 0 else "l", leading=LD)
        if abs(dy) > 5:
            c.setStrokeColor(colors.black)
            c.setLineWidth(0.5)
            c.line(*link(dy)[0], *link(dy)[1])

    # pipe ends on the face: callouts in rows under the tank (staggered when several), each with a
    # leader up to its pipe - drawn white where it crosses the black cube faces
    # pipes on one line (same position) share ONE callout; its leader runs up to the lowest pipe
    # and on through the others on that line
    rows = label_rows(d, view)
    row_h = _row_h(d, view)
    top0 = y0 - (36 if span_dim else 14)                  # top of the first row
    used = 0
    for grp in sorted(_face_groups(d, view), key=lambda g: face_cx(g[0])):
        lines = group_lines(grp)
        n = len(lines)
        w = max(stringWidth(t, FN, LS) for t in lines)
        cx = face_cx(grp[0])
        bottoms = [y0 + q["z"] * s - max(q["diameter"] * s, 3.5) / 2 - 0.6 for q in grp]
        tip = (cx, min(bottoms))
        pick = None
        for r in range(rows):
            base_y = top0 - r * row_h - LS
            for sh in [0] + [k * 8 * sg for k in range(1, 21) for sg in (1, -1)]:
                box = block_box(cx + sh - w / 2, base_y, w, n)
                seg = ((cx + sh, base_y + LS + 2), tip)
                if clear(box) and not any(_seg_hits_box(*seg, o) for o in keep) \
                        and not any(_seg_hits_box(a, b, box) for a, b in below_leaders):
                    pick = (cx + sh, base_y, box, seg, r)
                    break
            if pick:
                break
        if pick is None:                                  # no clear spot: first row, over a mask
            base_y = top0 - LS
            box = block_box(cx - w / 2, base_y, w, n)
            masked(box)
            pick = (cx, base_y, box, ((cx, base_y + LS + 2), tip), 0)
        tx, base_y, box, (a, b), r = pick
        used = max(used, r + 1)
        keep.append(box)
        text_block(c, tx, base_y, lines, size=LS, align="c", leading=LD)
        below_leaders.append((a, b))
        c.setLineWidth(0.5)
        if b[1] <= y0:                                    # pipe at the base: leader stays below the tank
            parts = [(a, b, colors.black)]
        else:
            m = (a[0] + (b[0] - a[0]) * (y0 - a[1]) / (b[1] - a[1]), y0)
            parts = [(a, m, colors.black), (m, b, colors.white)]
        if max(bottoms) > b[1] + 1:                       # more pipes on this line, higher up
            parts.append(((cx, b[1]), (cx, max(bottoms)), colors.white))
        for p1, p2, col_ in parts:
            c.setStrokeColor(col_)
            c.line(p1[0], p1[1], p2[0], p2[1])
        c.setStrokeColor(colors.black)

    # liner callout at the right end (fixed spot, raised until it is clear)
    liner = ["NON-WOVEN", "GEO-FAB & LDPE LINER", "EXTENDED 500mm", "ABOVE TOP OF STORAGE"]
    lw = max(stringWidth(t, FN, SZ) for t in liner)
    ly = y_top + ext + 54
    for _ in range(30):
        if clear(block_box(x1 + 6 - lw, ly, lw, len(liner))):
            break
        ly += 6
    keep.append(block_box(x1 + 6 - lw, ly, lw, len(liner)))
    text_block(c, x1 + 6, ly, liner, size=SZ, align="r", leading=LD)
    leader(c, x1 + 9, ly - (len(liner) - 1) * LD - 1.5, x1 + 5, y_top + ext)   # from under the last line
    dim_v(c, x1 + 26, y_top, y_top + ext, "500", ext_to=x1 + 9)

    keep_leaders = []                                  # leader segments already drawn

    def leader_segs(xl, yb, w, from_left):
        """The two segments of the leader of a block (landing + diagonal to the top edge)."""
        ax_ = free_anchor(xl - 14 if from_left else xl + w + 28)
        if from_left and ax_ > xl + w:            # block sits left of the tank: leave by its right end
            from_left = False
        elif not from_left and ax_ < xl:          # block sits beyond the tank's end: leave by its left end
            from_left = True
        lx = xl - 2 if from_left else xl + w + 2
        ly_ = yb + SZ - 4.6
        land = 5 if ax_ >= lx else -5
        return [((lx, ly_), (lx + land, ly_)), ((lx + land, ly_), (ax_, y_top + 1))]

    def place_block(lines, pref_x, from_left):
        """Left-aligned block above the tank at the nearest spot to pref_x where neither the
        block nor its leader touches a riser, another block or another leader."""
        w = max(stringWidth(t, FN, SZ) for t in lines)
        n = len(lines)
        levels = [y_top + 28 + k * (n * LD + 6) for k in range(4)]
        xs_ = [pref_x]
        for k in range(1, 80):
            xs_ += [pref_x + 8 * k, pref_x - 8 * k]
        # normally above the tank; a tank narrower than its callouts lets them sit past its end
        lo, hi = x0 - 4, max(x1 + 6 - w, x1 + 150 - w)
        for yb in levels:
            for xl in xs_:
                if not (lo <= xl <= hi):
                    continue
                box = block_box(xl, yb, w, n)
                if not clear(box):
                    continue
                segs = leader_segs(xl, yb, w, from_left)
                if any(_seg_hits_box(a, b, o) for a, b in segs for o in keep):
                    continue
                if any(_seg_hits_box(a, b, box) for a, b in keep_leaders):
                    continue
                keep.append(box)
                keep_leaders.extend(segs)
                return xl, yb, w, False
        xl, yb = min(max(pref_x, lo), max(lo, hi)), levels[0]
        keep.append(block_box(xl, yb, w, n))
        keep_leaders.extend(leader_segs(xl, yb, w, from_left))
        return xl, yb, w, True

    def draw_block(lines, xl, yb, w, masked, from_left):
        if masked:
            bx = block_box(xl, yb, w, len(lines))
            c.setFillColor(colors.white)
            c.rect(bx[0], bx[1], bx[2] - bx[0], bx[3] - bx[1], stroke=0, fill=1)
        text_block(c, xl, yb, lines, size=SZ, align="l", leading=LD)
        (a, b), (_, end) = leader_segs(xl, yb, w, from_left)
        leader(c, a[0], a[1], end[0], end[1])

    top_lines = ["TOP OF STORAGE", f"RL {fmt_rl(d['top_rl'])}"]
    xl, yb, w, m = place_block(top_lines, x0 + tw * 0.30, True)
    draw_block(top_lines, xl, yb, w, m, True)

    geo_lines = ["NON-WOVEN GEO-FAB", "WRAPPED AROUND THE TANK"]
    xl, yb, w, m = place_block(geo_lines, x1 - 100 - max(stringWidth(t, FN, SZ) for t in geo_lines), False)
    draw_block(geo_lines, xl, yb, w, m, False)

    if span_dim:
        dim_h(c, x0, x1, y0 - 26, f"{span:.0f}", ext_to=y0 - 9)
    if title:
        underlined_title(c, f"{view.upper()} ELEVATION VIEW", x0 + tw / 2,
                         y0 - (48 if span_dim else 34) - row_h * used, size=14 if span_dim else 11)
    return {"top": y_top, "fsl": y_fsl, "used_top": max([y_fsl] + [b[3] for b in keep]),
            "used_x": (min([x0] + [b[0] for b in keep]), max([x1] + [b[2] for b in keep]))}


# ======================================================
# ONE ELEVATION PER SHEET (back / left / right extra sheets)
# ======================================================

def draw_elevation_page(c, d, view, bx, by, bw, bh):
    """Annotated elevation, its annotations centred in the box (bx, by, bw, bh) and scaled to
    fill the sheet (an end-on view of a long tank would be unreadable at the front-view scale)."""
    span = d["width"] if view in ("left", "right") else d["length"]
    need_l = left_need(d, VIEWS[view][1])
    need_r = right_need(d, view)
    base = elev_base(d, view) + 20                      # + room for the span dimension and big title
    pad = 40
    s = min((bw - need_l - need_r - pad) / span,
            (bh - pad - base - ELEV_ABOVE) / d["stack_h"],
            (bh - pad - base - 44) / (d["stack_h"] + d["cover"]),
            0.10)
    h = base + d["stack_h"] * s + max(ELEV_ABOVE, d["cover"] * s + 44)
    x0 = bx + (bw - (need_l + span * s + need_r)) / 2 + need_l
    y0 = by + (bh - h) / 2 + base
    draw_elevation_view(c, d, x0, y0, s, view=view, span_dim=True)
