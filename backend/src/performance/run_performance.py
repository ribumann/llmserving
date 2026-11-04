from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.engines.base import InferenceEngineAdapter, PerformanceMetricsStream


class PerformanceRunner:
    def run(
        self,
        *,
        engine: InferenceEngineAdapter,
        deployment_revision_id: str,
        workload: Mapping[str, Any],
    ) -> PerformanceMetricsStream:
        return engine.runPerformanceWorkload(deployment_revision_id, workload)
