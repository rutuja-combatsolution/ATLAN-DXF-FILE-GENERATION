"""PDF -> one DXF per diagram.

usage: python pdf_to_dxf.py input.pdf [out_dir] [--all]

Splits every page of the PDF into its separate diagrams (PLAN VIEW, FRONT ELEVATION, a picture, ...)
and writes each one as its own DXF (mm, lower-left corner at 0,0, ready to insert in AutoCAD).
Default output folder: <this folder>\\output\\<pdf name>\\

How diagrams are found (all from the PDF itself):
  * content repeated on every page (border, title block, logo) is page furniture and is dropped
  * a diagram starts at its big title text (>= 16 pt); everything drawn after it, up to the next
    title, belongs to it (the generator draws title first, so this is the PDF's own paint order)
  * a picture is its own diagram, together with anything drawn on top of it
  * a block with few lines/boxes and at least as many text items (tables, notes) is not a
    diagram; --all writes those too

Entities: LINE / LWPOLYLINE (Bezier arcs -> bulge arcs), HATCH, TEXT (Arial), IMAGE; big repeated
shapes (the cube artwork) become one BLOCK + INSERTs. PDF paint order is kept.
Raster pictures stay pictures: the PDF does not contain their vector source.
"""
import math, os, re, sys

import ezdxf
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from ezdxf.colors import rgb2int
from ezdxf.enums import TextEntityAlignment as Align

# =============== SETTINGS: edit these, then just run  python pdf_to_dxf.py  ===============
INPUT_PDF = r"D:\pdf gen\accurate_titleblock_fixed.pdf"    # <- PUT YOUR PDF FILE PATH HERE
OUTPUT_DIR = ""            # "" = <this folder>\output\<pdf name>\   or put a folder path here
WRITE_TABLES_TOO = False   # True = also write tables / notes as DXF (same as --all)
# (a path typed on the command line overrides INPUT_PDF / OUTPUT_DIR)
# ========================================================================================

K = 25.4 / 72              # PDF point -> mm
CAP = 0.716                # Arial cap height / em  (DXF text height = cap height)
TITLE_MIN_PT = 16          # text this big starts a new diagram
VALID_LWT = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120,
             140, 158, 200, 211)
BEZIER_STEPS = 12          # segments when a curve is not a circular arc
ARC_TOL = 0.02             # mm: a Bezier within this of a circular arc becomes a bulge arc
SAME_TOL = 0.02            # mm: two shapes closer than this are "the same" (block reuse)
DEDUPE_MIN_VERTS = 40
TABLE_MAX_PATHS = 40       # a block with more lines/boxes than this is a drawing, not a table


# ---------------------------------------------------------------------------- geometry
def _bezier_to_arc_bulge(p0, c1, c2, p3):
    """Bulge of the circular arc p0->p3 that this cubic Bezier is, else None (y-up coords)."""
    cx, cy = p3[0] - p0[0], p3[1] - p0[1]
    chord = math.hypot(cx, cy)
    if chord < 1e-9:
        return None
    t0 = (c1[0] - p0[0], c1[1] - p0[1])
    if math.hypot(*t0) < 1e-9:
        t0 = (c2[0] - p0[0], c2[1] - p0[1])
    phi = math.atan2(t0[0] * cy - t0[1] * cx, t0[0] * cx + t0[1] * cy)   # tangent -> chord
    if abs(phi) > math.radians(89):
        return None
    bulge = math.tan(phi / 2)
    mid = ((p0[0] + 3 * c1[0] + 3 * c2[0] + p3[0]) / 8, (p0[1] + 3 * c1[1] + 3 * c2[1] + p3[1]) / 8)
    s = chord / 2 * bulge                                  # sagitta, bulges to the right
    arc_mid = ((p0[0] + p3[0]) / 2 + cy / chord * s, (p0[1] + p3[1]) / 2 - cx / chord * s)
    return bulge if math.dist(mid, arc_mid) <= ARC_TOL else None


def build_subpaths(items, to_mm):
    """PDF path items -> [(vertices, bulges, closed)] in mm (y up)."""
    out, cur = [], None            # cur = [vertices, bulges(per segment)]

    def finish():
        nonlocal cur
        if cur and len(cur[0]) > 1:
            v, b, closed = cur[0], cur[1], False
            if math.dist(v[0], v[-1]) < 1e-6 and len(v) > 2:       # explicit closing point
                v, closed = v[:-1], True
            else:
                b = b + [0.0]
            out.append((v, b, closed))
        cur = None

    for it in items:
        kind = it[0]
        if kind in ("re", "qu"):
            finish()
            if kind == "re":
                r = it[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
            else:
                q = it[1]
                pts = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
            out.append(([to_mm(*p) for p in pts], [0.0] * 4, True))
            continue
        p0 = to_mm(it[1].x, it[1].y)
        if cur is None or math.dist(cur[0][-1], p0) > 1e-3:
            finish()
            cur = [[p0], []]
        if kind == "l":
            cur[0].append(to_mm(it[2].x, it[2].y))
            cur[1].append(0.0)
        elif kind == "c":
            c1, c2, p3 = (to_mm(it[i].x, it[i].y) for i in (2, 3, 4))
            bulge = _bezier_to_arc_bulge(p0, c1, c2, p3)
            if bulge is not None:
                cur[0].append(p3)
                cur[1].append(bulge)
            else:
                for i in range(1, BEZIER_STEPS + 1):
                    t, u = i / BEZIER_STEPS, 1 - i / BEZIER_STEPS
                    cur[0].append((u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p3[0],
                                   u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p3[1]))
                    cur[1].append(0.0)
    finish()
    return out


# ---------------------------------------------------------------------------- colours
def _rgb(c):
    if c is None:
        return None
    c = tuple(c)
    if len(c) == 1:
        return (c[0],) * 3
    if len(c) == 4:
        cc, m, y, k = c
        return ((1 - cc) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return c[:3]


def _colour_attr(rgb):
    """Black -> ACI 7 by layer (white on a dark CAD background, black on paper)."""
    if rgb is None or max(rgb) < 0.02:
        return {}
    return {"true_color": rgb2int(tuple(round(v * 255) for v in rgb))}


# ---------------------------------------------------------------------------- one DXF file
class DxfWriter:
    def __init__(self, out_path):
        self.out_path = out_path
        d = self.doc = ezdxf.new("R2010", units=ezdxf.units.MM)
        for name in ("LINES", "TEXT", "FILL", "IMAGE"):
            d.layers.add(name, color=7)
        for style, font in (("ARIAL", "arial.ttf"), ("ARIAL_BOLD", "arialbd.ttf"),
                            ("ARIAL_ITALIC", "ariali.ttf"), ("ARIAL_BOLDITALIC", "arialbi.ttf")):
            d.styles.add(style, font=font)
        self.msp = d.modelspace()
        self.linetypes, self.shapes, self.n_blocks = set(), {}, 0
        self.counts = dict(path=0, text=0, image=0, insert=0)

    def _line_attr(self, st):
        a = {"layer": "LINES", **_colour_attr(st["stroke"])}
        a["lineweight"] = min(VALID_LWT, key=lambda w: abs(w - (st["lw"] or 0) * K * 100))
        if st["dash"]:
            arr = list(st["dash"]) * (2 if len(st["dash"]) % 2 else 1)
            name = "DASH_" + "_".join(f"{v:g}" for v in arr)
            if name not in self.linetypes:
                pat = [sum(arr) * K] + [(v if i % 2 == 0 else -v) * K for i, v in enumerate(arr)]
                self.doc.linetypes.add(name, pattern=pat)
                self.linetypes.add(name)
            a["linetype"] = name
        return a

    def _emit(self, layout, subs, st):
        if st["fill"] is not None:
            h = layout.add_hatch(dxfattribs={"layer": "FILL"})
            if max(st["fill"]) < 0.02:
                h.set_solid_fill(color=7, style=0)
            else:
                h.set_solid_fill(rgb=tuple(round(v * 255) for v in st["fill"]), style=0)
            for v, b, _ in subs:
                if len(v) >= 3 or any(b):
                    h.paths.add_polyline_path([(x, y, bu) for (x, y), bu in zip(v, b)], is_closed=True)
        if st["stroke"] is not None:
            attr = self._line_attr(st)
            for v, b, closed in subs:
                if len(v) == 2 and not closed and not any(b):
                    layout.add_line(v[0], v[1], dxfattribs=attr)
                elif len(v) >= 2:
                    layout.add_lwpolyline([(x, y, bu) for (x, y), bu in zip(v, b)],
                                          format="xyb", close=closed, dxfattribs=attr)

    def path(self, d, to_mm):
        subs = build_subpaths(d["items"], to_mm)
        if not subs:
            return
        t = d["type"]
        dashes = [float(x) for x in re.findall(r"[-\d.]+", (d.get("dashes") or "").split("]")[0])]
        st = dict(fill=_rgb(d.get("fill")) if "f" in t else None,
                  stroke=(_rgb(d.get("color")) or (0, 0, 0)) if "s" in t else None,
                  lw=d.get("width") or 0, dash=tuple(dashes) or None)
        self.counts["path"] += 1
        if sum(len(v) for v, _, _ in subs) < DEDUPE_MIN_VERTS:
            return self._emit(self.msp, subs, st)

        # big shape: reuse a block when an identical one (at any position) was already written
        xy = np.array([p for v, _, _ in subs for p in v])
        bl = np.array([b for _, bs, _ in subs for b in bs])
        lo = xy.min(axis=0)
        rel = xy - lo
        key = (tuple(len(v) for v, _, _ in subs), tuple(c for _, _, c in subs),
               tuple(None if x is None else tuple(round(c, 2) for c in x) for x in (st["fill"], st["stroke"])),
               round(st["lw"], 2), st["dash"])
        name = None
        for cand, cxy, cbl in self.shapes.get(key, []):
            if np.abs(cxy - rel).max() <= SAME_TOL and np.abs(cbl - bl).max() <= 1e-3:
                name = cand
                break
        if name is None:
            name = f"SHAPE_{self.n_blocks}"
            self.n_blocks += 1
            blk = self.doc.blocks.new(name)
            self._emit(blk, [([(x - lo[0], y - lo[1]) for x, y in v], b, c) for v, b, c in subs], st)
            self.shapes.setdefault(key, []).append((name, rel, bl))
        self.msp.add_blockref(name, (float(lo[0]), float(lo[1])), dxfattribs={"layer": "FILL"})
        self.counts["insert"] += 1

    def text(self, s, to_mm):
        string = "".join(chr(c[0]) for c in s["chars"])
        ox, oy = s["chars"][0][2]
        dx, dy = s["dir"]
        font = s["font"]
        bold, ital = "Bold" in font or bool(s["flags"] & 16), "Oblique" in font or "Italic" in font
        style = {(0, 0): "ARIAL", (1, 0): "ARIAL_BOLD", (0, 1): "ARIAL_ITALIC",
                 (1, 1): "ARIAL_BOLDITALIC"}[(bold, ital)]
        t = self.msp.add_text(string, height=s["size"] * K * CAP,
                              rotation=math.degrees(math.atan2(-dy, dx)),
                              dxfattribs={"layer": "TEXT", "style": style,
                                          **_colour_attr(_rgb(s["color"]))})
        t.set_placement(to_mm(ox, oy), align=Align.LEFT)
        self.counts["text"] += 1

    def image(self, filename, size_px, bbox, to_mm):
        x0, y0, x1, y1 = bbox
        idef = self.doc.add_image_def(filename=filename, size_in_pixel=size_px, name=filename)
        self.msp.add_image(idef, insert=to_mm(x0, y1), size_in_units=((x1 - x0) * K, (y1 - y0) * K),
                           dxfattribs={"layer": "IMAGE"})
        self.counts["image"] += 1

    def save(self):
        errs = self.doc.audit().errors
        self.doc.saveas(self.out_path)
        return len(errs)


# ---------------------------------------------------------------------------- PDF -> diagrams
class Op:
    __slots__ = ("seq", "kind", "obj", "bbox", "key")

    def __init__(self, seq, kind, obj, bbox, key):
        self.seq, self.kind, self.obj, self.bbox, self.key = seq, kind, obj, tuple(bbox), key


def collect(page):
    ops = []
    for d in page.get_drawings():
        r = d["rect"]
        ops.append(Op(d["seqno"], "path", d, (r.x0, r.y0, r.x1, r.y1),
                      ("p", round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1), d["type"], len(d["items"]))))
    for s in page.get_texttrace():
        txt = "".join(chr(c[0]) for c in s["chars"])
        if s["type"] == 3 or not txt.strip():
            continue
        ox, oy = s["chars"][0][2]
        ops.append(Op(s["seqno"], "text", s, s["bbox"], ("t", re.sub(r"\d", "#", txt), round(ox, 1), round(oy, 1))))
    ops.sort(key=lambda o: o.seq)
    return ops


def union(ops):
    return (min(o.bbox[0] for o in ops), min(o.bbox[1] for o in ops),
            max(o.bbox[2] for o in ops), max(o.bbox[3] for o in ops))


def slug(text, fallback):
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s or fallback


def export_image(pdf, xref, dest_base):
    """Write picture `xref` next to the DXF; returns (file name, (w, h))."""
    ex = pdf.extract_image(xref)
    if ex and not ex.get("smask") and ex["ext"] in ("png", "jpeg", "jpg"):
        fname = f"{dest_base}.{ex['ext']}"
        with open(fname, "wb") as f:
            f.write(ex["image"])
        return os.path.basename(fname), (ex["width"], ex["height"])
    pix = fitz.Pixmap(pdf, xref)
    if ex and ex.get("smask"):
        pix = fitz.Pixmap(pix, fitz.Pixmap(pdf, ex["smask"]))
    if pix.colorspace is not None and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    fname = f"{dest_base}.png"
    if pix.alpha:
        # fully transparent pixels -> white, so a viewer that ignores alpha shows paper white
        a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n).copy()
        a[a[..., -1] == 0, :-1] = 255
        Image.fromarray(a, "RGBA").save(fname)
    else:
        pix.save(fname)
    return os.path.basename(fname), (pix.width, pix.height)


def convert(pdf_path, out_dir, include_all=False):
    pdf = fitz.open(pdf_path)
    os.makedirs(out_dir, exist_ok=True)
    n_pages = len(pdf)

    pages = [collect(p) for p in pdf]
    images = [[i for i in p.get_image_info(xrefs=True) if i.get("xref")] for p in pdf]

    # page furniture = identical on every page (border, title block, logo, ticks...)
    furniture = set()
    if n_pages > 1:
        cnt = {}
        for ops, imgs in zip(pages, images):
            for k in {o.key for o in ops} | {("i", i["xref"], round(i["bbox"][0]), round(i["bbox"][1])) for i in imgs}:
                cnt[k] = cnt.get(k, 0) + 1
        furniture = {k for k, c in cnt.items() if c >= n_pages}

    written = []
    for pno, page in enumerate(pdf, 1):
        H = page.rect.height
        ops = [o for o in pages[pno - 1] if o.key not in furniture]
        pics = [i for i in images[pno - 1]
                if ("i", i["xref"], round(i["bbox"][0]), round(i["bbox"][1])) not in furniture]

        # diagrams = (title, ops) groups; pictures first claim what is drawn on top of them
        groups = []                                              # (name, ops, picture_info|None)
        for k, im in enumerate(pics, 1):
            x0, y0, x1, y1 = im["bbox"]
            inside = [o for o in ops if x0 <= (o.bbox[0] + o.bbox[2]) / 2 <= x1 and y0 <= (o.bbox[1] + o.bbox[3]) / 2 <= y1]
            ops = [o for o in ops if o not in inside]
            groups.append((f"picture{k}" if len(pics) > 1 else "picture", inside, im))

        segs, cur, title = [], [], None                           # split by big title text
        for o in ops:
            if o.kind == "text" and o.obj["size"] >= TITLE_MIN_PT:
                if cur:
                    segs.append((title, cur))
                title, cur = "".join(chr(c[0]) for c in o.obj["chars"]), [o]
            else:
                cur.append(o)
        if cur:
            segs.append((title, cur))

        skipped = []
        for k, (title, seg) in enumerate(segs, 1):
            n_paths = sum(o.kind == "path" for o in seg)
            n_text = len(seg) - n_paths
            # tables / notes: few lines and boxes, at least as much text as lines
            diagram = n_paths > TABLE_MAX_PATHS or (n_paths > 0 and n_text < n_paths)
            if diagram or include_all:
                groups.append((slug(title, "other" if title is None else f"diagram{k}"), seg, None))
            else:
                skipped.append(title or "text/table block")

        for name, seg, pic in groups:
            if not seg and pic is None:
                continue
            allb = [o.bbox for o in seg] + ([tuple(pic["bbox"])] if pic else [])
            x0 = min(b[0] for b in allb); y1 = max(b[3] for b in allb)
            x1 = max(b[2] for b in allb); y0 = min(b[1] for b in allb)
            to_mm = lambda x, y, x0=x0, y1=y1: ((x - x0) * K, (y1 - y) * K)
            base = f"p{pno}_{name}"
            w = DxfWriter(os.path.join(out_dir, base + ".dxf"))
            if pic is not None:
                fname, size = export_image(pdf, pic["xref"], os.path.join(out_dir, base))
                w.image(fname, size, pic["bbox"], to_mm)
            for o in seg:
                (w.path if o.kind == "path" else w.text)(o.obj, to_mm)
            errs = w.save()
            written.append(dict(file=base + ".dxf", page=pno, pdf_bbox=(x0, y0, x1, y1),
                                counts=dict(w.counts), blocks=w.n_blocks, errors=errs))
        if skipped:
            print(f"  page {pno}: not a diagram, skipped: {skipped}")

    print(f"\nWrote {len(written)} DXF files to {out_dir}")
    print(f"{'file':<30}{'size (mm)':>14}  {'from page / position on sheet (mm)':<38}contents")
    for r in written:
        x0, y0, x1, y1 = r["pdf_bbox"]
        what = ", ".join(f"{v} {k}" for k, v in r["counts"].items() if v)
        print(f"{r['file']:<30}{(x1 - x0) * K:>7.0f} x {(y1 - y0) * K:<5.0f} "
              f"p{r['page']} x {x0 * K:>4.0f}-{x1 * K:<4.0f} y {y0 * K:>4.0f}-{y1 * K:<4.0f}   {what}"
              + (f" ({r['blocks']} shared shapes)" if r["blocks"] else "")
              + (f"  AUDIT ERRORS: {r['errors']}" if r["errors"] else ""))
    return written


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = args[0] if args else INPUT_PDF
    if not os.path.isfile(src):
        sys.exit(f"PDF not found: {src}\nSet INPUT_PDF at the top of pdf_to_dxf.py, or pass the path as an argument.")
    dst = args[1] if len(args) > 1 else (OUTPUT_DIR or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "output", os.path.splitext(os.path.basename(src))[0]))
    print(f"Converting {src}")
    convert(src, dst, include_all=WRITE_TABLES_TOO or "--all" in sys.argv)
