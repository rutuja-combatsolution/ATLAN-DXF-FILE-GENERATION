"""Payload JSON -> one combined 3D tank DXF (tank_3d.dxf): half cubes, side plates, pipes and manholes.

    python tank_3d.py payloads/01_double_13x3.json [output_dir]

The layout comes from the same mapped data as the five view DXFs (cube grid, layer heights, pipes, manholes).
Half cubes and side plates are the simplified GLB meshes in components/glb; pipes and manholes are generated at
the size the payload gives (pipe diameter, manhole type), not taken from a fixed-size GLB. Every part is written
once as a block of 3DFACEs and repeated as INSERTs, so the file stays small however many cubes there are.

Model space is mm, Z up, tank base at z = 0; x runs along the length, y along the width with the back wall at
y = width - the plan view's coordinates. Side plates and pipes sit outside that footprint.
"""
import argparse
import json
import math
import struct
from pathlib import Path

import ezdxf
import numpy as np

import dxf_canvas
import json_to_dxf

HERE = Path(__file__).resolve().parent
GLB_DIR = HERE / "components" / "glb"
CUBE_GLB = GLB_DIR / "ECOCUBE BOTTOM - SIMPLIFIED.glb"
PLATE_GLB = GLB_DIR / "ECOCUBE SIDE PANEL - SIMPLIFIED.glb"

LAYERS = [("TANK_MODULE", 8), ("TANK_SIDE_PLATE", 9), ("TANK_TOP_PLATE", 9),
          ("PIPES_INLET", 1), ("PIPES_OUTLET", 5), ("MANHOLES", 4)]

PIPE_STUB = 450          # mm a pipe sticks out beyond the side plate (schematic, as in the 2D views)
LID_T, LID_OVERHANG = 100, 40       # manhole lid: class D lid thickness; extra each side of the riser
SEGMENTS = 32            # facets round a circular riser or pipe

_COMPONENT_TYPES = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
_COMPONENTS = {"SCALAR": 1, "VEC3": 3}


# ---------------------------------------------------------------------------- GLB
def load_glb(path):
    """Every triangle of a .glb as an (n, 3, 3) array in metres, glTF axes (Y up), node transforms applied."""
    raw = Path(path).read_bytes()
    json_len = struct.unpack_from("<I", raw, 12)[0]
    gltf = json.loads(raw[20:20 + json_len])
    blob = raw[28 + json_len:]                              # BIN chunk data follows its 8-byte header

    def read(i):
        acc = gltf["accessors"][i]
        view = gltf["bufferViews"][acc["bufferView"]]
        dtype, n = np.dtype(_COMPONENT_TYPES[acc["componentType"]]), _COMPONENTS[acc["type"]]
        size, count = dtype.itemsize * n, acc["count"]
        stride = view.get("byteStride", size)               # position / normal / uv may share one interleaved buffer
        buf = np.frombuffer(blob, np.uint8, (count - 1) * stride + size, view.get("byteOffset", 0) + acc.get("byteOffset", 0))
        rows = np.lib.stride_tricks.as_strided(buf, (count, size), (stride, 1))
        return rows.copy().view(dtype).reshape(-1, n)

    def local(node):
        if "matrix" in node:
            return np.array(node["matrix"], float).reshape(4, 4).T
        x, y, z, w = node.get("rotation", (0, 0, 0, 1))
        m = np.eye(4)
        m[:3, :3] = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                              [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                              [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]) * node.get("scale", (1, 1, 1))
        m[:3, 3] = node.get("translation", (0, 0, 0))
        return m

    tris = []

    def walk(i, parent):
        node = gltf["nodes"][i]
        m = parent @ local(node)
        for prim in gltf["meshes"][node["mesh"]]["primitives"] if "mesh" in node else ():
            pos = read(prim["attributes"]["POSITION"]).astype(float)
            idx = read(prim["indices"]).ravel() if "indices" in prim else np.arange(len(pos))
            tris.append((np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3][idx].reshape(-1, 3, 3))
        for child in node.get("children", ()):
            walk(child, m)

    for root in gltf["scenes"][gltf.get("scene", 0)]["nodes"]:
        walk(root, np.eye(4))
    return np.concatenate(tris)


def to_cad_mm(tris):
    """glTF metres (Y up) -> CAD mm (Z up)."""
    return np.stack([tris[..., 0], -tris[..., 2], tris[..., 1]], axis=-1) * 1000


def mesh_faces(tris):
    """(points, hidden-edge mask) per triangle. An edge shared with a coplanar triangle is hidden, so the
    wireframe shows the part's outline and features, not the triangulation."""
    _, ids = np.unique(np.round(tris.reshape(-1, 3), 2), axis=0, return_inverse=True)
    ids = ids.reshape(-1, 3)
    normal = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    shared = {}
    for t in range(len(ids)):
        for k in range(3):                                  # 3DFACE edge bits of a triangle: 1, 2, 8
            a, b = ids[t, k], ids[t, (k + 1) % 3]
            shared.setdefault((min(a, b), max(a, b)), []).append((t, (1, 2, 8)[k]))
    hidden = np.zeros(len(ids), int)
    for pair in shared.values():
        if len(pair) == 2 and normal[pair[0][0]] @ normal[pair[1][0]] > 0.9999:
            for t, bit in pair:
                hidden[t] |= bit
    return [(tuple(map(tuple, tri)), int(h)) for tri, h in zip(tris, hidden)]


# ---------------------------------------------------------------------------- generated parts
def prism(poly, z0, z1, smooth=False):
    """Closed prism over a convex outline; `smooth` hides the vertical edges of a round one."""
    n = len(poly)
    cx, cy = sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n
    faces = [(((*poly[k], z0), (*poly[(k + 1) % n], z0), (*poly[(k + 1) % n], z1), (*poly[k], z1)), 10 if smooth else 0)
             for k in range(n)]
    for z in (z0, z1):
        faces += [(((cx, cy, z), (*poly[k], z), (*poly[(k + 1) % n], z)), 9) for k in range(n)]
    return faces


def circle(r, n=SEGMENTS):
    return [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def rectangle(w, h):
    return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]


def tube(r_out, r_in, length):
    """Open pipe along +X from x = 0, centred on the X axis."""
    ring = lambda r, x: [(x, py, pz) for py, pz in circle(r)]
    o0, o1, i0, i1 = ring(r_out, 0), ring(r_out, length), ring(r_in, 0), ring(r_in, length)
    faces = []
    for k in range(SEGMENTS):
        j = (k + 1) % SEGMENTS
        for quad in ((o0[k], o0[j], o1[j], o1[k]), (i0[k], i0[j], i1[j], i1[k]),
                     (o1[k], o1[j], i1[j], i1[k]), (o0[k], o0[j], i0[j], i0[k])):
            faces.append((quad, 10))
    return faces


def manhole_faces(shape, w, h, riser_h):
    lid_t = min(LID_T, riser_h / 2)
    if shape == "square":
        riser, lid = rectangle(w, h), rectangle(w + 2 * LID_OVERHANG, h + 2 * LID_OVERHANG)
    else:
        riser, lid = circle(w / 2), circle(w / 2 + LID_OVERHANG)
    smooth = shape != "square"
    return prism(riser, 0, riser_h - lid_t, smooth) + prism(lid, riser_h - lid_t, riser_h, smooth)


# ---------------------------------------------------------------------------- assembly
def add_block(doc, name, layer, faces):
    if name in doc.blocks:
        return name
    block = doc.blocks.new(name)
    for pts, hidden in faces:
        if len(pts) == 3:
            pts, hidden = (*pts, pts[2]), hidden | 4        # a triangle repeats its last point; that edge is empty
        block.add_3dface(pts, dxfattribs={"layer": layer, "invisible_edges": hidden})
    return name


def build(data):
    """The tank described by `data` (json_to_dxf.drawing_from_json) as an ezdxf document."""
    cube = to_cad_mm(load_glb(CUBE_GLB))
    cube -= [(cube[..., 0].max() + cube[..., 0].min()) / 2, (cube[..., 1].max() + cube[..., 1].min()) / 2, cube[..., 2].min()]
    half_h = cube[..., 2].max()
    plate = to_cad_mm(load_glb(PLATE_GLB))
    plate -= [(plate[..., 0].max() + plate[..., 0].min()) / 2, plate[..., 1].max(), plate[..., 2].min()]
    plate_h, plate_t = plate[..., 2].max(), -plate[..., 1].min()    # panel stands with its thickness towards -Y

    doc = dxf_canvas.new_document(LAYERS)
    msp = doc.modelspace()
    add_block(doc, "HALF_CUBE", "TANK_MODULE", mesh_faces(cube))
    flipped = cube * [1, -1, -1] + [0, 0, half_h]                   # the upper half of a layer is the lower one upside down
    add_block(doc, "HALF_CUBE_UP", "TANK_MODULE", mesh_faces(flipped))
    add_block(doc, "SIDE_PLATE", "TANK_SIDE_PLATE", mesh_faces(plate))

    pitch, length, width = json_to_dxf.data_mapper.CUBE_MM, data["length"], data["width"]
    cols, rows = data["cubes_long"], data["cubes_wide"]
    z = 0.0
    for row_h in data["rows_mm"]:
        full = row_h > half_h * 2 - 1
        for i in range(cols):
            for j in range(rows):
                at = ((i + 0.5) * pitch, (j + 0.5) * pitch)
                msp.add_blockref("HALF_CUBE", (*at, z), dxfattribs={"layer": "TANK_MODULE"})
                if full:
                    msp.add_blockref("HALF_CUBE_UP", (*at, z + half_h), dxfattribs={"layer": "TANK_MODULE"})
                elif row_h - half_h > 1:                           # a half layer: one half cube under a top plate
                    top = add_block(doc, "TOP_PLATE", "TANK_TOP_PLATE",
                                    prism(rectangle(pitch, pitch), 0, row_h - half_h))
                    msp.add_blockref(top, (*at, z + half_h), dxfattribs={"layer": "TANK_TOP_PLATE"})
        scale = 1 if full else row_h / plate_h
        for i in range(cols):                                      # front (y = 0) and back walls, outward = -Y / +Y
            for y, rot in ((0, 0), (width, 180)):
                msp.add_blockref("SIDE_PLATE", ((i + 0.5) * pitch, y, z),
                                 dxfattribs={"layer": "TANK_SIDE_PLATE", "rotation": rot, "zscale": scale})
        for j in range(rows):                                      # left (x = 0) and right walls, outward = -X / +X
            for x, rot in ((0, 270), (length, 90)):
                msp.add_blockref("SIDE_PLATE", (x, (j + 0.5) * pitch, z),
                                 dxfattribs={"layer": "TANK_SIDE_PLATE", "rotation": rot, "zscale": scale})
        z += row_h

    for p in data["pipes"]:
        r = p["diameter"] / 2
        layer = f"PIPES_{p['kind']}"
        name = add_block(doc, f"PIPE_{p['kind']}_{p['diameter']:g}", layer,
                         tube(r, r - max(3, p["diameter"] * 0.04), plate_t + PIPE_STUB))
        a = p["along"]                                             # the pipe starts at the module edge, through the plate
        pos, rot = {"bottom": ((a, 0), 270), "top": ((a, width), 90),
                    "left": ((0, a), 180), "right": ((length, a), 0)}[p["side"]]
        msp.add_blockref(name, (*pos, p["z"]), dxfattribs={"layer": layer, "rotation": rot})

    riser_h = max((data["fsl"] - data["top_rl"]) * 1000, 100)      # top of the tank up to finished surface level
    for m in data["manholes"]:
        name = add_block(doc, f"MANHOLE_{m['shape']}_{m['w_mm']:g}x{m['h_mm']:g}_{riser_h:g}", "MANHOLES",
                         manhole_faces(m["shape"], m["w_mm"], m["h_mm"], riser_h))
        msp.add_blockref(name, (m["x"], m["y"], z), dxfattribs={"layer": "MANHOLES"})

    view = doc.viewports.get("*Active")[0]                         # opens as a south-east isometric of the whole tank
    view.dxf.target = (length / 2, width / 2, z / 2)
    view.dxf.direction = (1, -1, 1)
    view.dxf.center = (0, 0)
    view.dxf.height = math.hypot(length, width, z) * 1.1
    return doc


def write(data, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "tank_3d.dxf"
    doc = build(data)
    errors = doc.audit().errors
    if errors:
        raise ValueError(f"DXF audit failed for {path}: {errors}")
    doc.saveas(path)
    if ezdxf.readfile(path).audit().errors:
        raise ValueError(f"DXF read-back audit failed for {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("payload", help="payload JSON: a path, or a file name inside payload/")
    parser.add_argument("output", nargs="?", help="output directory (default: output/<payload stem>)")
    args = parser.parse_args()
    source, payload = json_to_dxf.load_payload(args.payload)
    print(write(json_to_dxf.drawing_from_json(payload), args.output or HERE / "output" / source.stem))


if __name__ == "__main__":
    main()
