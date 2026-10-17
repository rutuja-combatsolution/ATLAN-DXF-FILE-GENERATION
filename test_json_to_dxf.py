"""Checks for the payload-driven DXF export (views + components).

    python -m unittest test_json_to_dxf.py            # fast set (~1-2 min)
    ATLAN_SLOW_TESTS=1 python -m unittest ...         # also exports the 330k-segment cube module drawing
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

import ezdxf

import json_to_dxf as generator
import view_export
import component_export

HERE = Path(__file__).resolve().parent
SOURCES = sorted(HERE.glob("source_data*.json"))
VIEW_FILES = {"plan_view.dxf", "front_elevation.dxf", "back_elevation.dxf", "left_elevation.dxf",
              "right_elevation.dxf"}


def load(name="source_data.json"):
    return json.loads((HERE / name).read_text(encoding="utf-8-sig"))


def dim_values(doc):
    """{'h': set of horizontal measurements, 'v': vertical} of the DIMENSION entities, rounded to mm."""
    out = {"h": set(), "v": set()}
    for d in doc.modelspace().query("DIMENSION"):
        p2, p3 = d.dxf.defpoint2, d.dxf.defpoint3
        if abs(d.dxf.angle) < 1e-6:
            out["h"].add(round(abs(p3.x - p2.x)))
        else:
            out["v"].add(round(abs(p3.y - p2.y)))
    return out


def entity_widths(msp):
    """Horizontal extent of every LINE / LWPOLYLINE."""
    out = []
    for e in msp:
        if e.dxftype() == "LINE":
            out.append(abs(e.dxf.end.x - e.dxf.start.x))
        elif e.dxftype() == "LWPOLYLINE":
            xs = [p[0] for p in e.get_points()]
            out.append(max(xs) - min(xs))
    return out


class DataTests(unittest.TestCase):
    def test_payload_change_updates_geometry(self):
        payload = load()
        changed = copy.deepcopy(payload)
        changed["material"]["cubes_long"] += 1
        a, b = map(generator.drawing_from_json, (payload, changed))
        self.assertEqual(b["length"] - a["length"], 1150)
        self.assertEqual(b["pipes"][0]["along"] - a["pipes"][0]["along"], 575)

    def test_bad_payload_is_rejected(self):
        payload = load()
        payload["geometry"]["stack_length"] = 1000.0               # 2 layers need 1560
        with self.assertRaises(ValueError):
            generator.drawing_from_json(payload)
        payload = load()
        del payload["material"]["cubes_long"]
        with self.assertRaises(ValueError):
            generator.drawing_from_json(payload)

    def test_plot_scale_keeps_geometry_true(self):
        data = generator.drawing_from_json(load("source_data2.json"))     # 66 m tank
        n, sheet, _ = view_export.choose_plot_scale(data, None)
        self.assertLessEqual(n * view_export.PT_MM, view_export.max_annotation_unit(data))
        self.assertIn(sheet, ("A1", "A0", "A0+"))


class ViewTests(unittest.TestCase):
    def test_every_sample_payload(self):
        for source in SOURCES:
            with self.subTest(payload=source.name):
                data = generator.drawing_from_json(load(source.name))
                with tempfile.TemporaryDirectory() as folder:
                    paths = generator.convert(data, folder, components=False)
                    self.assertEqual({p.name for p in paths}, VIEW_FILES)
                    self.assertTrue((Path(folder) / "manifest.json").is_file())
                    for path in paths:
                        doc = ezdxf.readfile(path)
                        self.assertFalse(doc.audit().errors)
                        self.assertEqual(doc.units, ezdxf.units.MM)

    def test_views_carry_the_pdf_annotations(self):
        data = generator.drawing_from_json(load())
        with tempfile.TemporaryDirectory() as folder:
            generator.convert(data, folder, components=False)
            plan = ezdxf.readfile(Path(folder) / "plan_view.dxf")
            dims = dim_values(plan)
            self.assertIn(round(data["length"]), dims["h"])          # module length
            self.assertIn(round(data["exc_length"]), dims["h"])      # excavation length
            self.assertIn(round(data["width"]), dims["v"])
            self.assertIn(round(data["exc_width"]), dims["v"])
            texts = " ".join(t.dxf.text for t in plan.modelspace().query("TEXT"))
            for needle in ("EXCAVATION LENGTH", "INLET", "OUTLET", "AGG DRAIN", "IL 97.00", "PLAN VIEW"):
                self.assertIn(needle, texts)
            self.assertNotIn("BY OTHERS", texts)
            for gone in ("TOTAL STORAGE CAPACITY", "AtlanCUBE 1000L MODULE", "CUBES ROW"):   # centre box dropped
                self.assertNotIn(gone, texts)
            white = [e for e in plan.modelspace().query("*[layer=='MANHOLES']")
                     if e.dxf.hasattr("true_color") and e.dxf.true_color == 0xFFFFFF]
            self.assertEqual(len(white), len(data["manholes"]))                               # white outlines
            self.assertEqual(plan.layers.get("MANHOLES").color, 7)                            # not green
            layers = {e.dxf.layer for e in plan.modelspace()}
            self.assertTrue({"FLOW_INLET", "FLOW_OUTLET", "EXCAVATION", "MANHOLES", "PIPES",
                             "DIMENSIONS", "LEADERS"} <= layers)
            inserts = list(plan.modelspace().query("INSERT[name=='atlancube_plan']"))
            self.assertEqual(len(inserts), data["cubes_long"] * data["cubes_wide"])

            front = ezdxf.readfile(Path(folder) / "front_elevation.dxf")
            texts = " ".join(t.dxf.text for t in front.modelspace().query("TEXT"))
            for needle in ("TOP OF STORAGE", "FSL 100.00", "NON-WOVEN", "COVER", "EXCAVATION DEPTH",
                           "BASE RL: 97.00", "FRONT ELEVATION VIEW"):
                self.assertIn(needle, texts)
            self.assertIn("GEOFAB", {e.dxf.layer for e in front.modelspace()})
            vdims = dim_values(front)["v"]
            self.assertIn(round(data["stack_h"]), vdims)
            self.assertIn(round(data["cover"]), vdims)
            self.assertIn(round(data["exc_depth"]), vdims)

    def test_pipe_positions_follow_payload_and_mirror(self):
        data = generator.drawing_from_json(load())
        with tempfile.TemporaryDirectory() as folder:
            generator.convert(data, folder, components=False)
            for stem, face, mirror, span in (("front_elevation", "bottom", False, data["length"]),
                                             ("back_elevation", "top", True, data["length"])):
                doc = ezdxf.readfile(Path(folder) / f"{stem}.dxf")
                circles = sorted((c.dxf.center.x, c.dxf.center.y, c.dxf.radius)
                                 for c in doc.modelspace().query("CIRCLE[layer=='PIPES']"))
                want = sorted((span - p["along"] if mirror else p["along"], p["z"])
                              for p in data["pipes"] if p["side"] == face)
                self.assertEqual(len(circles), len(want))
                for (cx, cy, r), (wx, wz) in zip(circles, want):
                    self.assertAlmostEqual(cx, wx, places=3)
                    self.assertAlmostEqual(cy, wz, places=3)

    def test_half_layer_row_height(self):
        payload = load("source_data2.json")                              # 2.5 layers
        data = generator.drawing_from_json(payload)
        self.assertEqual(data["rows_mm"], [780, 780, 430.0])
        with tempfile.TemporaryDirectory() as folder:
            generator.convert(data, folder, components=False)
            doc = ezdxf.readfile(Path(folder) / "front_elevation.dxf")
            inserts = list(doc.modelspace().query("INSERT[name=='atlancube_face']"))
            self.assertEqual(len(inserts), data["cubes_long"] * 3)
            self.assertEqual(sorted({round(i.dxf.yscale, 4) for i in inserts}), [round(430 / 780, 4), 1.0])

    def test_empty_fittings(self):
        payload = load()
        for key in ("inlet", "outlet", "manhole"):
            payload["material"][key] = None
        data = generator.drawing_from_json(payload)
        self.assertEqual(data["pipes"], [])
        self.assertEqual(data["manholes"], [])
        with tempfile.TemporaryDirectory() as folder:
            paths = generator.convert(data, folder, components=False)
            plan = ezdxf.readfile(Path(folder) / "plan_view.dxf")
            self.assertFalse(plan.modelspace().query("CIRCLE"))
            self.assertEqual(len(paths), 5)


class ComponentTests(unittest.TestCase):
    def test_component_plan_follows_payload(self):
        payload = load()
        data = generator.drawing_from_json(payload)
        plan = component_export.component_plan(data, payload)
        keys = [p[1] for p in plan]
        m = payload["material"]
        self.assertEqual(len([k for k in keys if k.startswith("manhole")]), len(m["manhole"]))
        self.assertEqual(len([k for k in keys if k.split("_")[0] in ("inlet", "outlet")]),
                         len(m["inlet"]) + len(m["outlet"]))
        self.assertIn("half_cube_module", keys)
        self.assertNotIn("side_plate_half_height", keys)               # no_half_side_plates is 0
        payload["material"]["no_single_clips"] = 0
        keys = [p[1] for p in component_export.component_plan(data, payload)]
        self.assertNotIn("single_connector", keys)

    def test_parametric_and_plate_components(self):
        payload = load()
        payload["material"]["no_half_cubes"] = 0                       # skip the 330k-segment module drawing
        payload["material"]["no_half_side_plates"] = 7                 # exercise the GLB route too
        data = generator.drawing_from_json(payload)
        with tempfile.TemporaryDirectory() as folder:
            rows = component_export.export_components(data, payload, folder)
            by_file = {r["file"]: r for r in rows}
            self.assertTrue(all(r["status"] == "ok" for r in rows), rows)
            self.assertEqual(by_file["side_plate_full_height.dxf"]["quantity"], payload["material"]["no_side_plates"])
            self.assertEqual(by_file["side_plate_half_height.dxf"]["quantity"], 7)
            self.assertEqual(by_file["single_connector.dxf"]["geometry"], "none (placeholder sheet)")
            for r in rows:
                doc = ezdxf.readfile(Path(folder) / r["file"])
                self.assertFalse(doc.audit().errors)
                self.assertEqual(doc.units, ezdxf.units.MM)

            # supplier plate drawn 1:1: front view 1147 x 777 mm
            plate = ezdxf.readfile(Path(folder) / "side_plate_full_height.dxf").modelspace()
            self.assertTrue(any(abs(w - 1147) < 2 for w in entity_widths(plate)),
                            "1147 mm overall width (supplier dimension) not found at 1:1")

            # a pipe sheet carries the payload's diameter, level and wall
            inlet = ezdxf.readfile(Path(folder) / "inlet_1_dn150.dxf").modelspace()
            self.assertTrue(any(abs(c.dxf.radius - 75) < 1e-6 for c in inlet.query("CIRCLE")))
            text = " ".join(t.dxf.text for t in inlet.query("TEXT"))
            self.assertIn("RL 98.000", text)
            self.assertIn("BACK", text)

    @unittest.skipUnless(os.environ.get("ATLAN_SLOW_TESTS"), "set ATLAN_SLOW_TESTS=1 (about 1 minute)")
    def test_half_cube_module_drawing(self):
        payload = load()
        data = generator.drawing_from_json(payload)
        with tempfile.TemporaryDirectory() as folder:
            rows = component_export.export_components(data, payload, folder)
            row = next(r for r in rows if r["file"] == "half_cube_module.dxf")
            self.assertEqual(row["status"], "ok")
            self.assertEqual(row["quantity"], payload["material"]["no_half_cubes"])
            msp = ezdxf.readfile(Path(folder) / "half_cube_module.dxf").modelspace()
            self.assertTrue(any(abs(w - 1150) < 2 for w in entity_widths(msp)),
                            "1150 mm overall width (supplier dimension) not found at 1:1")


if __name__ == "__main__":
    unittest.main()
