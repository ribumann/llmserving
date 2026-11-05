from __future__ import annotations

from src.evaluation.run_quality import QualityRunOrchestrator


def test_evaluate_case_grades_final_answer_not_reasoning_trace() -> None:
    # Regression test: a Qwen3-style "<think>...</think>" reasoning block can
    # mention the expected substring while still reasoning, then land on a
    # different final answer. Grading the raw response would incorrectly pass
    # this case; grading must only consider text after the closing think tag.
    observed = (
        "<think>\nThe Nile is often cited as the longest river, but some "
        "sources argue the Amazon is longer...\n</think>\n\nAmazon"
    )
    case = {
        "caseId": "longest-river",
        "input": "What is the longest river in the world?",
        "evaluationRule": "contains",
        "expectedSubstring": "Nile",
    }
    assert QualityRunOrchestrator._evaluate_case(case, observed) is False


def test_evaluate_case_passes_when_final_answer_matches_after_reasoning() -> None:
    observed = "<think>\nGold's symbol comes from the Latin 'aurum'.\n</think>\n\nAu"
    case = {
        "caseId": "gold-chemical-symbol",
        "input": "What is the chemical symbol for gold?",
        "evaluationRule": "regex:(?i)\\bau\\b",
    }
    assert QualityRunOrchestrator._evaluate_case(case, observed) is True


def test_evaluate_case_falls_back_to_full_text_without_a_think_block() -> None:
    # Non-reasoning models (or engines that don't emit "<think>") never
    # contain "</think>", so grading must still work against the plain text.
    observed = "Paris"
    case = {
        "caseId": "capital-france",
        "input": "What is the capital of France?",
        "evaluationRule": "contains",
        "expectedSubstring": "Paris",
    }
    assert QualityRunOrchestrator._evaluate_case(case, observed) is True


def test_evaluate_case_exact_match_ignores_reasoning_trace() -> None:
    observed = "<think>\nDouble-checking the arithmetic...\n</think>\n96"
    case = {
        "caseId": "arithmetic-basic",
        "input": "What is 12 multiplied by 8?",
        "evaluationRule": "exact-match",
        "expectedOutput": "96",
    }
    assert QualityRunOrchestrator._evaluate_case(case, observed) is True


def test_reasoning_only_does_not_pass_without_a_final_answer() -> None:
    case = {"evaluationRule": "contains", "expectedSubstring": "Nile"}
    assert QualityRunOrchestrator._evaluate_case(case, "<think>Nile</think>") is False


def test_regex_preserves_pattern_case() -> None:
    case = {"evaluationRule": "regex:^Au$"}
    assert QualityRunOrchestrator._evaluate_case(case, "Au") is True
    assert QualityRunOrchestrator._evaluate_case(case, "au") is False
