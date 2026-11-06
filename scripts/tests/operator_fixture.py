"""Synthetic target inputs for offline tests, never imported by operator tools."""

import json
import os
import sys
from pathlib import Path

CONFIG = json.loads(
    (Path(__file__).parent / "fixtures" / "operator-config.json").read_text()
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LLM_SERVING_OPERATOR_CONFIG"] = json.dumps(CONFIG)
