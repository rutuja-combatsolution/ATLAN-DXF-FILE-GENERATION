"""Payload JSON -> separate CAD files: five view DXFs and one DXF per bill-of-materials component.

    python json_to_dxf.py source_data.json [output_dir] [--no-components] [--exploded-dims] [--assets DIR]

The payload is the same JSON the PDF generator takes (geometry / input / material [/ project]).  It is mapped
by the PDF project's ``data_mapper`` and the views are drawn by the PDF project's own drawing code, so the
DXFs and the PDF always agree.  See README.md.
"""
import argparse
import datetime
import json
import math
from pathlib import Path

import pdfgen_bridge
from pdfgen_bridge import data_mapper

HERE = Path(__file__).resolve().parent


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


def convert(data, out_dir, components=True, native_dims=True, assets_dir=None):
    """Write views (+ components) and manifest.json into out_dir. Returns the DXF paths written."""
    import component_export
    import view_export

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    views = view_export.export_views(data, out_dir, native_dims)
    rows = []
    if components:
        rows = component_export.export_components(
            data, data["payload"], out_dir / "components", assets_dir or component_export.ASSET_DIR)

    manifest = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "project": [t for t in data["project_lines"] if t],
        "title": data["title_lines"],
        "model_mm": {"length": data["length"], "width": data["width"], "stack_height": data["stack_h"],
                     "cubes_long": data["cubes_long"], "cubes_wide": data["cubes_wide"],
                     "rows_mm": data["rows_mm"]},
        "levels": {"fsl": data["fsl"], "top_of_storage": data["top_rl"], "base": data["base_rl"]},
        "views": views,
        "components": rows,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    paths = [out_dir / v["file"] for v in views]
    paths += [out_dir / "components" / r["file"] for r in rows if r["status"] == "ok"]
    return paths


def load_payload(path):
    source = Path(path)
    if not source.is_file() and not source.is_absolute():
        source = HERE / source
    with source.open(encoding="utf-8-sig") as stream:
        return source, json.loads(stream.read().replace(" ", " "))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("payload", nargs="?", default=str(HERE / "source_data.json"))
    parser.add_argument("output", nargs="?", help="Output directory (default: output/<payload stem>)")
    parser.add_argument("--no-components", action="store_true", help="only the five view DXFs")
    parser.add_argument("--exploded-dims", action="store_true",
                        help="draw dimensions as lines + text (as in the PDF) instead of DIMENSION entities")
    parser.add_argument("--assets", help="folder with the supplier drawings / models (default: dxg files)")
    args = parser.parse_args()

    source, payload = load_payload(args.payload)
    data = drawing_from_json(payload)
    paths = convert(data, args.output or HERE / "output" / source.stem, components=not args.no_components,
                    native_dims=not args.exploded_dims, assets_dir=args.assets)
    print(f"\n{len(paths)} DXF files written; manifest.json lists every file, quantity and geometry source.")


if __name__ == "__main__":
    main()
