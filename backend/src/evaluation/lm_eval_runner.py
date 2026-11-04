from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from src.domain.benchmark_definition import BenchmarkDefinition

LmEvalCallable = Callable[..., dict[str, Any]]


class LmEvalRunner:
    def __init__(self, evaluator: LmEvalCallable | None = None) -> None:
        self._evaluator = evaluator or self._default_evaluator

    def evaluate(
        self,
        *,
        base_url: str,
        benchmark_definition: BenchmarkDefinition,
        model_id: str,
        num_concurrent: int = 1,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        subset = dict(benchmark_definition.presentationSubset or {})
        base_task = str(subset.get("task") or benchmark_definition.benchmarkId)
        # For tasks like MMLU, "subjects" selects a small set of subject
        # sub-tasks (e.g. "mmlu_abstract_algebra") instead of running the
        # full ~57-subject suite.
        subjects = list(subset.get("subjects") or [])
        task_names = [f"{base_task}_{subject}" for subject in subjects] if subjects else [base_task]
        task_kwargs = dict(subset.get("taskKwargs") or {})

        # "sampleSize"/"seed" describe a presentation-scale subset (e.g. 50
        # examples for a live demo) — without translating these into
        # lm-eval's own `limit`/`*_seed` kwargs, evaluations silently ran the
        # entire (often 1000+ example) test split.
        sample_size = subset.get("sampleSize")
        if sample_size is not None:
            task_kwargs.setdefault("limit", sample_size)
        seed = subset.get("seed")
        if seed is not None:
            task_kwargs.setdefault("random_seed", seed)
            task_kwargs.setdefault("numpy_random_seed", seed)
            task_kwargs.setdefault("torch_random_seed", seed)
            task_kwargs.setdefault("fewshot_random_seed", seed)

        # Free-form "generate_until" tasks (ifeval, and in general anything
        # that grades the model's actual response rather than token
        # loglikelihoods) must be evaluated through the chat-completions
        # endpoint with the chat template applied. Hitting the raw
        # /v1/completions endpoint with an unformatted prompt makes an
        # instruct model treat the instruction as text to *continue*
        # instead of *follow*, which silently craters scores on
        # instruction-following-style benchmarks even though the served
        # model is working correctly. Multiple-choice tasks (e.g. MMLU) must
        # stay on "local-completions": lm-eval's chat-completions client
        # doesn't support loglikelihood requests at all.
        use_chat_completions = bool(subset.get("useChatCompletions", False))
        model_args: dict[str, Any] = {
            # lm-eval's "local-completions"/"local-chat-completions" API
            # models require "model" (the checkpoint id the OpenAI-compatible
            # server expects, also used to load a matching HF tokenizer if
            # the endpoint doesn't support remote tokenization) — without it,
            # self.model stays None and tokenizer loading fails with "None is
            # not a valid model identifier".
            "model": model_id,
            "num_concurrent": num_concurrent,
            "max_retries": max_retries,
        }
        evaluator_kwargs: dict[str, Any] = {}
        if use_chat_completions:
            model_args["base_url"] = f"{str(base_url).rstrip('/')}/v1/chat/completions"
            # Qwen3-style hybrid-reasoning models emit a "<think>...</think>"
            # reasoning block before the actual answer by default. Strict
            # format checkers (e.g. ifeval) grade the *entire* response text,
            # so without stripping the reasoning trace, even a fully correct
            # answer fails. lm-eval's chat-completions client strips
            # everything up to and including this token for us.
            model_args["think_end_token"] = "</think>"
            # lm-eval's API models default to a 256-token generation budget,
            # which a thinking model routinely exhausts on its "<think>"
            # trace alone before ever writing its actual answer -- lm-eval
            # itself special-cases this ("runs out of tokens during the
            # thinking process") by substituting a placeholder empty
            # answer, which then fails every strict format check. Give
            # chat-completions generations enough headroom to finish
            # thinking *and* answer.
            model_args.setdefault("max_gen_toks", subset.get("maxGenTokens", 2048))
            evaluator_kwargs["apply_chat_template"] = True
        else:
            # lm-eval expects the full completions endpoint, not just the
            # host root.
            model_args["base_url"] = f"{str(base_url).rstrip('/')}/v1/completions"

        raw = self._evaluator(
            model="local-chat-completions" if use_chat_completions else "local-completions",
            model_args=model_args,
            tasks=task_names,
            **evaluator_kwargs,
            **task_kwargs,
        )
        return self._map_result(
            benchmark_definition=benchmark_definition,
            task_names=task_names,
            raw=raw,
        )

    def _default_evaluator(self, **kwargs: Any) -> dict[str, Any]:
        from lm_eval import simple_evaluate

        return simple_evaluate(**kwargs)

    @staticmethod
    def _map_result(
        *,
        benchmark_definition: BenchmarkDefinition,
        task_names: list[str],
        raw: Mapping[str, Any],
    ) -> dict[str, Any]:
        subset = dict(benchmark_definition.presentationSubset or {})
        threshold = dict(benchmark_definition.passFailThreshold or {})
        metric_name = str(subset.get("metric") or threshold.get("metric") or "exact_match,none")
        results = dict(raw.get("results") or {})
        scores: list[float] = []
        for task_name in task_names:
            task_results = dict(results.get(task_name) or {})
            if metric_name not in task_results:
                available_metrics = sorted(task_results.keys())
                raise ValueError(
                    f"Benchmark '{benchmark_definition.benchmarkId}' task '{task_name}' did "
                    f"not return metric '{metric_name}'. Available: {available_metrics}."
                )
            scores.append(float(task_results[metric_name]))

        # When multiple subject sub-tasks are selected (e.g. MMLU subjects),
        # report the unweighted mean across them as the benchmark's score.
        score = sum(scores) / len(scores)
        if score <= 1.0:
            score *= 100.0
        baseline = float(threshold.get("baselineScore") or 0.0)
        delta = round(score - baseline, 4)
        regression_threshold = float(threshold.get("regressionThresholdPoints") or 5.0)
        regression_flag = delta < (-1 * regression_threshold)
        return {
            "benchmarkId": benchmark_definition.benchmarkId,
            "version": benchmark_definition.version,
            "score": round(score, 4),
            "baseline": round(baseline, 4),
            "delta": delta,
            "passFail": "fail" if regression_flag else "pass",
            "regressionFlag": regression_flag,
        }
