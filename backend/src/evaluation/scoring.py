from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def strip_reasoning_trace(observed: str) -> str:
    """Grade the final answer even when a closed reasoning trace has no answer."""
    _, separator, tail = observed.rpartition("</think>")
    return tail if separator else observed


def evaluate_golden_case(case: Mapping[str, Any], observed: str) -> bool:
    graded_text = strip_reasoning_trace(observed)
    raw_rule = str(case.get("evaluationRule") or "").strip()
    rule = raw_rule.lower()
    if rule == "exact-match":
        expected = str(case.get("expectedOutput") or "").strip()
        return graded_text.strip() == expected
    if rule == "contains":
        expected = str(case.get("expectedSubstring") or "").strip()
        return expected in graded_text
    if rule.startswith("regex:"):
        pattern = raw_rule.split(":", 1)[1]
        return re.search(pattern, graded_text) is not None
    raise ValueError(f"Unsupported evaluation rule '{case.get('evaluationRule')}'.")
