# data_mapper.py
# Turns the app payload (geometry / input / material) into the drawing_data dict
# every page and view reads. No PDF logic here - pure data mapping.
#
# INPUT  payload = {"geometry": {...}, "input": {...}, "material": {...},
#                   "project":  {...}}        <- "project" is optional (title block)
#
# Optional "project" keys: project_name | project_lines, dwg_no, customer_code,
# request_no, drawn_date, client_name, rev_history.
# Missing header values stay blank (drawn_date / rev default to today / "1").
#
# FIXED (not in any payload): drawn_by "R.R.", scale "N.T.S", size "A3",
# cube footprint 1150 mm, layer height 780 mm, excavation margin 525 mm per side.

import math
import os
import re
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
PAGE3_IMAGES_DIR = os.path.join(_HERE, "withdimension", "withdimension")

CUBE_MM = 1150            # plan footprint of one 1000L module
LAYER_MM = 780            # height of one full layer
EXC_MARGIN_MM = 525       # 500 clearance + 25 wrap, each side (ref: 31050 -> 32100)
PIPE_EDGE_MM = 10         # gap kept between a pipe moved onto its wall and the wall's end

# Sign convention of `horizontal_offset` (metres, measured from the wall centre).
# back/front walls and manholes: the app's front view puts + on the LEFT (so the plan and every
# elevation, which all read these coordinates, match its 3D front view).
# left/right walls: + is towards the back (top of plan).
OFFSET_RIGHT_POSITIVE = False
OFFSET_BACK_POSITIVE = True

STACK_LABEL = {0.5: "HALF STACK", 1: "SINGLE STACK", 1.5: "1.5 STACK",
               2: "DOUBLE STACK", 2.5: "2.5 STACK", 3: "TRIPLE STACK"}

# payload wall name -> side used by the plan view (top = back row, bottom = front row)
_PLAN_SIDE = {"back": "top", "top": "top", "front": "bottom", "bottom": "bottom",
              "left": "left", "right": "right"}


def fmt_rl(v: float) -> str:
    """12.2 -> '12.20', 11.315 -> '11.315', 100 -> '100.00' (>= 2 decimals, <= 3)."""
    s = f"{v:.3f}".rstrip("0")
    whole, _, frac = s.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def fmt_num(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _today() -> str:
    d = date.today()
    return f"{d.day}/{d.month:02d}/{d.year}"


def _pipe(p: dict, kind: str, length: float, width: float, base_rl: float) -> dict:
    default_side = "left" if kind == "INLET" else "right"
    side = _PLAN_SIDE.get(str(p.get("side") or default_side).lower(), default_side)
    off_mm = float(p.get("horizontal_offset") or 0.0) * 1000
    dia = float(p.get("diameter") or 0.0)
    il = float(p.get("invert_level") if p.get("invert_level") is not None else base_rl)

    if side in ("top", "bottom"):
        along = length / 2 + (off_mm if OFFSET_RIGHT_POSITIVE else -off_mm)
        wall = length
    else:
        along = width / 2 + (off_mm if OFFSET_BACK_POSITIVE else -off_mm)
        wall = width
    # the pipe must lie wholly on its wall: a wall too short for the offset (a long, one-cube-wide tank has
    # 1.15 m end walls) keeps it just inside the end instead of letting half of it hang off the tank
    lim = min(dia / 2 + PIPE_EDGE_MM, wall / 2)
    if not lim <= along <= wall - lim:
        if not 0.0 <= along <= wall:
            import warnings
            warnings.warn(f"{kind} {p.get('id', '')[:8]} on the {side} wall: horizontal_offset "
                          f"{off_mm / 1000:g} m is outside the {wall / 1000:g} m wall - moved inside it")
        along = min(max(along, lim), wall - lim)
    cell = along / CUBE_MM - 0.5            # fractional cube index whose centre is `along`

    return {
        "id": p.get("id", ""), "kind": kind, "side": side, "along": along,
        "panel_x": {"left": 0, "right": length / CUBE_MM - 1}.get(side, cell),
        "panel_y": {"bottom": 0, "top": width / CUBE_MM - 1}.get(side, cell),
        "diameter": dia, "il": il,
        "z": (il - base_rl) * 1000 + dia / 2,     # pipe centre above tank base, mm
    }


def _manhole_dims(kind: str, diameter) -> tuple:
    """(shape, width_mm, height_mm) from the app's type name, e.g. 'square_600x600',
    'circular_300', 'circular_600'; falls back to `diameter` (mm), then to a 600 circle."""
    s = re.fullmatch(r"square_(\d+)x(\d+)", kind)
    if s:
        return "square", float(s.group(1)), float(s.group(2))
    c = re.fullmatch(r"circular_(\d+)", kind)
    if c:
        return "circle", float(c.group(1)), float(c.group(1))
    dia = float(diameter or 600)
    return ("square" if kind.startswith("square") else "circle"), dia, dia


def _inside(pos: float, extent: float, size: float) -> float:
    """`pos` moved, if need be, so a feature `size` wide centred on it lies within 0..extent
    (centred when the tank is narrower than the feature)."""
    if extent <= size:
        return extent / 2
    return min(max(pos, size / 2), extent - size / 2)


def _manhole(m: dict, length: float, width: float, idx: int) -> dict:
    kind = str(m.get("manhole_type") or "circular_600")
    shape, w_mm, h_mm = _manhole_dims(kind, m.get("diameter"))
    off_mm = float(m.get("horizontal_offset") or 0) * 1000
    # the whole manhole stays inside the tank: on a one-cube-wide tank the app's default offset would put
    # its centre on the edge, with half the riser outside
    return {
        "id": m.get("id", ""),
        "x": _inside(length / 2 + (off_mm if OFFSET_RIGHT_POSITIVE else -off_mm), length, w_mm),
        "y": _inside(width / 2 + float(m.get("top_depth_offset") or 0) * 1000, width, h_mm),
        "shape": shape,
        "w_mm": w_mm, "h_mm": h_mm,          # true footprint: plan view, and riser width in the elevations
    }


def _parts_list(m: dict) -> list:
    rows = [("1000L MODULE - HALF CUBE", m.get("no_half_cubes")),
            ("1000L MODULE - SIDE PANEL FULL HEIGHT", m.get("no_side_plates")),
            ("1000L MODULE - SIDE PANEL HALF HEIGHT", m.get("no_half_side_plates")),
            ("SINGLE CONNECTOR", m.get("no_single_clips")),
            ("DOUBLE CONNECTOR", m.get("no_double_clips"))]
    rows = [(d, q) for d, q in rows if q]
    return [[str(i + 1), d, fmt_num(q), ""] for i, (d, q) in enumerate(rows)]


def _components(m: dict) -> list:
    rows = [("Atlan Cubes", "Material", m.get("no_half_cubes"), "Each"),
            ("Side Plates", "Material", m.get("no_side_plates"), "Each"),
            ("Half Side Plates", "Material", m.get("no_half_side_plates"), "Each"),
            ("Geotextile", "Material", m.get("no_non_woven_geotextile"), "m2"),
            ("Liner", "Material", m.get("liner_required"), "m2"),
            ("Single Clip", "Material", m.get("no_single_clips"), "Each"),
            ("Double Clip", "Material", m.get("no_double_clips"), "Each")]
    return [{"item": i, "category": c, "quantity": q, "unit": u} for i, c, q, u in rows if q]


_REQUIRED = {
    "geometry": ("stack_length", "cover_depth"),
    "input": ("layers_in_system", "fsl_user_input", "base_of_tank_level"),
    "material": ("cubes_long", "cubes_wide", "tank_storage"),
}


def _validate(payload: dict) -> None:
    missing = [f"{sec}.{key}" for sec, keys in _REQUIRED.items()
               for key in keys if (payload.get(sec) or {}).get(key) is None]
    if missing:
        raise ValueError("payload is missing: " + ", ".join(missing))


def build(payload: dict) -> dict:
    _validate(payload)
    g, inp, m = payload["geometry"], payload["input"], payload["material"]
    proj = payload.get("project") or {}

    cubes_long, cubes_wide = int(m["cubes_long"]), int(m["cubes_wide"])
    layers = float(inp["layers_in_system"])
    length, width = cubes_long * CUBE_MM, cubes_wide * CUBE_MM

    stack_h = float(g["stack_length"])
    full_rows = int(layers)
    rows_mm = [LAYER_MM] * full_rows
    if stack_h - LAYER_MM * full_rows > 1:                      # half layer on top
        rows_mm.append(stack_h - LAYER_MM * full_rows)

    fsl = float(inp["fsl_user_input"])
    base_rl = float(inp["base_of_tank_level"])
    cover = float(g["cover_depth"])
    top_rl = base_rl + stack_h / 1000

    storage = float(m["tank_storage"])
    stack_label = STACK_LABEL.get(layers, f"{layers:g} STACK")

    pipes = ([_pipe(p, "INLET", length, width, base_rl) for p in (m.get("inlet") or [])] +
             [_pipe(p, "OUTLET", length, width, base_rl) for p in (m.get("outlet") or [])])
    manholes = [_manhole(h, length, width, i) for i, h in enumerate(m.get("manhole") or [])]

    drawn_date = proj.get("drawn_date") or _today()
    if proj.get("project_lines"):
        project_lines = list(proj["project_lines"])
    else:
        project_lines = [proj.get("project_name", "")]

    # RL-style plan label: "5-CUBES ROW x 27-CUBES LONG"
    return {
        # ---- title block ------------------------------------------------------
        "customer_code": proj.get("customer_code", ""),
        "dwg_no":        proj.get("dwg_no", ""),
        "request_no":    proj.get("request_no", ""),
        "client_name":   proj.get("client_name", ""),
        "drawn_date":    drawn_date,
        "drawn_by":      "R.R.",
        "scale":         "N.T.S",
        "size":          "A3",
        "rev_history":   proj.get("rev_history") or [["1", drawn_date, "R.R.", "INITIAL RELEASE"]],
        "project_lines": project_lines,
        "title_lines": [
            "ATLAN CUBE",
            f"ATLAN CUBE 1000L MODULE ({stack_label})",
            f"{cubes_wide}-CUBES WIDE x {cubes_long}-CUBES LONG - {fmt_num(storage)}m3",
            "GENERAL ARRANGEMENT",
        ],

        # ---- tank geometry (mm) -----------------------------------------------
        "cubes_long": cubes_long, "cubes_wide": cubes_wide,
        "layers": layers, "stack_label": stack_label,
        "rows_mm": rows_mm, "stack_h": stack_h,
        "length": length, "width": width,
        "exc_length": length + 2 * EXC_MARGIN_MM,
        "exc_width": width + 2 * EXC_MARGIN_MM,
        "tank_storage": storage,

        # ---- levels -----------------------------------------------------------
        "fsl": fsl, "base_rl": base_rl, "top_rl": top_rl,
        "cover": cover, "exc_depth": cover + stack_h,

        # ---- pipework ---------------------------------------------------------
        "pipes": pipes, "manholes": manholes,

        # ---- tables / images --------------------------------------------------
        "parts_list": _parts_list(m),
        "components": _components(m),
        "section_image": os.path.join(PAGE3_IMAGES_DIR, f"{layers:g}stack.png"),
    }
