# JSON to separate CAD files (DXF)

One payload JSON in, five independent DXF files out (plan view and front / back / left / right elevations) plus one
combined `general_arrangement.dxf` with the PDF's sheets 1-4 - the same payload the PDF generator takes.

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
  general_arrangement.dxf             the PDF's sheets 1-4 in one file (below)
  manifest.json                       every file with its plot scale and sheet
```

## Combined sheet: `general_arrangement.dxf`

```powershell
python -m unittest test_sheet_export.py
```

The PDF's pages 1-4 in one DXF: four identical A3 sheets in a column, sheet 1 at the top down to sheet 4. Sheet 1 = plan +
front elevation + tank storage capacity, parts list, site level confirmation box, notes, approval stamp; sheets 2-4 = back,
left, right elevation. Every sheet has the PDF's frame with grid references, tolerance bar, revision table, client /
confidentiality cells, drawn / check block, logo and project / title block (filled from the payload; scale = the plot scale).
The PDF's section sheet (5) and bill of materials (6) are not drawn.

* It is the PDF's own sheet code (`generator/main.py`, `page1.py`, ...) run through `dxf_canvas.Recorder` by
  `sheet_export.py`, so the sheets match the PDF and follow it when `generator/` is re-synced.
* Model space is 1:1 in mm. A sheet is its A3 frame x N (it plots at 1:N on A3) and all four sheets share one N: the
  smallest standard scale at which the general arrangement (the busiest sheet) still fits (printed in the title block and
  in `manifest.json`). The narrow end elevations are therefore drawn at the same scale as the plan, not enlarged like in
  the PDF. On a very long tank N gets large (1:400 and more) and, as in the PDF, the details it clamps for legibility
  (525 mm excavation margin, small pipes) are drawn oversize.
* Layers `FRAME`, `TITLE_BLOCK`, `TABLES` hold the sheet furniture, the view layers are the same as in the single-view
  files. Like `plan_view.dxf`, the plan has no centre info box.
* The logo is the PDF's `generator/Atlan-Stormwater-LogoR.png`, outlined to vector shapes (one solid-filled HATCH,
  `dxf_canvas.trace_image`), so it is inside the DXF - no linked image file - and stays sharp at any zoom. A new logo
  PNG (one colour, transparent background) is picked up by copying it over that file.

## Combined 3D tank

```powershell
python tank_3d.py payloads/01_double_13x3.json              # -> output/01_double_13x3/tank_3d.dxf
python -m unittest test_tank_3d.py
```

One more DXF per payload: the whole tank in 3D (mm, Z up, tank base at z = 0, plan coordinates as in `plan_view.dxf`).
It opens as a south-east isometric of the whole tank.

* Half cubes (two per full layer, the upper one upside down) and side plates are the simplified GLB meshes in
  `components/glb` (not in git: see `.gitignore`); a half layer is one half cube under a flat top plate.
* **Pipes and manholes are drawn at the size in the payload**: a pipe at its `diameter` (open tube, 450 mm beyond the side
  plate, centre at its invert level), a manhole at its `manhole_type` footprint (square 600x600, circular 600, circular 300 ...)
  rising from the tank top to FSL with a lid. They are generated, not taken from the fixed-size manhole / pit GLBs.
* Every part is one block of 3DFACEs repeated as INSERTs, so the sample payloads come out at 1 - 3 MB. Layers: `TANK_MODULE`,
  `TANK_SIDE_PLATE`, `TANK_TOP_PLATE`, `PIPES_INLET`, `PIPES_OUTLET`, `MANHOLES`.
* Not modelled: connector clips (no model for them), geofab / liner / excavation, pits.

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
* DXF R2013 (AutoCAD 2013, AC1027); every file is audited before saving and again after reopening. Opening in AutoCAD itself is
  still to be checked by a person - nothing here runs AutoCAD.
