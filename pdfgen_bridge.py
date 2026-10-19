"""Exposes the drawing code the DXF export reuses, from the ``generator/`` folder inside this project.

The DXF export shares the payload mapper (``data_mapper``) and the view drawing code
(``Internal.plan_view`` / ``Internal.elevation_view``) with the PDF, so a drawing and its DXF agree.
``generator/`` holds a copy of those files (see ``generator/SOURCE_VERSION.txt`` for the PDF-project commit
they started from), so this project runs on its own - the PDF project is not needed.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GENERATOR_DIR = HERE / "generator"

if not (GENERATOR_DIR / "data_mapper.py").is_file():
    raise FileNotFoundError(f"{GENERATOR_DIR} is missing data_mapper.py - the generator/ folder must stay with this project.")
if str(GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATOR_DIR))

import data_mapper                                   # noqa: E402  (needs the path above)
from Internal import cube_art, cube_plan_art         # noqa: E402,F401
from Internal import elevation_view, plan_view       # noqa: E402

CUBE_MM = data_mapper.CUBE_MM
LAYER_MM = data_mapper.LAYER_MM
