"""Plan and elevation DXFs: the PDF's own drawing code, recorded and written as 1:1 model-space DXF.

Every annotation the PDF shows (excavation / module dimensions, MIN 500 callouts, pipe callouts with leaders,
flow arrows, geofab wrap, level dimensions, TOP OF STORAGE / FSL labels ...) comes from
``Internal/plan_view.py`` and ``Internal/elevation_view.py`` through ``dxf_canvas.Recorder``.

Scale: the PDF draws at N.T.S. with fixed-size text.  For CAD the model stays 1:1 in mm and a *plot scale*
1:N is chosen (printed on the drawing): annotation is sized so that it reads like the PDF when plotted at
1:N, and the geometry that the PDF clamps for readability (excavation margin, geofab extension, pipe
diameters) is kept true by limiting N.
"""
import math
from contextlib import contextmanager

import ezdxf
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth

import pdfgen_bridge as bridge
from dxf_canvas import CAP_HEIGHT, PT_MM, Emitter, Recorder, bounds, new_document, add_text_lines
from pdfgen_bridge import cube_art, elevation_view, plan_view

FN = plan_view.FN
FACE_FORM, CUBE_FORM = elevation_view.FACE_FORM, plan_view.CUBE_FORM

LAYERS = [("TANK", 7), ("MODULE_ART", 7), ("EXCAVATION", 1), ("PIPES", 7), ("MANHOLES", 7),
          ("FLOW_INLET", 1), ("FLOW_OUTLET", 5), ("GEOFAB", 5), ("DIMENSIONS", 7),
          ("LEADERS", 7), ("ANNOTATIONS", 7), ("TITLE", 7)]

VIEWS = (("plan_view", None), ("front_elevation", "front"), ("back_elevation", "back"),
         ("left_elevation", "left"), ("right_elevation", "right"))

SHEETS = (("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841))
PLOT_SCALES = (10, 20, 25, 50, 100, 125, 200, 250, 500)
SHEET_MARGIN = (30, 75)          # mm: left+right, bottom (title strip) + top

_ORIG = {name: getattr(plan_view, name) for name in
         ("dim_h", "dim_v", "draw_flow_arrow", "leader", "text_block", "underlined_title", "draw_panel_grid")}
_ORIG["draw_side_panel"] = elevation_view.draw_side_panel


# ---------------------------------------------------------------------------- layers
def _close(a, b, tol=0.03):
    return a is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


def layer_of(kind, st):
    """Layer of a primitive from the pen state the PDF code set (the PDF code has no layer notion)."""
    stroke, fill, lw = st.stroke, st.fill, st.lw
    if kind == "text":
        return "ANNOTATIONS"
    if _close(stroke, (0.5, 0.0, 0.0)):
        return "EXCAVATION"
    if _close(stroke, (1, 0, 1)) or (_close(stroke, (0, 0, 1)) and st.dash):
        return "GEOFAB"
    if fill is not None and abs(fill[0] - fill[1]) < 0.01 and abs(fill[1] - fill[2]) < 0.01:
        g = fill[0]
        if abs(g - 0.75) < 0.02:
            return "PIPES"
        if abs(g - 0.72) < 0.02 or abs(g - 0.45) < 0.02:
            return "MANHOLES"
    if _close(fill, (1, 1, 1)):
        return "MANHOLES" if (kind == "circle" or lw >= 0.9) else "ANNOTATIONS"
    if kind == "circle":
        return "MANHOLES"
    return "TANK" if lw >= 1.4 else "ANNOTATIONS"


# ---------------------------------------------------------------------------- patches to the PDF drawing code
def _forced(fn, layer):
    def wrapper(c, *a, **k):
        with c.layer(layer(c, *a, **k) if callable(layer) else layer):
            return fn(c, *a, **k)
    return wrapper


def _text_override(value, measured_mm):
    try:
        return "" if abs(float(value) - measured_mm) < 0.5 else str(value)
    except (TypeError, ValueError):
        return str(value)


def _native_dims(u):
    """dim_h / dim_v that write a real DIMENSION entity for the ordinary case and fall back to the
    PDF's own (exploded) drawing for the special layouts (MIN. 500 callouts, too-short segments)."""
    orig_h, orig_v = _ORIG["dim_h"], _ORIG["dim_v"]

    def dim_h(c, x1, x2, y, value, label=None, ext_to=None, narrow=None, size=8,
              text_right=False, arrow=4.5, skip_short=False, fit_label=False, value_above=False):
        with c.layer("DIMENSIONS"):
            tw = stringWidth(value or "", FN, size)
            if narrow or not value or (x2 - x1) < max(2 * arrow + 3, tw + 2 * arrow + 3):
                return orig_h(c, x1, x2, y, value, label, ext_to, narrow, size, text_right, arrow, skip_short,
                              fit_label, value_above)
            ya = y if ext_to is None else ext_to
            c.add_dim((x1, ya), (x2, ya), (x1, y), 0, _text_override(value, (x2 - x1) * u),
                      size, arrow, 0 if ext_to is None else 3, 2.5)
            if label:                                                                   # as the PDF's dim_h
                fit = plan_view._fit_label(label, x2 - x1 - 4) if fit_label else ([label], 5)
                if fit:
                    lines, fs = fit
                    c.setFillColor(colors.black)
                    c.setFont(FN, fs)
                    for k, t in enumerate(lines):
                        c.drawCentredString((x1 + x2) / 2, y - (6.5 if len(lines) == 1 else 6.0) - k * (fs + 0.6), t)

    def dim_v(c, x, y1, y2, value, label=None, ext_to=None, narrow=None, size=8,
              narrow_below=False, arrow=4.5, skip_short=False, fit_label=False, label_lines=3, cross=None):
        with c.layer("DIMENSIONS"):
            tw = stringWidth(value or "", FN, size)
            # a DIMENSION entity keeps its value at the middle of the line; where a line of another dimension
            # crosses the middle the PDF moves the value along the dimension, so that one is drawn the PDF's way
            crossed = bool(cross) and any(abs(yc - (y1 + y2) / 2) < tw / 2 + 2 for yc in cross)
            if narrow or crossed or not value or (y2 - y1) < max(2 * arrow + 3, tw + 2 * arrow + 3):
                return orig_v(c, x, y1, y2, value, label, ext_to, narrow, size, narrow_below, arrow, skip_short,
                              fit_label, label_lines, cross)
            xa = x if ext_to is None else ext_to
            c.add_dim((xa, y1), (xa, y2), (x, y1), 90, _text_override(value, (y2 - y1) * u),
                      size, arrow, 0 if ext_to is None else 3, 2.5)
            if label:                                                                   # as the PDF's dim_v
                runs = plan_view._clear_runs(y1, y2, cross)
                fit = (plan_view._fit_label(label, runs[0][1], max_lines=label_lines) if fit_label
                       else ([label if isinstance(label, str) else label[0]], 5))
                if fit:
                    lines, fs = fit
                    c.saveState()
                    c.translate(x - 2.5, (y1 + y2) / 2)
                    c.rotate(90)
                    c.setFillColor(colors.black)
                    c.setFont(FN, fs)
                    for k, t in enumerate(lines):
                        c.drawCentredString(runs[0][0] if fit_label else 0, 10.5 + k * (fs + 0.6), t)
                    c.restoreState()

    return dim_h, dim_v


@contextmanager
def _patched(u, native_dims=True):
    saved = []

    def put(mod, name, fn):
        saved.append((mod, name, getattr(mod, name)))
        setattr(mod, name, fn)

    if native_dims:
        dim_h, dim_v = _native_dims(u)
    else:
        dim_h, dim_v = (_forced(_ORIG["dim_h"], "DIMENSIONS"), _forced(_ORIG["dim_v"], "DIMENSIONS"))
    flow_layer = lambda c, cx, cy, side, flow_type, *a, **k: (
        "FLOW_INLET" if str(flow_type).upper() == "INLET" else "FLOW_OUTLET")
    wrappers = {
        "dim_h": dim_h, "dim_v": dim_v,
        "draw_flow_arrow": _forced(_ORIG["draw_flow_arrow"], flow_layer),
        "leader": _forced(_ORIG["leader"], "LEADERS"),
        "text_block": _forced(_ORIG["text_block"], "ANNOTATIONS"),
        "underlined_title": _forced(_ORIG["underlined_title"], "ANNOTATIONS"),
        "draw_panel_grid": _forced(_ORIG["draw_panel_grid"], "MODULE_ART"),
        "draw_side_panel": _forced(_ORIG["draw_side_panel"], "MODULE_ART"),
    }
    try:
        for mod in (plan_view, elevation_view):
            for name, fn in wrappers.items():
                if hasattr(mod, name):
                    put(mod, name, fn)
        yield
    finally:
        for mod, name, fn in reversed(saved):
            setattr(mod, name, fn)


def _tidy_plan(rec):
    """Plan-only differences from the PDF: no centre info box, and manhole outlines in white."""
    prims = rec.prims
    for i, p in enumerate(prims):                       # box = white rect, 0.6 pen, then its text lines
        if (p.kind == "poly" and p.closed and _close(p.fill, (1, 1, 1)) and _close(p.stroke, (0, 0, 0))
                and abs(p.lw - 0.6) < 0.01 and prims[i + 1].kind == "text"):
            n = 1                                       # a narrow module wraps the text: any number of lines
            while i + n < len(prims) and prims[i + n].kind == "text":
                n += 1
            del prims[i:i + n]
            break
    for p in prims:
        if p.layer == "MANHOLES" and _close(p.fill, (1, 1, 1)):
            p.stroke = (1.0, 1.0, 1.0)


# ---------------------------------------------------------------------------- recording / scale choice
def record_view(data, view, u, native_dims=True):
    """Run the PDF drawing code for one view with ``u`` mm per point; returns the Recorder."""
    rec = Recorder(layer_of)
    s = 1.0 / u                                         # points per mm, as the PDF code expects
    with _patched(u, native_dims):
        if view is None:
            plan_view.draw_plan_view(rec, data, 0.0, 0.0, s)
            _tidy_plan(rec)
        else:
            elevation_view.draw_elevation_view(rec, data, 0.0, 0.0, s, view=view, span_dim=True)
    return rec


def max_annotation_unit(data):
    """Largest mm-per-point at which the PDF code still draws true-size geometry.

    The PDF clamps a few things to a minimum number of points: excavation margin (12 pt), geofab
    extension (8 pt), pipe height (4 pt).  Above these limits the DXF would show them oversize."""
    cap = min(525 / 12.0, 500 / 8.0)
    for p in data["pipes"]:
        if p["diameter"] > 0:
            cap = min(cap, p["diameter"] / 4.0)
    return cap


def choose_plot_scale(data, view, native_dims=True):
    """(N, sheet name, paper size mm) - the largest drawing that fits the smallest sheet, true geometry kept."""
    cap = max_annotation_unit(data)
    options = [n for n in PLOT_SCALES if n * PT_MM <= cap] or [PLOT_SCALES[0]]
    size = {}
    for n in options:
        x0, y0, x1, y1 = bounds(record_view(data, view, n * PT_MM, native_dims), stringWidth)
        size[n] = ((x1 - x0) * PT_MM, (y1 - y0) * PT_MM)
    for name, w, h in SHEETS:
        for n in options:
            pw, ph = size[n]
            if pw <= w - SHEET_MARGIN[0] and ph <= h - SHEET_MARGIN[1]:
                return n, name, size[n]
    n = options[-1]
    return n, "A0+", size[n]


# ---------------------------------------------------------------------------- DXF writing
def _form_units():
    return {FACE_FORM: ((cube_art.WIDTH, cube_art.HEIGHT), (bridge.CUBE_MM, bridge.LAYER_MM)),
            CUBE_FORM: ((1.0, 1.0), (bridge.CUBE_MM, bridge.CUBE_MM))}


VIEW_TITLE = {None: "PLAN VIEW", "front": "FRONT ELEVATION", "back": "BACK ELEVATION",
              "left": "LEFT ELEVATION", "right": "RIGHT ELEVATION"}


def export_view(data, name, view, path, native_dims=True):
    """Write one view as its own DXF. Returns a dict describing the file."""
    n, sheet, paper = choose_plot_scale(data, view, native_dims)
    u = n * PT_MM
    rec = record_view(data, view, u, native_dims)
    x0, y0, x1, y1 = bounds(rec, stringWidth)

    doc = new_document(LAYERS)
    Emitter(doc, u, form_units=_form_units()).emit(rec)

    # title strip under the drawing - the PDF title-block content that belongs to this view
    h = 7 * CAP_HEIGHT * u
    lines = [f"{VIEW_TITLE[view]}  |  MODEL UNITS: mm (1:1)  |  PLOT 1:{n} ON {sheet}"]
    lines += [t for t in data["project_lines"] if t][:3]
    lines += data["title_lines"]
    lines += [f"DWG No. {data['dwg_no']}" if data["dwg_no"] else "", f"DRAWN {data['drawn_by']}  {data['drawn_date']}"]
    lines = [t for t in lines if t]
    bottom = y0 * u - 30 * u
    add_text_lines(doc.modelspace(), x0 * u, bottom, lines, h, "TITLE")

    top = y1 * u
    ext = (x0 * u, (bottom - len(lines) * h * 1.6), x1 * u, top)
    doc.set_modelspace_vport(height=(ext[3] - ext[1]) * 1.15,
                             center=((ext[0] + ext[2]) / 2, (ext[1] + ext[3]) / 2))
    errors = doc.audit().errors
    if errors:
        raise ValueError(f"DXF audit failed for {path}: {errors}")
    doc.saveas(path)
    if ezdxf.readfile(path).audit().errors:
        raise ValueError(f"DXF read-back audit failed for {path}")
    return {"file": path.name, "view": VIEW_TITLE[view], "plot_scale": f"1:{n}", "sheet": sheet,
            "paper_mm": [round(paper[0]), round(paper[1])], "mm_per_pt": round(u, 3)}


def export_views(data, out_dir, native_dims=True):
    from pathlib import Path
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    infos = []
    for name, view in VIEWS:
        info = export_view(data, name, view, out_dir / f"{name}.dxf", native_dims)
        infos.append(info)
        print(f"Saved: {out_dir / info['file']}  (plot 1:{info['plot_scale'][2:]} on {info['sheet']})")
    return infos
