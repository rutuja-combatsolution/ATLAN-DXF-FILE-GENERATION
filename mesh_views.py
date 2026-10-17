"""Orthographic line views of a GLB mesh (for components that only exist as a 3D model).

Feature edges are drawn: creases (angle between the two faces above ``crease_deg``), silhouettes for the
viewing direction, and open boundary edges.  Hidden lines are NOT removed - every feature edge of the part
is projected, which is what a CAD wireframe view looks like.

GLB files from the supplier use 1 unit = 10 mm (full side plate 114.8 x 6.5 x 77.8 -> 1148 x 65 x 778 mm).
"""
import json
import struct

import numpy as np

_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _parse_glb(buf):
    magic, _, _ = struct.unpack_from("<4sII", buf, 0)
    if magic != b"glTF":
        raise ValueError("not a GLB file")
    off, js, blob = 12, None, None
    while off < len(buf):
        clen, ctype = struct.unpack_from("<I4s", buf, off)
        off += 8
        chunk = buf[off:off + clen]
        off += clen
        if ctype == b"JSON":
            js = json.loads(chunk.decode("utf8").rstrip("\x00 "))
        elif ctype.startswith(b"BIN"):
            blob = chunk
    return js, blob


def _accessor(js, blob, idx):
    a = js["accessors"][idx]
    bv = js["bufferViews"][a["bufferView"]]
    dt, n = np.dtype(_CT[a["componentType"]]), _NC[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", 0)
    if stride and stride != dt.itemsize * n:
        return np.ndarray((a["count"], n), dtype=dt, buffer=blob, offset=start, strides=(stride, dt.itemsize))
    return np.frombuffer(blob, dtype=dt, count=a["count"] * n, offset=start).reshape(a["count"], n)


def load_glb(path, unit_mm=10.0, weld=1e-3):
    """(vertices Nx3 in mm, triangles Mx3) with coincident vertices welded."""
    with open(path, "rb") as f:
        js, blob = _parse_glb(f.read())
    verts, tris, base = [], [], 0
    for mesh in js.get("meshes", []):
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) != 4:
                continue
            pos = _accessor(js, blob, prim["attributes"]["POSITION"]).astype(np.float64)
            idx = (_accessor(js, blob, prim["indices"]).reshape(-1).astype(np.int64)
                   if "indices" in prim else np.arange(len(pos)))
            verts.append(pos * unit_mm)
            tris.append(idx.reshape(-1, 3) + base)
            base += len(pos)
    v = np.vstack(verts)
    t = np.vstack(tris)
    keys = np.round(v / weld).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    v = v[first]
    t = inverse.reshape(-1)[t]
    keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    return v, t[keep]


def feature_edges(verts, tris, view_dir, crease_deg=35.0):
    """Edges (Kx2 vertex indices) that belong in a line drawing seen along ``view_dir``."""
    n_vert = len(verts)
    p0, p1, p2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    normals = np.cross(p1 - p0, p2 - p0)
    length = np.linalg.norm(normals, axis=1)
    ok = length > 1e-12
    normals[ok] /= length[ok, None]

    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    face = np.tile(np.arange(len(tris)), 3)
    e.sort(axis=1)
    key = e[:, 0].astype(np.int64) * n_vert + e[:, 1]
    order = np.argsort(key, kind="stable")
    key, face, e = key[order], face[order], e[order]
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    counts = np.diff(np.r_[starts, len(key)])

    keep = np.zeros(len(starts), dtype=bool)
    keep[counts != 2] = True                                    # open / non-manifold edges
    pair = np.flatnonzero(counts == 2)
    f1, f2 = face[starts[pair]], face[starts[pair] + 1]
    n1, n2 = normals[f1], normals[f2]
    v = np.asarray(view_dir, dtype=float)
    v = v / np.linalg.norm(v)
    crease = np.einsum("ij,ij->i", n1, n2) < np.cos(np.radians(crease_deg))
    silhouette = (n1 @ v) * (n2 @ v) < 0
    keep[pair] = crease | silhouette
    return e[starts[keep]]


def project(verts, edges, axes):
    """Edges as ((x0, y0), (x1, y1)) arrays using the two coordinate axes (0, 1, 2) as x, y."""
    a = verts[edges[:, 0]][:, axes]
    b = verts[edges[:, 1]][:, axes]
    return a, b
