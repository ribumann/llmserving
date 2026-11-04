"""Test helpers for functions/: adds functions/ to sys.path so tests can
import `orchestration_lib`, `orchestrators`, and `activities` the same way
the Azure Functions Python v2 host does at runtime (function_app.py sits at
the functions/ root and imports these as plain top-level packages).
"""

from __future__ import annotations

import sys
from pathlib import Path

FUNCTIONS_ROOT = Path(__file__).resolve().parent.parent
if str(FUNCTIONS_ROOT) not in sys.path:
    sys.path.insert(0, str(FUNCTIONS_ROOT))
