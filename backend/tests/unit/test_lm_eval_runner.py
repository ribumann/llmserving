from __future__ import annotations

from typing import Any

import pytest
from src.domain.benchmark_definition import BenchmarkDefinition
from src.evaluation.lm_eval_runner import LmEvalRunner


def _definition(**overrides: Any) -> BenchmarkDefinition:
    defaults: dict[str, Any] = dict(
        benchmarkId="gsm8k",
        version="presentation-50-seed-42",
        presentationSubset={
            "task": "gsm8k",
            "metric": "exact_match,strict-match",
            "sampleSize": 50,
            "seed": 42,
            "split": "test",
        },
        passFailThreshold={
            "metric": "exact_match,strict-match",
            "baselineScore": 75.0,
            "regressionThresholdPoints": 5.0,
        },
    )
    defaults.update(overrides)
    return BenchmarkDefinition(**defaults)


def test_evaluate_passes_model_id_and_full_completions_url() -> None:
    captured: dict[str, Any] = {}

    def evaluator(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"results": {"gsm8k": {"exact_match,strict-match": 0.82}}}

    runner = LmEvalRunner(evaluator=evaluator)
    result = runner.evaluate(
        base_url="http://10.0.0.5:8000",
        benchmark_definition=_definition(),
        model_id="Qwen/Qwen3-4B",
    )

    assert captured["model_args"]["model"] == "Qwen/Qwen3-4B"
    assert captured["model_args"]["base_url"] == "http://10.0.0.5:8000/v1/completions"
    assert result["score"] == pytest.approx(82.0)
    assert result["passFail"] == "pass"


def test_evaluate_translates_sample_size_and_seed_into_lm_eval_kwargs() -> None:
    captured: dict[str, Any] = {}

    def evaluator(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"results": {"gsm8k": {"exact_match,strict-match": 0.5}}}

    runner = LmEvalRunner(evaluator=evaluator)
    runner.evaluate(
        base_url="http://10.0.0.5:8000",
        benchmark_definition=_definition(),
        model_id="Qwen/Qwen3-4B",
    )

    assert captured["tasks"] == ["gsm8k"]
    # Without this translation, lm-eval defaults to running the entire
    # (1000+ example) test split instead of the intended presentation subset.
    assert captured["limit"] == 50
    assert captured["random_seed"] == 42
    assert captured["numpy_random_seed"] == 42
    assert captured["torch_random_seed"] == 42
    assert captured["fewshot_random_seed"] == 42


def test_evaluate_expands_subjects_into_per_subject_tasks_and_averages_score() -> None:
    captured: dict[str, Any] = {}

    def evaluator(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "results": {
                "mmlu_abstract_algebra": {"acc,none": 0.4},
                "mmlu_college_biology": {"acc,none": 0.8},
            }
        }

    definition = _definition(
        benchmarkId="mmlu-5subject-mini",
        version="presentation-54-seed-42",
        presentationSubset={
            "task": "mmlu",
            "metric": "acc,none",
            "sampleSize": 27,
            "seed": 42,
            "split": "test",
            "subjects": ["abstract_algebra", "college_biology"],
        },
        passFailThreshold={
            "metric": "acc,none",
            "baselineScore": 60.0,
            "regressionThresholdPoints": 5.0,
        },
    )
    runner = LmEvalRunner(evaluator=evaluator)
    result = runner.evaluate(
        base_url="http://10.0.0.5:8000",
        benchmark_definition=definition,
        model_id="Qwen/Qwen3-4B",
    )

    assert captured["tasks"] == ["mmlu_abstract_algebra", "mmlu_college_biology"]
    assert captured["limit"] == 27
    # Unweighted mean of 40% and 80% => 60%.
    assert result["score"] == pytest.approx(60.0)


def test_evaluate_uses_chat_completions_for_ifeval() -> None:
    captured: dict[str, Any] = {}

    def evaluator(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"results": {"ifeval": {"prompt_level_strict_acc,none": 0.7}}}

    definition = _definition(
        benchmarkId="ifeval",
        version="presentation-50-seed-42",
        presentationSubset={
            "task": "ifeval",
            "metric": "prompt_level_strict_acc,none",
            "sampleSize": 50,
            "seed": 42,
            "split": "train",
            "useChatCompletions": True,
        },
        passFailThreshold={
            "metric": "prompt_level_strict_acc,none",
            "baselineScore": 65.0,
            "regressionThresholdPoints": 5.0,
        },
    )
    runner = LmEvalRunner(evaluator=evaluator)
    runner.evaluate(
        base_url="http://10.0.0.5:8000",
        benchmark_definition=definition,
        model_id="Qwen/Qwen3-4B",
    )

    assert captured["model"] == "local-chat-completions"
    assert captured["model_args"]["base_url"] == "http://10.0.0.5:8000/v1/chat/completions"
    # Without stripping Qwen3's "<think>...</think>" reasoning trace, ifeval's
    # strict format checks (which grade the whole response text) fail even on
    # a correct final answer.
    assert captured["model_args"]["think_end_token"] == "</think>"
    # Thinking models can exhaust lm-eval's 256-token default generation
    # budget on the "<think>" trace alone, leaving no room for an actual
    # answer.
    assert captured["model_args"]["max_gen_toks"] == 2048
    assert captured["apply_chat_template"] is True


def test_evaluate_allows_overriding_max_gen_tokens_for_chat_completions() -> None:
    captured: dict[str, Any] = {}

    def evaluator(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"results": {"ifeval": {"prompt_level_strict_acc,none": 0.7}}}

    definition = _definition(
        benchmarkId="ifeval",
        version="presentation-50-seed-42",
        presentationSubset={
            "task": "ifeval",
            "metric": "prompt_level_strict_acc,none",
            "sampleSize": 50,
            "seed": 42,
            "split": "train",
            "useChatCompletions": True,
            "maxGenTokens": 4096,
        },
        passFailThreshold={
            "metric": "prompt_level_strict_acc,none",
            "baselineScore": 65.0,
            "regressionThresholdPoints": 5.0,
        },
    )
    runner = LmEvalRunner(evaluator=evaluator)
    runner.evaluate(
        base_url="http://10.0.0.5:8000",
        benchmark_definition=definition,
        model_id="Qwen/Qwen3-4B",
    )

    assert captured["model_args"]["max_gen_toks"] == 4096


def test_evaluate_defaults_to_raw_completions_for_multiple_choice_tasks() -> None:
    captured: dict[str, Any] = {}

    def evaluator(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"results": {"gsm8k": {"exact_match,strict-match": 0.82}}}

    runner = LmEvalRunner(evaluator=evaluator)
    runner.evaluate(
        base_url="http://10.0.0.5:8000",
        benchmark_definition=_definition(),
        model_id="Qwen/Qwen3-4B",
    )

    assert captured["model"] == "local-completions"
    assert captured["model_args"]["base_url"] == "http://10.0.0.5:8000/v1/completions"
    assert "think_end_token" not in captured["model_args"]
    assert "apply_chat_template" not in captured


def test_evaluate_raises_when_metric_missing_from_results() -> None:
    def evaluator(**_kwargs: Any) -> dict[str, Any]:
        return {"results": {"gsm8k": {"some_other_metric,none": 0.1}}}

    runner = LmEvalRunner(evaluator=evaluator)
    with pytest.raises(ValueError, match="did not return metric"):
        runner.evaluate(
            base_url="http://10.0.0.5:8000",
            benchmark_definition=_definition(),
            model_id="Qwen/Qwen3-4B",
        )
