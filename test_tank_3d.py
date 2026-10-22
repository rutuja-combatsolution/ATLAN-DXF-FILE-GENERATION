"""Checks for the combined 3D tank DXF.

    python -m unittest test_tank_3d.py
"""
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import ezdxf
import numpy as np

import json_to_dxf
import tank_3d

PAYLOADS = Path(__file__).resolve().parent / "payloads"
SAMPLES = ("01_double_13x3.json", "09_1.5stack.json", "12_half_stack.json")     # double, 1.5 and half stack


def load(name):
    payload = json.loads((PAYLOADS / name).read_text(encoding="utf-8-sig"))
    return payload["material"], json_to_dxf.drawing_from_json(payload)


def vertices(doc, block):
    return np.array([v for f in doc.blocks[block].query("3DFACE") for v in (f.dxf.vtx0, f.dxf.vtx1, f.dxf.vtx2, f.dxf.vtx3)])


class Tank3dTests(unittest.TestCase):
    def test_parts_match_the_bill_of_materials(self):
        for name in SAMPLES:
            with self.subTest(payload=name):
                material, data = load(name)
                inserts = Counter(i.dxf.name.split("_")[0] for i in tank_3d.build(data).modelspace().query("INSERT"))
                self.assertEqual(inserts["HALF"], material["no_half_cubes"])
                self.assertEqual(inserts["SIDE"], (material["no_side_plates"] or 0) + (material["no_half_side_plates"] or 0))
                self.assertEqual(inserts["PIPE"], len(data["pipes"]))
                self.assertEqual(inserts["MANHOLE"], len(data["manholes"]))

    def test_pipes_and_manholes_are_drawn_at_their_payload_size(self):
        for name in SAMPLES + ("06_data.json",):                  # 06 has 225 .. 750 mm pipes and 300 / 600 manholes
            with self.subTest(payload=name):
                _, data = load(name)
                doc = tank_3d.build(data)
                names = [i.dxf.name for i in doc.modelspace().query("INSERT")]
                for pipe in data["pipes"]:
                    v = vertices(doc, f"PIPE_{pipe['kind']}_{pipe['diameter']:g}")
                    self.assertAlmostEqual(np.ptp(v[:, 1]), pipe["diameter"], places=3)
                    self.assertAlmostEqual(np.ptp(v[:, 2]), pipe["diameter"], places=3)
                for m in data["manholes"]:
                    block = next(n for n in names if n.startswith(f"MANHOLE_{m['shape']}_{m['w_mm']:g}x{m['h_mm']:g}_"))
                    foot = vertices(doc, block)
                    foot = foot[foot[:, 2] == 0]
                    self.assertAlmostEqual(np.ptp(foot[:, 0]), m["w_mm"], places=3)
                    self.assertAlmostEqual(np.ptp(foot[:, 1]), m["h_mm"], places=3)

    def test_file_is_written_and_reads_back(self):
        _, data = load(SAMPLES[0])
        with tempfile.TemporaryDirectory() as folder:
            path = tank_3d.write(data, folder)
            self.assertEqual(path.name, "tank_3d.dxf")
            self.assertFalse(ezdxf.readfile(path).audit().errors)


if __name__ == "__main__":
    unittest.main()
