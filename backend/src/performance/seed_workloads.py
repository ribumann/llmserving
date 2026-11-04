from __future__ import annotations

from src.config import get_settings
from src.domain.performance_workload import PerformanceWorkload
from src.persistence.db import create_session_factory

# Mean/stddev input & output token counts mirror llmperf's own token_benchmark_ray.py
# defaults (mean-input-tokens=550, stddev-input-tokens=150, mean-output-tokens=150,
# stddev-output-tokens=10) - the de facto "industry standard" token profile used by
# the LLMPerf tool itself, so results are comparable across the presenter's runs
# without anyone having to invent/tune a token distribution by hand.
_STANDARD_INPUT_PROFILE = {
    "meanInputTokens": 550,
    "stddevInputTokens": 150,
    "meanOutputTokens": 150,
    "stddevOutputTokens": 10,
}

WORKLOADS = [
    {
        # Canonical single-stream latency probe: concurrency 1 so TTFT/inter-token
        # latency reflect an unloaded server, matching llmperf's own default.
        "workloadId": "llmperf-single-stream-v1",
        "version": 1,
        "warmup": {"requestCount": 3},
        "inputProfile": _STANDARD_INPUT_PROFILE,
        "concurrency": 1,
        "durationOrRequestCount": {"requestCount": 25},
        "safetyLimits": {"maxRequests": 40, "maxConcurrency": 1, "timeoutSeconds": 600},
        "completionCriteria": {"targetCompletedRequests": 25},
    },
    {
        # Typical concurrent-chatbot load: same token profile, concurrency 10, to
        # surface throughput/latency trade-offs under realistic simultaneous usage.
        "workloadId": "chatbot-concurrent-10-v1",
        "version": 1,
        "warmup": {"requestCount": 5},
        "inputProfile": _STANDARD_INPUT_PROFILE,
        "concurrency": 10,
        "durationOrRequestCount": {"requestCount": 50},
        "safetyLimits": {"maxRequests": 80, "maxConcurrency": 10, "timeoutSeconds": 600},
        "completionCriteria": {"targetCompletedRequests": 50},
    },
    {
        # Heavier stress/burst test: concurrency 25, to validate behavior and
        # graceful degradation under a higher-than-typical concurrent load.
        "workloadId": "high-concurrency-burst-v1",
        "version": 1,
        "warmup": {"requestCount": 5},
        "inputProfile": _STANDARD_INPUT_PROFILE,
        "concurrency": 25,
        "durationOrRequestCount": {"requestCount": 100},
        "safetyLimits": {"maxRequests": 150, "maxConcurrency": 25, "timeoutSeconds": 600},
        "completionCriteria": {"targetCompletedRequests": 100},
    },
]


def main() -> None:
    settings = get_settings()
    session_factory = create_session_factory(settings)
    with session_factory() as session:
        for payload in WORKLOADS:
            session.merge(PerformanceWorkload(**payload))
        session.commit()

    print(f"Seeded {len(WORKLOADS)} performance workloads.")


if __name__ == "__main__":
    main()
