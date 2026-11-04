from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("AUTH_MODE", "local-demo")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
