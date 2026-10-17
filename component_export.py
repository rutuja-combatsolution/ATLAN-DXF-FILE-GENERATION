"""One DXF per component of the payload's bill of materials, in true millimetres (1:1).

Geometry sources, in order of preference (nothing is invented):
  * supplier part drawing (PDF, vector)  -> half cube module, full height side plate
  * supplier 3D model (GLB)              -> half height side plate (orthographic feature-edge views)
  * the payload itself                   -> manholes and pipes (size, type, levels, wall, offsets)
  * no geometry supplied                 -> single / double connector: a note sheet, flagged in manifest.json

Quantities, names and positions always come from the payload.
"""
import math
import re
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment as A

from dxf_canvas import PT_MM, VALID_LWT, add_text_lines, new_document

HERE = Path(__file__).resolve().parent
ASSET_DIR = HERE / "dxg files"
K = PT_MM

LAYERS = [("OUTLINE", 7), ("DETAIL", 8), ("FINE", 9), ("SYMBOL", 7), ("CENTRELINE", 1),
          ("DIMENSIONS", 7), ("ANNOTATIONS", 7), ("FLOW", 5), ("TITLE", 7)]

PDF_ITEM_LIMIT = 4_000_000

# Windows are in PDF points on the supplier sheets; scale = real mm per paper mm of that view.
MODULE_SPEC = {
    "pdf": "20250617_510.0023-06_dwg.pdf", "page": 0,
    "source": "Supplier drawing 510.0023-06 ECOCUBE 1000 MODULE (rev 06)",
    "views": [("PLAN VIEW", (103, 150, 1123, 1217), 4.0, True),
              ("SIDE VIEW", (1283, 150, 1610, 1123), 4.0, True),
              ("SECTION C-C", (1844, 262, 2181, 1170), 4.0, False),
              ("SECTION A-A (1:2)", (112, 1339, 506, 1929), 2.0, False),
              ("SECTION B-B (1:2)", (655, 1339, 983, 1985), 2.0, False)],
}
PLATE_SPEC = {
    "pdf": "20250617_510.0024-03_dwg.pdf", "page": 1,
    "source": "Supplier drawing 510.0024-03 ECOCUBE 1000 SIDE PLATE (rev 03), sheet 2",
    "views": [("FRONT VIEW", (50, 56, 804, 606), 5.0, True),
              ("SECTIONS A-A / B-B", (860, 86, 1124, 645), 5.0, False),
              ("DETAIL C (1:1)", (106, 609, 344, 800), 1.0, False)],
}
HALF_PLATE_GLB = "1000L MODULE - Half Height Side Plate.glb"

NOTE_MANHOLE = ["ACCESS MANHOLES Ø375 ROUND LIDS - CLASS 'D' (BY ATLAN)", "Ø300 PVC RISERS"]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "component"


def qty_text(q):
    return f"{q:g}" if isinstance(q, (int, float)) else str(q)


# ---------------------------------------------------------------------------- sheet helper
class Sheet:
    """A component DXF: model-space helpers, extent tracking and the title strip."""

    def __init__(self):
        self.doc = new_document(LAYERS)
        self.msp = self.doc.modelspace()
        self.lo = [math.inf, math.inf]
        self.hi = [-math.inf, -math.inf]

    def grow(self, *pts):
        for x, y in pts:
            self.lo[0], self.lo[1] = min(self.lo[0], x), min(self.lo[1], y)
            self.hi[0], self.hi[1] = max(self.hi[0], x), max(self.hi[1], y)

    @property
    def size(self):
        return (max(self.hi[0] - self.lo[0], 1.0), max(self.hi[1] - self.lo[1], 1.0))

    def line(self, a, b, layer="SYMBOL", **kw):
        self.grow(a, b)
        self.msp.add_line(a, b, dxfattribs={"layer": layer, **kw})

    def rect(self, x, y, w, h, layer="SYMBOL"):
        self.grow((x, y), (x + w, y + h))
        self.msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True,
                                dxfattribs={"layer": layer})

    def circle(self, c, r, layer="SYMBOL"):
        self.grow((c[0] - r, c[1] - r), (c[0] + r, c[1] + r))
        self.msp.add_circle(c, r, dxfattribs={"layer": layer})

    def text(self, x, y, s, h, layer="ANNOTATIONS", align=A.LEFT, rotation=0.0):
        self.grow((x, y), (x, y + h))
        t = self.msp.add_text(str(s), dxfattribs={"height": h, "layer": layer, "style": "ARIAL", "rotation": rotation})
        t.set_placement((x, y), align=align)

    def dim(self, p1, p2, base, h, angle=0.0, text="<>"):
        d = self.msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, text=text, dimstyle="Standard",
                                    override={"dimtxt": h, "dimasz": h, "dimexo": h * 0.3, "dimexe": h * 0.6,
                                              "dimgap": h * 0.3, "dimtad": 1, "dimdec": 0, "dimtxsty": "ARIAL",
                                              "dimclrd": 7, "dimclre": 7, "dimclrt": 7},
                                    dxfattribs={"layer": "DIMENSIONS"})
        d.render()
        self.grow(p1, p2, base)

    def finish(self, path, title_lines, text_h):
        x0, y0 = self.lo
        add_text_lines(self.msp, x0, y0 - 3 * text_h, [t for t in title_lines if t], text_h, "TITLE")
        w, h = self.size
        self.doc.set_modelspace_vport(height=max(w, h) * 1.3, center=(x0 + w / 2, y0 + h / 2 - 3 * text_h))
        errors = self.doc.audit().errors
        if errors:
            raise ValueError(f"DXF audit failed for {path}: {errors}")
        self.doc.saveas(path)
        if ezdxf.readfile(path).audit().errors:
            raise ValueError(f"DXF read-back audit failed for {path}")


def _title(name, qty, unit, data, source, extra=()):
    proj = [t for t in data["project_lines"] if t]
    return ([f"COMPONENT: {name}", f"QUANTITY: {qty_text(qty)} {unit}"] if qty is not None else [f"COMPONENT: {name}"]) + \
           [f"PROJECT: {proj[0]}" if proj else "", f"GENERAL ARRANGEMENT: {data['title_lines'][1]}",
            f"SOURCE: {source}", "UNITS: mm, drawn 1:1"] + list(extra)


# ---------------------------------------------------------------------------- supplier PDF views
def _item_points(it):
    k = it[0]
    if k == "l":
        return [it[1], it[2]]
    if k == "c":
        return [it[1], it[2], it[3], it[4]]
    if k == "re":
        r = it[1]
        return [(r.x0, r.y0), (r.x1, r.y1)]
    if k == "qu":
        q = it[1]
        return [q.ul, q.ur, q.lr, q.ll]
    return []


def _xy(p):
    return (p.x, p.y) if hasattr(p, "x") else (p[0], p[1])


def _pdf_layer(width_pt):
    return "OUTLINE" if width_pt >= 0.9 else ("DETAIL" if width_pt >= 0.4 else "FINE")


def _lineweight(width_pt):
    want = width_pt * K * 100
    return min(VALID_LWT, key=lambda w: abs(w - want))


def _view_item_buckets(page, views):
    """Assign every drawing item to the view window it lies in (items, not drawings: one PDF
    drawing object can carry the strokes of several views)."""
    buckets = [dict() for _ in views]
    total = 0
    for di, d in enumerate(page.get_drawings()):
        for it in d["items"]:
            pts = [_xy(p) for p in _item_points(it)]
            if not pts:
                continue
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            for vi, (_, win, _, _) in enumerate(views):
                if win[0] <= cx <= win[2] and win[1] <= cy <= win[3]:
                    buckets[vi].setdefault(di, [d, []])[1].append(it)
                    total += 1
                    break
    return buckets, total


def build_pdf_component(spec, assets_dir, sheet, text_h):
    """Draw the spec's views side by side (true mm). Returns the list of view names."""
    try:
        import pymupdf as fitz
    except ImportError:          # older PyMuPDF
        import fitz
    from pdf_to_dxf import build_subpaths               # tested PDF path -> polyline/arc converter

    pdf_path = Path(assets_dir) / spec["pdf"]
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    page = fitz.open(pdf_path)[spec["page"]]
    buckets, total = _view_item_buckets(page, spec["views"])
    if not total:
        raise ValueError(f"no drawing items found in the view windows of {pdf_path.name}")

    # tight extent of each view, then lay the views out in a row
    boxes = []
    for (name, win, S, _), bucket in zip(spec["views"], buckets):
        xs, ys = [], []
        for d, items in bucket.values():
            for it in items:
                for p in _item_points(it):
                    x, y = _xy(p)
                    xs.append(x)
                    ys.append(y)
        boxes.append((min(xs), min(ys), max(xs), max(ys)) if xs else None)
    widths = [((b[2] - b[0]) * K * S if b else 0) for b, (_, _, S, _) in zip(boxes, spec["views"])]
    gap = max(60.0, 0.06 * max(widths))
    ox = 0.0
    msp = sheet.msp
    done = []
    for (name, win, S, caption), bucket, box, w in zip(spec["views"], buckets, boxes, widths):
        if box is None:
            continue
        bx0, by0, bx1, by1 = box
        to_mm = lambda x, y, bx0=bx0, by1=by1, S=S, ox=ox: ((x - bx0) * K * S + ox, (by1 - y) * K * S)
        for d, items in bucket.values():
            subs = build_subpaths(items, to_mm)
            width = d.get("width") or 0.0
            attr = {"layer": _pdf_layer(width), "lineweight": _lineweight(width)}
            col = d.get("color")
            if col and max(col) > 0.02:
                attr["true_color"] = (round(col[0] * 255) << 16) | (round(col[1] * 255) << 8) | round(col[2] * 255)
            dashes = [float(v) for v in re.findall(r"[-\d.]+", (d.get("dashes") or "").split("]")[0])]
            if dashes:
                attr["linetype"] = _ensure_dash(sheet.doc, dashes, K * S)
            for v, b, closed in subs:
                sheet.grow(*v)
                if len(v) == 2 and not closed and not any(b):
                    msp.add_line(v[0], v[1], dxfattribs=attr)
                elif len(v) >= 2:
                    msp.add_lwpolyline([(x, y, bu) for (x, y), bu in zip(v, b)], format="xyb", close=closed,
                                       dxfattribs=attr)
        if caption:
            sheet.text(ox, -2.2 * text_h, f"{name}  ({spec['source'].split(' ')[2]} view, drawn 1:1 mm)", text_h, "TITLE")
        done.append(name)
        ox += w + gap
    return done


def _ensure_dash(doc, dashes, mm_per_pt):
    arr = list(dashes) * (2 if len(dashes) % 2 else 1)
    name = "DASH_" + "_".join(f"{v * mm_per_pt:.1f}" for v in arr)
    if name not in doc.linetypes:
        doc.linetypes.add(name, pattern=[sum(arr) * mm_per_pt] +
                          [(v if i % 2 == 0 else -v) * mm_per_pt for i, v in enumerate(arr)])
    return name


# ---------------------------------------------------------------------------- supplier 3D model views
def build_mesh_component(glb_path, sheet, text_h):
    """Front / top / side line views of a GLB (third-angle layout), true mm."""
    import mesh_views as mv
    verts, tris = mv.load_glb(glb_path)
    verts = verts - verts.min(axis=0)
    dx, dy, dz = verts.max(axis=0)
    gap = max(60.0, 0.08 * max(dx, dz))
    # (title, projected axes, view direction, origin of that view)
    layout = [("FRONT VIEW", (0, 2), (0, 1, 0), (0.0, 0.0)),
              ("TOP VIEW", (0, 1), (0, 0, 1), (0.0, dz + gap)),
              ("SIDE VIEW", (1, 2), (1, 0, 0), (dx + gap, 0.0))]
    counts = {}
    for name, axes, vdir, (ox, oy) in layout:
        edges = mv.feature_edges(verts, tris, vdir)
        a, b = mv.project(verts, edges, list(axes))
        for p, q in zip(a, b):
            sheet.msp.add_line((p[0] + ox, p[1] + oy), (q[0] + ox, q[1] + oy), dxfattribs={"layer": "OUTLINE", "lineweight": 13})
        w = a[:, 0].max() if len(a) else 0
        sheet.grow((ox, oy), (ox + max(a[:, 0].max(), b[:, 0].max()), oy + max(a[:, 1].max(), b[:, 1].max())))
        counts[name] = len(edges)
        sheet.text(ox, oy - 2.2 * text_h, f"{name}  (hidden lines not removed)", text_h, "TITLE")
    return counts, (dx, dy, dz)


# ---------------------------------------------------------------------------- payload-driven symbols
def build_manhole(m_src, m, cover, sheet, h):
    """Plan symbol and riser elevation at true size from the payload's manhole entry."""
    w, ht = m["w_mm"], m["h_mm"]
    circle = m["shape"] == "circle"
    gap = max(w, ht) * 1.4 + 6 * h
    # plan
    if circle:
        sheet.circle((0, 0), w / 2)
        if w >= 500:
            sheet.circle((0, 0), w / 2 * 0.6)
        else:
            hat = sheet.msp.add_hatch(color=7, dxfattribs={"layer": "SYMBOL"})
            hat.set_solid_fill()
            hat.paths.add_polyline_path([(-w * 0.11, 0, 1), (w * 0.11, 0, 1)], is_closed=True)
    else:
        sheet.rect(-w / 2, -ht / 2, w, ht)
    ext = max(w, ht) * 0.75 + 2 * h
    sheet.line((-ext, 0), (ext, 0), "CENTRELINE")
    sheet.line((0, -ext), (0, ext), "CENTRELINE")
    sheet.dim((-w / 2, -ht / 2 - 0), (w / 2, -ht / 2), (0, -ht / 2 - 3 * h), h)
    sheet.text(0, -ht / 2 - 7 * h, "PLAN VIEW", h, "TITLE", A.CENTER)
    # elevation: riser from top of storage (y = 0) up to finished surface
    ex = gap + w / 2 + w / 2
    sheet.rect(ex - w / 2, 0, w, cover)
    sheet.line((ex - w / 2 - 300, 0), (ex + w / 2 + 300, 0), "SYMBOL")
    sheet.line((ex - w / 2 - 300, cover), (ex + w / 2 + 300, cover), "SYMBOL")
    sheet.text(ex + w / 2 + 340, cover - h, "FSL", h)
    sheet.text(ex + w / 2 + 340, 0, "TOP OF STORAGE", h)
    sheet.dim((ex - w / 2, 0), (ex - w / 2, cover), (ex - w / 2 - 3 * h, 0), h, 90)
    sheet.dim((ex - w / 2, cover), (ex + w / 2, cover), (ex, cover + 3 * h), h)
    sheet.text(ex, -2.2 * h, "ELEVATION (RISER, TOP OF STORAGE TO FSL)", h, "TITLE", A.CENTER)
    notes = [f"TYPE: {m_src.get('manhole_type')}", f"FOOTPRINT: {w:g} x {ht:g} mm ({m['shape']})",
             f"HORIZONTAL OFFSET: {float(m_src.get('horizontal_offset') or 0):g} m  |  "
             f"TOP DEPTH OFFSET: {float(m_src.get('top_depth_offset') or 0):g} m",
             f"POSITION IN PLAN (FROM MODULE CORNER): X {m['x']:.0f}  Y {m['y']:.0f} mm",
             f"RISER HEIGHT = COVER DEPTH {cover:g} mm"] + NOTE_MANHOLE
    return notes


def build_pipe(p, src, data, sheet, h):
    """End view and side stub of one inlet / outlet from the payload."""
    d = p["diameter"]
    stub = max(2.0 * d, 600.0)
    inlet = p["kind"] == "INLET"
    # end view
    sheet.circle((0, 0), d / 2)
    sheet.line((-d * 0.75, 0), (d * 0.75, 0), "CENTRELINE")
    sheet.line((0, -d * 0.75), (0, d * 0.75), "CENTRELINE")
    sheet.dim((-d / 2, -d / 2), (d / 2, -d / 2), (0, -d / 2 - 3 * h), h)
    sheet.text(0, d / 2 + 2 * h, "END VIEW", h, "TITLE", A.CENTER)
    # side view: tank wall on the right, pipe stub leaving to the left
    sx = d * 0.75 + 8 * h + stub
    sheet.line((sx, -d), (sx, d), "OUTLINE", lineweight=50)
    x0 = sx - stub                                           # pipe leaves the wall to the left, ends in a break line
    sheet.grow((x0, -d / 2), (sx, d / 2))
    sheet.msp.add_lwpolyline([(sx, d / 2), (x0, d / 2), (x0 - 0.12 * d, d / 6), (x0 + 0.12 * d, -d / 6),
                              (x0, -d / 2), (sx, -d / 2)], dxfattribs={"layer": "SYMBOL"})
    sheet.line((x0 - 0.15 * stub, 0), (sx + 0.15 * stub, 0), "CENTRELINE")
    a0, a1 = sx - stub * 0.65, sx - stub * 0.35               # flow arrow along the centre line
    tail, tip = (a0, a1) if inlet else (a1, a0)
    sheet.line((tail, 0), (tip, 0), "FLOW", lineweight=35)
    head = 0.08 * stub * (1 if tip > tail else -1)
    sheet.line((tip, 0), (tip - head, d * 0.16), "FLOW")
    sheet.line((tip, 0), (tip - head, -d * 0.16), "FLOW")
    sheet.text(sx - stub / 2, -d / 2 - 2.5 * h, "LENGTH NOT TO SCALE", h, "ANNOTATIONS", A.CENTER)
    sheet.text(sx - stub / 2, d / 2 + 2 * h, "SIDE VIEW (TANK WALL AT RIGHT)", h, "TITLE", A.CENTER)
    side = {"top": "BACK (top of plan)", "bottom": "FRONT (bottom of plan)", "left": "LEFT", "right": "RIGHT"}[p["side"]]
    return [f"{p['label']}   Ø{d:g} PIPE   {'FLOW INTO TANK' if inlet else 'FLOW OUT OF TANK'}",
            f"INVERT LEVEL: RL {p['il']:.3f}   (FSL RL {data['fsl']:.3f}, BASE RL {data['base_rl']:.3f})",
            f"CENTRE HEIGHT ABOVE TANK BASE: {p['z']:.0f} mm",
            f"WALL: {side}   |   HORIZONTAL OFFSET FROM WALL CENTRE: {float(src.get('horizontal_offset') or 0):g} m",
            f"POSITION ALONG WALL: {p['along']:.0f} mm"]


# ---------------------------------------------------------------------------- orchestration
def _material(payload):
    return payload.get("material") or {}


def component_plan(data, payload):
    """[(kind, key, name, quantity, unit, extra)] - what the payload says the project needs."""
    m = _material(payload)
    plan = []
    for key, name, qkey, unit, kind in (
            ("half_cube_module", "1000L MODULE - HALF CUBE", "no_half_cubes", "Each", "pdf_module"),
            ("side_plate_full_height", "1000L MODULE - SIDE PANEL FULL HEIGHT", "no_side_plates", "Each", "pdf_plate"),
            ("side_plate_half_height", "1000L MODULE - SIDE PANEL HALF HEIGHT", "no_half_side_plates", "Each", "glb"),
            ("single_connector", "SINGLE CONNECTOR", "no_single_clips", "Each", "no_geometry"),
            ("double_connector", "DOUBLE CONNECTOR", "no_double_clips", "Each", "no_geometry")):
        q = m.get(qkey)
        if q:
            plan.append((kind, key, name, q, unit, None))
    srcs = m.get("manhole") or []
    for i, mh in enumerate(data["manholes"]):
        src = srcs[i] if i < len(srcs) else {}
        plan.append(("manhole", f"manhole_{i + 1}_{slug(src.get('manhole_type') or mh['shape'])}",
                     f"MANHOLE {i + 1} - {str(src.get('manhole_type') or mh['shape']).upper()}", 1, "Each", (src, mh)))
    by_id = {str(x.get("id")): x for x in (m.get("inlet") or []) + (m.get("outlet") or [])}
    for p in data["pipes"]:
        n = p["label"].split("-")[-1]
        plan.append(("pipe", f"{p['kind'].lower()}_{n}_dn{p['diameter']:g}",
                     f"{p['label']} - Ø{p['diameter']:g} PIPE", 1, "Each", (by_id.get(str(p["id"]), {}), p)))
    return plan


def export_components(data, payload, out_dir, assets_dir=ASSET_DIR):
    """Write every component DXF into out_dir; returns manifest rows (one per component)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind, key, name, qty, unit, extra in component_plan(data, payload):
        path = out_dir / f"{key}.dxf"
        row = {"file": path.name, "component": name, "quantity": qty, "unit": unit}
        try:
            sheet = Sheet()
            if kind in ("pdf_module", "pdf_plate"):
                spec = MODULE_SPEC if kind == "pdf_module" else PLATE_SPEC
                h = 30.0 if kind == "pdf_module" else 25.0
                views = build_pdf_component(spec, assets_dir, sheet, h)
                source, extra_lines = spec["source"], [f"VIEWS: {', '.join(views)}"]
                row.update(geometry="supplier drawing", source=spec["pdf"])
            elif kind == "glb":
                h = 20.0
                counts, dims = build_mesh_component(Path(assets_dir) / HALF_PLATE_GLB, sheet, h)
                source = f"Supplier 3D model {HALF_PLATE_GLB} (orthographic feature edges)"
                extra_lines = [f"OVERALL: {dims[0]:.0f} x {dims[2]:.0f} x {dims[1]:.0f} mm (L x H x D)"]
                row.update(geometry="supplier 3D model", source=HALF_PLATE_GLB)
            elif kind == "manhole":
                src, mh = extra
                h = max(12.0, max(mh["w_mm"], mh["h_mm"]) / 18)
                notes = build_manhole(src, mh, data["cover"], sheet, h)
                source, extra_lines = "payload material.manhole[]", notes
                row.update(geometry="payload (parametric)", source="payload", id=str(src.get("id", "")))
            elif kind == "pipe":
                src, p = extra
                h = max(12.0, p["diameter"] / 12)
                notes = build_pipe(p, src, data, sheet, h)
                source, extra_lines = "payload material.inlet[] / outlet[]", notes
                row.update(geometry="payload (parametric)", source="payload", id=str(p["id"]))
            else:                                             # no geometry supplied for connectors
                h = 25.0
                sheet.text(0, 0, f"{name}", h * 1.6, "TITLE")
                sheet.text(0, -3 * h, "NO GEOMETRY SUPPLIED FOR THIS COMPONENT", h, "ANNOTATIONS")
                sheet.text(0, -5 * h, "Add the supplier drawing to 'dxg files' and register it in component_export.py", h)
                sheet.grow((0, 0), (1500, -6 * h))
                source, extra_lines = "none", []
                row.update(geometry="none (placeholder sheet)", source="")
            lines = _title(name, qty, unit, data, source, extra_lines)
            sheet.finish(path, lines, h)
            row["status"] = "ok"
        except Exception as exc:                              # one bad asset must not stop the others
            row.update(status=f"failed: {type(exc).__name__}: {exc}")
            print(f"WARNING: {name}: {row['status']}")
        rows.append(row)
        print(f"Saved: {path}  [{row.get('geometry', '')}] {row['status']}")
    return rows
