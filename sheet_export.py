"""One DXF with the PDF's sheets 1-4: general arrangement (plan + front elevation, parts list, site level box, notes),
then back, left and right elevation. Each sheet is the PDF page itself (frame, title block, tables, views) run through
``dxf_canvas.Recorder`` - the PDF's section and bill-of-materials sheets are not drawn.

Model space is 1:1 in mm: the views are true size and a sheet is its A3 frame x N, so it plots at 1:N on A3. All four
sheets share one standard N - the smallest that the busiest sheet (the general arrangement) still fits on A3 - so the
frames are identical; they lie in a column, sheet 1 at the top, sheet 4 at the bottom.
"""
import types
from contextlib import ExitStack
from unittest import mock

import ezdxf

import pdfgen_bridge  # noqa: F401  (puts generator/ on sys.path: the PDF's sheet code lives there)
import main as pdf_main
import page1 as pdf_page1
import view_export as ve
from dxf_canvas import PT_MM, Emitter, Recorder, new_document

SHEETS = (("ga", "GENERAL ARRANGEMENT"), ("back", "BACK ELEVATION"), ("left", "LEFT ELEVATION"),
          ("right", "RIGHT ELEVATION"))
SCALES = (10, 20, 25, 30, 40, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 750, 1000)
SHEET_LAYERS = [("FRAME", 7), ("TITLE_BLOCK", 7), ("TABLES", 7)]
LAYER_OF = {"draw_page_border": "FRAME", "draw_tolerance_bar": "TITLE_BLOCK", "draw_rev_table": "TITLE_BLOCK",
            "draw_client_col": "TITLE_BLOCK", "draw_confidential": "TITLE_BLOCK",
            "draw_signatures": "TITLE_BLOCK", "draw_project_info": "TITLE_BLOCK"}


def _record(data, kind, number, n=None):
    """The PDF code for one sheet, recorded. n = plot scale 1:n (None: the PDF's own scale).
    Returns (Recorder, the scale in pt per mm the PDF layout wanted)."""
    wanted = []
    cap = 1 / (n * PT_MM) if n else None

    def scale_fn(fn):                                    # GA sheet: remember the PDF's scale, then cap it
        def wrapper(*a, **k):
            s = fn(*a, **k)
            wanted.append(s)
            return min(s, cap) if cap else s
        return wrapper

    def elevation_page(*a):
        wanted.append(orig_elevation_page(*a, max_s=cap or 0.10))
        return wanted[-1]

    def plan_view(c, *a, **k):                           # as plan_view.dxf: no centre info box
        start = len(c.prims)
        orig_plan_view(c, *a, **k)
        tail = types.SimpleNamespace(prims=c.prims[start:])
        ve._tidy_plan(tail)
        c.prims[start:] = tail.prims

    orig_elevation_page, orig_plan_view = pdf_main.draw_elevation_page, pdf_page1.draw_plan_view
    rec = Recorder(ve.layer_of)
    with ExitStack() as patches:
        patches.enter_context(ve._patched((n or 1) * PT_MM))
        put = lambda mod, name, fn: patches.enter_context(mock.patch.object(mod, name, fn))
        put(pdf_page1, "_stack_scale", scale_fn(pdf_page1._stack_scale))
        put(pdf_page1, "_side_scale", scale_fn(pdf_page1._side_scale))
        put(pdf_page1, "Canvas", lambda _stream: Recorder())          # _measure_elev draws on a scratch canvas
        put(pdf_page1, "draw_plan_view", plan_view)
        put(pdf_main, "draw_elevation_page", elevation_page)
        put(pdf_page1, "_draw_column", ve._forced(pdf_page1._draw_column, "TABLES"))
        for name, layer in LAYER_OF.items():
            put(pdf_main, name, ve._forced(getattr(pdf_main, name), layer))
        dd = dict(data, scale=f"1:{n}" if n else data["scale"])
        pdf_main.draw_full_page(rec, kind, number, len(SHEETS), dd)
    return rec, max(wanted)


def _standard_scale(wanted):
    """Smallest standard 1:N whose drawing is no bigger than what the PDF layout fitted onto A3."""
    return next((n for n in SCALES if n * PT_MM >= 1 / wanted), SCALES[-1])


def export_sheets(data, path):
    """Write the four sheets into one DXF. Returns a dict describing the file (for manifest.json)."""
    n = max(_standard_scale(_record(data, kind, number)[1]) for number, (kind, _) in enumerate(SHEETS, 1))
    u = n * PT_MM
    pw, ph = pdf_main.PW * u, pdf_main.PH * u                          # the A3 frame in model space, mm
    gap = 0.1 * pw
    height = len(SHEETS) * ph + (len(SHEETS) - 1) * gap

    doc = new_document(ve.LAYERS + SHEET_LAYERS)
    emit = Emitter(doc, u, form_units=ve._form_units())                 # one emitter: shared block definitions
    sheets = []
    for k, (kind, content) in enumerate(SHEETS):
        y = (len(SHEETS) - 1 - k) * (ph + gap)
        emit.origin = (0.0, -y / u)                                      # the sheet's lower-left corner -> (0, y)
        emit.emit(_record(data, kind, k + 1, n)[0])
        sheets.append({"sheet": f"{k + 1} OF {len(SHEETS)}", "content": content, "plot_scale": f"1:{n}",
                       "size": "A3", "frame_mm": [round(pw), round(ph)], "origin_mm": [0, round(y)]})
    doc.header["$EXTMIN"], doc.header["$EXTMAX"] = (0, 0, 0), (pw, height, 0)
    doc.set_modelspace_vport(height=height * 1.05, center=(pw / 2, height / 2))

    if doc.audit().errors:
        raise ValueError(f"DXF audit failed for {path}: {doc.audit().errors}")
    doc.saveas(path)
    if ezdxf.readfile(path).audit().errors:
        raise ValueError(f"DXF read-back audit failed for {path}")
    return {"file": path.name, "sheets": sheets}
