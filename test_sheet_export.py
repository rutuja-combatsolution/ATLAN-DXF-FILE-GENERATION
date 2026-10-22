"""Checks for the combined sheet DXF (PDF sheets 1-4 in one file).

    python -m unittest test_sheet_export.py
"""
import json
import tempfile
import unittest
from pathlib import Path

import ezdxf

import json_to_dxf
import sheet_export

PAYLOADS = Path(__file__).resolve().parent / "payloads"


def export(name, folder):
    payload = json.loads((PAYLOADS / name).read_text(encoding="utf-8-sig"))
    data = json_to_dxf.drawing_from_json(payload)
    path = Path(folder) / "general_arrangement.dxf"
    return data, sheet_export.export_sheets(data, path), ezdxf.readfile(path)


class SheetTests(unittest.TestCase):
    def test_four_pdf_sheets_in_one_dxf(self):
        with tempfile.TemporaryDirectory() as folder:
            data, info, doc = export("01_double_13x3.json", folder)
        self.assertEqual(doc.dxfversion, "AC1027")                          # AutoCAD 2013
        self.assertFalse(doc.audit().errors)
        texts = [t.dxf.text for t in doc.modelspace().query("TEXT")]
        for n in range(1, 5):
            self.assertEqual(texts.count(f"{n} OF 4"), 1)                  # title block of each sheet
        for needle in ("PARTS LIST", "Site Level Confirmation", "NOTES:", "PLAN VIEW", "FRONT ELEVATION VIEW",
                       "BACK ELEVATION VIEW", "LEFT ELEVATION VIEW", "RIGHT ELEVATION VIEW"):
            self.assertIn(needle, texts)
        for filled in ("RL: 100.00", "mm", "RL: 98.00 / 97.00", "RL: 97.00"):          # site level box: FSL, cover (blank), inlet, outlet
            self.assertIn(filled, texts)
        self.assertTrue(any(t.startswith("ALL INTERCONNECTING") for t in texts))
        self.assertTrue(any(t.startswith("TANK STORAGE CAPACITY") for t in texts))
        for gone in ("Bill of Materials", "FINAL BACKFILL", "SECTION"):    # sheets 5 and 6 are not drawn
            self.assertFalse(any(gone in t for t in texts))
        self.assertEqual([s["content"] for s in info["sheets"]][0], "GENERAL ARRANGEMENT")
        logos = [h for h in doc.modelspace().query("HATCH[layer=='TITLE_BLOCK']")]          # the logo, traced to vectors
        self.assertEqual(len(logos), 4)
        self.assertEqual(logos[0].dxf.solid_fill, 1)
        self.assertGreater(len(logos[0].paths), 20)                                          # letters + counters + (R)
        self.assertFalse(any(t == "Atlan" for t in texts))                                  # no text stand-in
        # the views are true size: the front elevation's module length is a real 14950 mm dimension
        lengths = {round(abs(d.dxf.defpoint3.x - d.dxf.defpoint2.x)) for d in doc.modelspace().query("DIMENSION")}
        self.assertIn(round(data["length"]), lengths)

    def test_sheets_are_equal_and_in_a_column(self):
        with tempfile.TemporaryDirectory() as folder:
            _, info, doc = export("13_long_tank.json", folder)
        self.assertFalse(doc.audit().errors)
        sheets = info["sheets"]
        self.assertEqual(len({(s["plot_scale"], tuple(s["frame_mm"])) for s in sheets}), 1)   # same scale, same frame
        self.assertEqual([s["origin_mm"][0] for s in sheets], [0] * 4)                       # one column ...
        ys = [s["origin_mm"][1] for s in sheets]
        self.assertEqual(ys, sorted(ys, reverse=True))                                       # ... sheet 1 on top


if __name__ == "__main__":
    unittest.main()
