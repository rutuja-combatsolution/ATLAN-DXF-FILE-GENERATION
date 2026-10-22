"""Payload JSON -> five separate CAD files (plan view and front / back / left / right elevation DXFs) plus one
combined general_arrangement.dxf with the PDF's sheets 1-4 (see sheet_export.py).

    python json_to_dxf.py payload/source_data.json [output_dir] [--exploded-dims]

The payload is the same JSON the PDF generator takes (geometry / input / material [/ project]).  It is mapped
by ``generator/data_mapper.py`` and the views are drawn by the drawing code in ``generator/Internal`` (a copy
kept inside this project, so it runs on its own).  See README.md.
"""
import argparse
import datetime
import json
import math
from pathlib import Path

import pdfgen_bridge
from pdfgen_bridge import data_mapper

HERE = Path(__file__).resolve().parent
PAYLOAD_DIR = HERE / "payload"


def drawing_from_json(payload):
    """Map the payload exactly as the PDF does, with sanity checks and pipe labels."""
    data = data_mapper.build(payload)
    for key in ("length", "width", "stack_h"):
        if not math.isfinite(data[key]) or data[key] <= 0:
            raise ValueError(f"{key} must be a positive finite number")
    if data["layers"] <= 0 or not math.isfinite(data["layers"]):
        raise ValueError("layers_in_system must be positive and finite")
    if not math.isclose(sum(data["rows_mm"]), data["stack_h"], abs_tol=1):
        raise ValueError("stack_length is inconsistent with the layer count")
    counts = {}
    for pipe in data["pipes"]:
        counts[pipe["kind"]] = counts.get(pipe["kind"], 0) + 1
        pipe["label"] = f"{pipe['kind']}-{counts[pipe['kind']]}"
        if pipe["diameter"] <= 0 or not all(math.isfinite(pipe[k]) for k in ("diameter", "along", "z")):
            raise ValueError("Pipe diameter must be positive and pipe coordinates finite")
    data["payload"] = payload
    return data


def convert(data, out_dir, native_dims=True):
    """Write the five view DXFs, the combined general_arrangement.dxf and manifest.json into out_dir. Returns the DXF paths written."""
    import sheet_export
    import view_export

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    views = view_export.export_views(data, out_dir, native_dims)
    sheet = sheet_export.export_sheets(data, out_dir / "general_arrangement.dxf")
    print(f"Saved: {out_dir / sheet['file']}  ({len(sheet['sheets'])} sheets)")

    manifest = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "project": [t for t in data["project_lines"] if t],
        "title": data["title_lines"],
        "model_mm": {"length": data["length"], "width": data["width"], "stack_height": data["stack_h"],
                     "cubes_long": data["cubes_long"], "cubes_wide": data["cubes_wide"],
                     "rows_mm": data["rows_mm"]},
        "levels": {"fsl": data["fsl"], "top_of_storage": data["top_rl"], "base": data["base_rl"]},
        "views": views,
        "general_arrangement": sheet,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return [out_dir / v["file"] for v in views] + [out_dir / sheet["file"]]


def load_payload(path):
    source = Path(path)
    if not source.is_file() and not source.is_absolute():      # then next to this script, then in payload/
        source = next((c for c in (HERE / source, PAYLOAD_DIR / source) if c.is_file()), HERE / source)
    with source.open(encoding="utf-8-sig") as stream:
        return source, json.loads(stream.read().replace(" ", " "))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("payload", nargs="?", default=str(PAYLOAD_DIR / "source_data.json"),
                        help="payload JSON: a path, or just a file name inside payload/")
    parser.add_argument("output", nargs="?", help="Output directory (default: output/<payload stem>)")
    parser.add_argument("--exploded-dims", action="store_true",
                        help="draw dimensions as lines + text (as in the PDF) instead of DIMENSION entities")
    args = parser.parse_args()

    source, payload = load_payload(args.payload)
    data = drawing_from_json(payload)
    paths = convert(data, args.output or HERE / "output" / source.stem, native_dims=not args.exploded_dims)
    print(f"\n{len(paths)} DXF files written; manifest.json lists every file and its plot scale and sheet.")


if __name__ == "__main__":
    main()
