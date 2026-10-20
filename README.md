# JSON to separate CAD files (DXF)

One payload JSON in, five independent DXF files out (plan view and front / back / left / right elevations) -
the same payload the PDF generator takes.

```powershell
python -m pip install -r requirements.txt
python json_to_dxf.py payload/source_data.json              # -> output/source_data/
python json_to_dxf.py payload/source_data2.json output/my_project
python json_to_dxf.py source_data6.json                     # a bare file name is looked up in payload/
python -m unittest test_json_to_dxf.py
```

## What is written

```
output/<payload>/
  plan_view.dxf  front_elevation.dxf  back_elevation.dxf  left_elevation.dxf  right_elevation.dxf
  manifest.json                       the five files with their plot scale and sheet
```

## How it stays in step with the PDF

* The payload is mapped by `generator/data_mapper.py` (module footprint 1150 mm, layer height 780 mm,
  excavation margin 525 mm, wall sign conventions, ...).
* The views are drawn by `generator/Internal/plan_view.py` and `generator/Internal/elevation_view.py`.
  `dxf_canvas.py` stands in for the ReportLab canvas and records every call as DXF entities, so every
  dimension, MIN. 500 callout, pipe callout with leader, flow arrow, geofab wrap, level dimension and
  TOP OF STORAGE / FSL label of the drawing code is in the DXF.
* **This project is self-contained.** `generator/` is a copy of those five files from the PDF project
  (`generator/SOURCE_VERSION.txt` gives the commit it was taken from). Nothing outside this folder is needed and
  there is no `ATLAN_PDF_GEN_DIR` / `../pdf gen` lookup any more. The two projects now evolve separately: a
  drawing change in the PDF project reaches the DXF only if it is copied into `generator/` by hand.
* **Syncing a PDF change.** Copy `data_mapper.py`, `Internal/plan_view.py` and `Internal/elevation_view.py` over the
  files in `generator/` as they are (the DXF-specific code lives outside `generator/`), re-apply the one line listed in
  `generator/SOURCE_VERSION.txt`, update that file, then run the checks. The only code that depends on the signatures
  of the PDF's `dim_h` / `dim_v` (and their label-fitting helpers) is `_native_dims` in `view_export.py`; if the PDF
  adds an argument to either, add it there too.
* The PDF's text-overlap handling (dimension captions that shrink / wrap / fall back to a shorter wording, labels fitted
  into the stretch of a dimension that no other line crosses, callouts placed clear of risers and leaders) and its
  placement rules for manholes and inlet / outlet pipes (kept wholly inside the tank on a long, narrow module) are
  therefore part of the DXF output.

## Views

* Model space is 1:1 in millimetres, module bottom-left corner at (0, 0), $INSUNITS = mm. Opposite elevations
  mirror positions exactly as the PDF does.
* Layers: `TANK`, `MODULE_ART`, `EXCAVATION`, `PIPES`, `MANHOLES`, `FLOW_INLET`, `FLOW_OUTLET`, `GEOFAB`,
  `DIMENSIONS`, `LEADERS`, `ANNOTATIONS`, `TITLE`.
* Ordinary linear dimensions are real `DIMENSION` entities; the special layouts (MIN. 500 callouts, short chain
  segments) are drawn as lines + text like the PDF (`--exploded-dims` draws all dimensions that way).
* **Plot scale.** The PDF is N.T.S. with fixed-size text; for CAD each view gets a plot scale 1:N (printed in the
  title strip and in `manifest.json`) so annotation reads like the PDF when plotted at 1:N on the stated sheet.
  N is limited so the geometry the PDF clamps for legibility (525 mm excavation margin, 500 mm geofab extension,
  pipe diameters) is drawn true; a very long tank therefore needs a larger sheet (A1/A0) rather than a smaller scale.
* Pipe stubs, flow arrows and callout leaders are schematic, as in the PDF.

## Requirements and limits

* `ezdxf`, `reportlab` (the drawing code in `generator/`).
* DXF R2010; every file is audited before saving and again after reopening. Opening in AutoCAD itself is
  still to be checked by a person - nothing here runs AutoCAD.
