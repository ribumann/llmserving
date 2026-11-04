from __future__ import annotations

from src.config import get_settings
from src.domain.benchmark_definition import BenchmarkDefinition
from src.persistence.db import create_session_factory

BENCHMARKS = [
    {
        "benchmarkId": "gsm8k",
        "version": "presentation-50-seed-42",
        "presentationSubset": {
            "task": "gsm8k",
            "metric": "exact_match,strict-match",
            "sampleSize": 50,
            "seed": 42,
            "split": "test",
        },
        "passFailThreshold": {
            "metric": "exact_match,strict-match",
            "baselineScore": 75.0,
            "regressionThresholdPoints": 5.0,
        },
    },
    {
        "benchmarkId": "ifeval",
        "version": "presentation-50-seed-42",
        "presentationSubset": {
            "task": "ifeval",
            "metric": "prompt_level_strict_acc,none",
            "sampleSize": 50,
            "seed": 42,
            "split": "train",
            # ifeval grades the model's actual free-form response, so it
            # must go through the chat-completions endpoint with the chat
            # template applied (see lm_eval_runner.py) rather than raw
            # /v1/completions, or an instruct model just continues the
            # instruction as text instead of following it.
            "useChatCompletions": True,
        },
        "passFailThreshold": {
            "metric": "prompt_level_strict_acc,none",
            "baselineScore": 65.0,
            "regressionThresholdPoints": 5.0,
        },
    },
    {
        "benchmarkId": "mmlu-5subject-mini",
        "version": "presentation-54-seed-42",
        "presentationSubset": {
            "task": "mmlu",
            "metric": "acc,none",
            "sampleSize": 54,
            "seed": 42,
            "split": "test",
            "subjects": [
                "abstract_algebra",
                "college_biology",
                "computer_security",
                "high_school_statistics",
                "professional_medicine",
            ],
        },
        "passFailThreshold": {
            "metric": "acc,none",
            "baselineScore": 60.0,
            "regressionThresholdPoints": 5.0,
        },
    },
]


def main() -> None:
    settings = get_settings()
    session_factory = create_session_factory(settings)
    with session_factory() as session:
        for payload in BENCHMARKS:
            session.merge(BenchmarkDefinition(**payload))
        session.commit()


if __name__ == "__main__":
    main()
