"""A stand-in for ``reportlab.pdfgen.canvas.Canvas`` that records drawing calls and writes them as DXF.

The PDF generator (``pdf gen/Internal/plan_view.py`` and ``elevation_view.py``) draws every view through a
handful of canvas calls (line, rect, circle, paths, text, forms ...).  Handing it a ``Recorder`` instead of
a PDF canvas gives the DXF export the *same* geometry, dimensions, callouts and arrows as the PDF, and any
future change to the PDF drawing code reaches the DXF automatically.

Coordinates arrive in PDF points; ``emit`` converts them to millimetres with ``u`` (mm per point).

Two steps:  ``Recorder``  collects primitives (no DXF library needed, so layouts can be measured)
            ``emit(...)`` writes them into an ``ezdxf`` document.
"""
import math
from contextlib import contextmanager

CAP_HEIGHT = 0.716                  # Arial / Helvetica cap height per em: DXF text height = cap height
PT_MM = 25.4 / 72                   # paper millimetres per PDF point
VALID_LWT = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120,
             140, 158, 200, 211)    # DXF lineweights in 1/100 mm


# ---------------------------------------------------------------------------- colours
def _rgb(c):
    """reportlab Color / (r, g, b) / name -> (r, g, b) floats 0..1."""
    if c is None:
        return None
    if hasattr(c, "red"):
        return (float(c.red), float(c.green), float(c.blue))
    if isinstance(c, (tuple, list)):
        return tuple(float(v) for v in c[:3])
    from reportlab.lib.colors import toColor
    return _rgb(toColor(c))


def _is_white(rgb):
    return rgb is not None and min(rgb) > 0.98


def _is_black(rgb):
    return rgb is not None and max(rgb) < 0.02


_ACI = {(1, 0, 0): 1, (1, 1, 0): 2, (0, 1, 0): 3, (0, 1, 1): 4, (0, 0, 1): 5, (1, 0, 1): 6}


def _color_attr(rgb):
    """Black -> by layer (ACI 7, black on paper / white on a dark screen); pure primaries -> ACI."""
    if rgb is None or _is_black(rgb):
        return {}
    key = tuple(int(round(v)) for v in rgb)
    if all(abs(v - k) < 0.02 for v, k in zip(rgb, key)) and key in _ACI:
        return {"color": _ACI[key]}
    return {"true_color": (round(rgb[0] * 255) << 16) | (round(rgb[1] * 255) << 8) | round(rgb[2] * 255)}


# ---------------------------------------------------------------------------- recording
class _State:
    __slots__ = ("stroke", "fill", "lw", "dash", "font", "ctm")

    def __init__(self):
        self.stroke, self.fill = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        self.lw, self.dash, self.font = 1.0, None, ("Helvetica", 10.0)
        self.ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def copy(self):
        s = _State()
        for k in self.__slots__:
            setattr(s, k, getattr(self, k))
        return s


class Prim:
    """One recorded drawing primitive (all coordinates already through the CTM, in points)."""
    __slots__ = ("kind", "layer", "pts", "closed", "stroke", "fill", "lw", "dash", "extra")

    def __init__(self, kind, layer, pts, closed=False, stroke=None, fill=None, lw=1.0, dash=None, **extra):
        self.kind, self.layer, self.pts, self.closed = kind, layer, pts, closed
        self.stroke, self.fill, self.lw, self.dash, self.extra = stroke, fill, lw, dash, extra


class _Path:
    """reportlab PDFPathObject look-alike (moveTo / lineTo / close / rect)."""

    def __init__(self):
        self.subs = []          # [points, closed]

    def moveTo(self, x, y):
        self.subs.append([[(x, y)], False])

    def lineTo(self, x, y):
        if not self.subs:
            self.moveTo(x, y)
        else:
            self.subs[-1][0].append((x, y))

    def close(self):
        if self.subs:
            self.subs[-1][1] = True

    def rect(self, x, y, w, h):
        self.subs.append([[(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True])


class Form:
    def __init__(self, name, bbox):
        self.name, self.bbox, self.prims, self.lw = name, bbox, [], None


class Recorder:
    """Canvas look-alike.  ``layer_of(prim_kind, state)`` may name a layer; ``with rec.layer("X")`` forces one."""

    def __init__(self, layer_of=None):
        self.prims = []
        self.forms = {}
        self._st = _State()
        self._stack = []
        self._target = self.prims
        self._form_stack = []
        self._force = []
        self._layer_of = layer_of
        self.native_dims = []               # (see add_dim)

    # --- layers ------------------------------------------------------------------
    @contextmanager
    def layer(self, name):
        self._force.append(name)
        try:
            yield
        finally:
            self._force.pop()

    def _layer(self, kind):
        if self._force:
            return self._force[-1]
        return self._layer_of(kind, self._st) if self._layer_of else "0"

    # --- graphics state ------------------------------------------------------------
    def setStrokeColor(self, c, alpha=None):
        self._st.stroke = _rgb(c)

    def setFillColor(self, c, alpha=None):
        self._st.fill = _rgb(c)

    def setStrokeGray(self, g, alpha=None):
        self._st.stroke = (g, g, g)

    def setFillGray(self, g, alpha=None):
        self._st.fill = (g, g, g)

    def setStrokeColorRGB(self, r, g, b, alpha=None):
        self._st.stroke = (r, g, b)

    def setFillColorRGB(self, r, g, b, alpha=None):
        self._st.fill = (r, g, b)

    def setLineWidth(self, w):
        self._st.lw = float(w)

    def setLineCap(self, mode):
        pass

    def setLineJoin(self, mode):
        pass

    def setDash(self, array=(), phase=0):
        if isinstance(array, (int, float)):
            self._st.dash = (float(array), float(phase))
        else:
            self._st.dash = tuple(float(v) for v in array) or None

    def setFont(self, name, size, leading=None):
        self._st.font = (name, float(size))

    def saveState(self):
        self._stack.append(self._st.copy())

    def restoreState(self):
        if self._stack:
            self._st = self._stack.pop()

    def _concat(self, m):
        a, b, c, d, e, f = m
        A, B, C, D, E, F = self._st.ctm
        self._st.ctm = (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D,
                        e * A + f * C + E, e * B + f * D + F)

    def transform(self, a, b, c, d, e, f):
        self._concat((a, b, c, d, e, f))

    def translate(self, dx, dy):
        self._concat((1, 0, 0, 1, dx, dy))

    def scale(self, sx, sy):
        self._concat((sx, 0, 0, sy, 0, 0))

    def rotate(self, deg):
        r = math.radians(deg)
        self._concat((math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0))

    def _xy(self, x, y):
        a, b, c, d, e, f = self._st.ctm
        return (a * x + c * y + e, b * x + d * y + f)

    def _scale_factor(self):
        a, b, c, d, _, _ = self._st.ctm
        return math.sqrt(abs(a * d - b * c))

    # --- primitives ----------------------------------------------------------------
    def _add(self, prim):
        self._target.append(prim)

    def _style(self, stroke, fill):
        st = self._st
        return (st.stroke if stroke else None, st.fill if fill else None,
                st.lw * self._scale_factor(), st.dash)

    def line(self, x1, y1, x2, y2):
        s, _, lw, dash = self._style(1, 0)
        self._add(Prim("poly", self._layer("line"), [self._xy(x1, y1), self._xy(x2, y2)], False, s, None, lw, dash))

    def lines(self, lines):
        for ln in lines:
            self.line(*ln)

    def _poly(self, pts, closed, stroke, fill, kind="shape"):
        s, f, lw, dash = self._style(stroke, fill)
        if s is None and f is None:
            return
        self._add(Prim("poly", self._layer(kind), [self._xy(*p) for p in pts], closed, s, f, lw, dash))

    def rect(self, x, y, w, h, stroke=1, fill=0):
        self._poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True, stroke, fill, "rect")

    def roundRect(self, x, y, w, h, radius, stroke=1, fill=0):
        r = min(radius, w / 2, h / 2)
        pts = []
        for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0),
                           (x + r, y + h - r, 90), (x + r, y + r, 180)):
            for k in range(9):
                a = math.radians(a0 + 90 * k / 8)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self._poly(pts, True, stroke, fill, "rect")

    def circle(self, x, y, r, stroke=1, fill=0):
        s, f, lw, dash = self._style(stroke, fill)
        if s is None and f is None:
            return
        self._add(Prim("circle", self._layer("circle"), [self._xy(x, y)], True, s, f, lw, dash,
                       r=r * self._scale_factor()))

    def ellipse(self, x1, y1, x2, y2, stroke=1, fill=0):
        """reportlab signature: bounding-box corners. ponytail: 48-gon, a true ELLIPSE entity if smoothness matters."""
        cx, cy, rx, ry = (x1 + x2) / 2, (y1 + y2) / 2, abs(x2 - x1) / 2, abs(y2 - y1) / 2
        self._poly([(cx + rx * math.cos(a), cy + ry * math.sin(a))
                    for a in (2 * math.pi * k / 48 for k in range(48))], True, stroke, fill, "shape")

    def beginPath(self):
        return _Path()

    def drawPath(self, path, stroke=1, fill=0, fillMode=None):
        s, f, lw, dash = self._style(stroke, fill)
        if s is None and f is None:
            return
        subs = [([self._xy(*p) for p in pts], closed) for pts, closed in path.subs if len(pts) > 1]
        if not subs:
            return
        self._add(Prim("path", self._layer("path"), subs, False, s, f, lw, dash))

    def _text(self, x, y, s, align):
        name, size = self._st.font
        a, b, _, _, _, _ = self._st.ctm
        sc = self._scale_factor()
        self._add(Prim("text", self._layer("text"), [self._xy(x, y)], False, self._st.fill, None, 0, None,
                       text=str(s), font=name, size=size * sc, align=align, rot=math.degrees(math.atan2(b, a))))

    def drawString(self, x, y, text, **kw):
        self._text(x, y, text, "l")

    def drawCentredString(self, x, y, text, **kw):
        self._text(x, y, text, "c")

    def drawRightString(self, x, y, text, **kw):
        self._text(x, y, text, "r")

    # --- forms (reusable artwork -> DXF blocks) --------------------------------------
    def hasForm(self, name):
        return name in self.forms

    def beginForm(self, name, lowerx=None, lowery=None, upperx=None, uppery=None):
        form = Form(name, (lowerx, lowery, upperx, uppery))
        self.forms[name] = form
        self._form_stack.append((self._target, self._st, self._stack))
        self._target, self._st, self._stack = form.prims, _State(), []

    def endForm(self):
        self._target, self._st, self._stack = self._form_stack.pop()

    def doForm(self, name):
        form = self.forms[name]
        self._add(Prim("insert", self._layer("insert"), [], False, None, None, 0, None,
                       form=name, ctm=self._st.ctm))

    # --- native dimension (written as a DIMENSION entity) --------------------------------
    def add_dim(self, p1, p2, base, angle, text, size, arrow, ext, gap):
        """p1, p2: measured points; base: a point on the dimension line (all in the current CTM space)."""
        self._add(Prim("dim", self._layer("dim"), [self._xy(*p1), self._xy(*p2), self._xy(*base)], False,
                       self._st.stroke, None, self._st.lw, None, angle=angle, text=text,
                       size=size, arrow=arrow, ext=ext, gap=gap))


# ---------------------------------------------------------------------------- measuring
def bounds(rec, string_width=None):
    """(x0, y0, x1, y1) of everything recorded, in points."""
    xs, ys = [], []

    def add(p):
        xs.append(p[0])
        ys.append(p[1])

    for pr in rec.prims:
        if pr.kind == "poly":
            for p in pr.pts:
                add(p)
        elif pr.kind == "path":
            for pts, _ in pr.pts:
                for p in pts:
                    add(p)
        elif pr.kind == "circle":
            cx, cy = pr.pts[0]
            r = pr.extra["r"]
            add((cx - r, cy - r))
            add((cx + r, cy + r))
        elif pr.kind == "text":
            x, y = pr.pts[0]
            w = (string_width(pr.extra["text"], pr.extra["font"], pr.extra["size"])
                 if string_width else len(pr.extra["text"]) * pr.extra["size"] * 0.55)
            x0 = {"l": 0, "c": -w / 2, "r": -w}[pr.extra["align"]]
            h = pr.extra["size"]
            r = math.radians(pr.extra["rot"])
            for dx, dy in ((x0, -0.2 * h), (x0 + w, h)):
                add((x + dx * math.cos(r) - dy * math.sin(r), y + dx * math.sin(r) + dy * math.cos(r)))
        elif pr.kind == "insert":
            form = rec.forms[pr.extra["form"]]
            lx, ly, ux, uy = form.bbox
            a, b, c, d, e, f = pr.extra["ctm"]
            for fx, fy in ((lx, ly), (ux, ly), (ux, uy), (lx, uy)):
                add((a * fx + c * fy + e, b * fx + d * fy + f))
        elif pr.kind == "dim":
            for p in pr.pts:
                add(p)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------- DXF output
STYLES = (("ARIAL", "arial.ttf"), ("ARIAL_BOLD", "arialbd.ttf"),
          ("ARIAL_ITALIC", "ariali.ttf"), ("ARIAL_BOLDITALIC", "arialbi.ttf"))


def new_document(layers=()):
    """R2010 DXF in millimetres with the project's text styles and the given (name, aci colour) layers."""
    import ezdxf
    doc = ezdxf.new("R2010", units=ezdxf.units.MM)
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LWDISPLAY"] = 1
    for style, font in STYLES:
        doc.styles.add(style, font=font)
    for name, color in layers:
        doc.layers.add(name, color=color)
    return doc


def add_text_lines(msp, x, y, lines, height, layer="TITLE", spacing=1.6, style="ARIAL"):
    """Left-aligned lines going downwards from baseline y; returns the y below the last line."""
    from ezdxf.enums import TextEntityAlignment as A
    for i, text in enumerate(lines):
        msp.add_text(str(text), dxfattribs={"height": height, "layer": layer, "style": style}).set_placement(
            (x, y - i * height * spacing), align=A.LEFT)
    return y - len(lines) * height * spacing


def _lineweight(lw_pt):
    want = lw_pt * PT_MM * 100
    return min(VALID_LWT, key=lambda w: abs(w - want))


class Emitter:
    """Writes a ``Recorder``'s primitives into an ezdxf modelspace.

    u            mm per PDF point
    origin       (x, y) in points that becomes (0, 0) in the DXF
    form_units   {form name: ((unit_w, unit_h), (mm_w, mm_h))}  block geometry is rescaled to real size
    """

    def __init__(self, doc, u, origin=(0.0, 0.0), form_units=None, block_layer="0"):
        self.doc, self.msp = doc, doc.modelspace()
        self.u, self.origin = u, origin
        self.form_units = form_units or {}
        self.block_layer = block_layer
        self._linetypes = set()
        self._block_scale = {}

    # -- helpers
    def _pt(self, p):
        return ((p[0] - self.origin[0]) * self.u, (p[1] - self.origin[1]) * self.u)

    def _attr(self, pr, in_block=False, with_fill=False):
        a = {"layer": self.block_layer if in_block else pr.layer}
        src = pr.fill if with_fill else pr.stroke
        if in_block and with_fill:
            if src is not None:                      # keep exact tones inside artwork blocks
                a["true_color"] = (round(src[0] * 255) << 16) | (round(src[1] * 255) << 8) | round(src[2] * 255)
        else:
            a.update(_color_attr(src))
        if not with_fill:
            a["lineweight"] = -2 if in_block else _lineweight(pr.lw)
            if pr.dash:
                a["linetype"] = self._linetype(pr.dash)
        return a

    def _linetype(self, dash):
        arr = list(dash) * (2 if len(dash) % 2 else 1)
        name = "DASH_" + "_".join(f"{v * self.u:.0f}" for v in arr)
        if name not in self._linetypes and name not in self.doc.linetypes:
            pat = [sum(arr) * self.u] + [(v if i % 2 == 0 else -v) * self.u for i, v in enumerate(arr)]
            self.doc.linetypes.add(name, pattern=pat)
        self._linetypes.add(name)
        return name

    def _rings(self, pr):
        """Closed rings (mm points) of a filled primitive."""
        if pr.kind == "circle":
            cx, cy = self._pt(pr.pts[0])
            r = pr.extra["r"] * self.u
            return [[(cx - r, cy, 1.0), (cx + r, cy, 1.0)]]
        if pr.kind == "poly":
            return [[(*self._pt(p), 0.0) for p in pr.pts]]
        return [[(*self._pt(p), 0.0) for p in pts] for pts, _ in pr.pts if len(pts) > 2]

    # -- writers
    def write(self, prims, layout=None, block=None, rescale=None):
        """prims -> entities in ``layout`` (default modelspace). ``rescale`` = (sx, sy) for block content."""
        lay = layout if layout is not None else self.msp
        for pr in prims:
            if pr.kind == "insert":
                self._insert(pr, lay)
            elif pr.kind == "dim":
                self._dim(pr, lay)
            elif pr.kind == "text":
                self._text(pr, lay)
            else:
                self._shape(pr, lay, block is not None, rescale)

    def _shape(self, pr, lay, in_block, rescale):
        # fills first (so strokes stay visible), then outlines
        if pr.fill is not None:
            rings = self._rings_scaled(pr, in_block, rescale)
            small = (pr.kind in ("poly", "path") and len(rings) == 1 and len(rings[0]) in (3, 4) and
                     all(b == 0 for _, _, b in rings[0]))
            if _is_white(pr.fill) and not in_block:
                for ring in rings:                     # white = "background": wipe what lies below
                    lay.add_wipeout(self._ring_points(ring), dxfattribs={"layer": pr.layer})
            elif small:
                v = [(x, y) for x, y, _ in rings[0]]
                # SOLID corners run in a Z order (1, 2, 4, 3), not around the outline
                v = [v[0], v[1], v[2], v[2]] if len(v) == 3 else [v[0], v[1], v[3], v[2]]
                lay.add_solid(v, dxfattribs=self._attr(pr, in_block, True))
            else:
                h = lay.add_hatch(dxfattribs=self._attr(pr, in_block, True))
                if _is_black(pr.fill) and not in_block:
                    h.set_solid_fill(color=7)          # black fill follows the screen background
                else:
                    h.set_solid_fill(rgb=tuple(round(v * 255) for v in pr.fill))
                for ring in rings:
                    h.paths.add_polyline_path(ring, is_closed=True)
        if pr.stroke is None:
            return
        attr = self._attr(pr, in_block)
        if pr.kind == "circle":
            cx, cy = self._pt_scaled(pr.pts[0], in_block, rescale)
            r = pr.extra["r"] * self.u * (rescale[0] if rescale else 1)
            lay.add_circle((cx, cy), r, dxfattribs=attr)
        elif pr.kind == "poly":
            pts = [self._pt_scaled(p, in_block, rescale) for p in pr.pts]
            self._polyline(lay, pts, pr.closed, attr)
        else:
            for sub, closed in pr.pts:
                pts = [self._pt_scaled(p, in_block, rescale) for p in sub]
                self._polyline(lay, pts, closed, attr)

    def _polyline(self, lay, pts, closed, attr):
        if len(pts) == 2 and not closed:
            lay.add_line(pts[0], pts[1], dxfattribs=attr)
        elif len(pts) >= 2:
            lay.add_lwpolyline(pts, close=closed, dxfattribs=attr)

    def _pt_scaled(self, p, in_block, rescale):
        if in_block:
            sx, sy = rescale or (1, 1)
            return (p[0] * sx, p[1] * sy)
        return self._pt(p)

    def _rings_scaled(self, pr, in_block, rescale):
        if not in_block:
            return self._rings(pr)
        sx, sy = rescale or (1, 1)
        if pr.kind == "circle":
            cx, cy = pr.pts[0]
            r = pr.extra["r"]
            return [[(cx * sx - r * sx, cy * sy, 1.0), (cx * sx + r * sx, cy * sy, 1.0)]]
        if pr.kind == "poly":
            return [[(p[0] * sx, p[1] * sy, 0.0) for p in pr.pts]]
        return [[(p[0] * sx, p[1] * sy, 0.0) for p in pts] for pts, _ in pr.pts if len(pts) > 2]

    def _ring_points(self, ring):
        if len(ring) == 2 and ring[0][2]:               # circle given as two bulged vertices
            (x0, y0, _), (x1, y1, _) = ring
            cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) / 2
            return [(cx + r * math.cos(t * math.pi / 24), cy + r * math.sin(t * math.pi / 24)) for t in range(48)]
        return [(x, y) for x, y, _ in ring]

    def _text(self, pr, lay):
        text = pr.extra["text"]
        if not text.strip():
            return
        from ezdxf.enums import TextEntityAlignment as A
        bold = "Bold" in pr.extra["font"]
        ital = "Oblique" in pr.extra["font"] or "Italic" in pr.extra["font"]
        style = {(0, 0): "ARIAL", (1, 0): "ARIAL_BOLD", (0, 1): "ARIAL_ITALIC", (1, 1): "ARIAL_BOLDITALIC"}[(bold, ital)]
        attr = {"layer": pr.layer, "style": style, "height": pr.extra["size"] * CAP_HEIGHT * self.u,
                "rotation": pr.extra["rot"], **_color_attr(pr.stroke)}      # text colour = PDF fill colour
        t = lay.add_text(text, dxfattribs=attr)
        t.set_placement(self._pt(pr.pts[0]), align={"l": A.LEFT, "c": A.CENTER, "r": A.RIGHT}[pr.extra["align"]])

    def _insert(self, pr, lay):
        name = pr.extra["form"]
        form = self.rec.forms[name]
        if name not in self._block_scale:
            (uw, uh), (mw, mh) = self.form_units.get(name, ((1.0, 1.0), (1.0, 1.0)))
            self._block_scale[name] = (mw / uw, mh / uh)
            blk = self.doc.blocks.new(name)
            self.write(form.prims, layout=blk, block=blk, rescale=self._block_scale[name])
        sx, sy = self._block_scale[name]
        a, b, c, d, e, f = pr.extra["ctm"]
        sx_pt = math.hypot(a, b)
        sy_pt = math.hypot(c, d)
        # mm per form unit along each axis, divided by the block's own rescale
        xs, ys = sx_pt * self.u / sx, sy_pt * self.u / sy
        flip = (a * d - b * c) < 0
        rot = math.degrees(math.atan2(b, a))
        x, y = self._pt((e, f))
        attr = {"layer": pr.layer, "xscale": xs, "yscale": -ys if flip else ys, "rotation": rot}
        lw_form = max((p.lw for p in form.prims if p.stroke is not None), default=0.0)
        if lw_form:                       # the artwork's own pen scales with the form when it is drawn
            attr["lineweight"] = _lineweight(lw_form * math.sqrt(sx_pt * sy_pt))
        lay.add_blockref(name, (x, y), dxfattribs=attr)

    def _dim(self, pr, lay):
        p1, p2, base = (self._pt(p) for p in pr.pts)
        u = self.u
        ov = {"dimtxt": pr.extra["size"] * CAP_HEIGHT * u, "dimasz": pr.extra["arrow"] * u,
              "dimexo": 0, "dimexe": pr.extra["ext"] * u, "dimgap": pr.extra["gap"] * u,
              "dimtad": 1, "dimdec": 0, "dimclrd": 7, "dimclre": 7, "dimclrt": 7,
              "dimtih": 0, "dimtoh": 0, "dimtxsty": "ARIAL"}
        if not pr.extra["ext"]:                       # measured points lie on the dimension line itself
            ov.update(dimse1=1, dimse2=1)
        dim = lay.add_linear_dim(base=base, p1=p1, p2=p2, angle=pr.extra["angle"],
                                 text=pr.extra["text"] or "<>", dimstyle="Standard", override=ov,
                                 dxfattribs={"layer": pr.layer})
        dim.render()

    def emit(self, rec):
        self.rec = rec
        self.write(rec.prims)
