"""Locates the PDF generator ('pdf gen' folder) and exposes the parts the DXF export reuses.

The DXF export shares the payload mapper (``data_mapper``) and the view drawing code
(``Internal.plan_view`` / ``Internal.elevation_view``) with the PDF, so a drawing and its DXF always agree.

Folder lookup: environment variable ATLAN_PDF_GEN_DIR, else ``../pdf gen`` next to this project,
else ``./pdf gen`` inside it.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def locate_generator():
    candidates = [os.environ.get("ATLAN_PDF_GEN_DIR"), HERE.parent / "pdf gen", HERE / "pdf gen"]
    for c in candidates:
        if c and (Path(c) / "data_mapper.py").is_file():
            return Path(c).resolve()
    raise FileNotFoundError(
        "PDF generator folder not found (needs data_mapper.py). Put the 'pdf gen' folder next to this "
        "project or set ATLAN_PDF_GEN_DIR. Tried: " + ", ".join(str(c) for c in candidates if c))


GENERATOR_DIR = locate_generator()
if str(GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATOR_DIR))

import data_mapper                                   # noqa: E402  (needs the path above)
from Internal import cube_art, cube_plan_art         # noqa: E402,F401
from Internal import elevation_view, plan_view       # noqa: E402

CUBE_MM = data_mapper.CUBE_MM
LAYER_MM = data_mapper.LAYER_MM
