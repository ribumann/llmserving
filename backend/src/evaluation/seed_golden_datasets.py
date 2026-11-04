from __future__ import annotations

from src.config import get_settings
from src.domain.enums import DatasetProvenance, DuplicateCheckState, ReviewStatus
from src.domain.golden_dataset import GoldenDataset
from src.persistence.db import create_session_factory

# A small, curated general-knowledge/reasoning golden dataset for smoke-testing a
# freshly deployed model. Prompts explicitly constrain the response format (e.g.
# "reply with just the ...") so free-form generative answers can still be graded
# with simple substring/regex checks rather than requiring an LLM judge. All facts
# are common public knowledge (geography, science, literature, arithmetic) - no
# copyrighted or dataset-licensed content is reproduced.
GOLDEN_DATASETS = [
    {
        "goldenDatasetId": "demo-factual-qa-v1",
        "name": "Demo factual Q&A smoke test",
        "version": 1,
        "provenance": DatasetProvenance.CURATED,
        "duplicateCheckState": DuplicateCheckState.CLEAN,
        "reviewStatus": ReviewStatus.REVIEWED,
        "cases": [
            {
                "caseId": "capital-france",
                "input": "What is the capital of France? Reply with just the city name.",
                "evaluationRule": "contains",
                "expectedSubstring": "Paris",
            },
            {
                "caseId": "arithmetic-basic",
                "input": "What is 12 multiplied by 8? Reply with only the number.",
                "evaluationRule": "regex:\\b96\\b",
            },
            {
                "caseId": "largest-planet",
                "input": (
                    "Which planet in our solar system is the largest? Reply with just "
                    "the planet name."
                ),
                "evaluationRule": "contains",
                "expectedSubstring": "Jupiter",
            },
            {
                "caseId": "water-boiling-point",
                "input": (
                    "At sea level, what temperature in Celsius does water boil at? "
                    "Reply with only the number."
                ),
                "evaluationRule": "contains",
                "expectedSubstring": "100",
            },
            {
                "caseId": "romeo-and-juliet-author",
                "input": (
                    "Who wrote the play 'Romeo and Juliet'? Reply with just the author's name."
                ),
                "evaluationRule": "contains",
                "expectedSubstring": "Shakespeare",
            },
            {
                "caseId": "gold-chemical-symbol",
                "input": "What is the chemical symbol for gold? Reply with only the symbol.",
                # Case-insensitive word-boundary regex instead of "contains": a bare
                # "Au" substring check would also match inside unrelated words (e.g.
                # "author"), and the model's capitalization isn't guaranteed.
                "evaluationRule": "regex:(?i)\\bau\\b",
            },
            {
                "caseId": "continent-count",
                "input": "How many continents are there on Earth? Reply with only the number.",
                "evaluationRule": "regex:\\b7\\b",
            },
            {
                "caseId": "opposite-of-hot",
                "input": "What is the opposite of 'hot'? Reply with just one word.",
                # Case-insensitive: the model may or may not capitalize a
                # sentence-initial single-word answer.
                "evaluationRule": "regex:(?i)\\bcold\\b",
            },
            {
                "caseId": "python-creator",
                "input": "Who created the Python programming language? Reply with just the name.",
                "evaluationRule": "contains",
                "expectedSubstring": "Guido",
            },
            {
                "caseId": "sum-two-numbers",
                "input": "What is the sum of 15 and 27? Reply with only the number.",
                "evaluationRule": "regex:\\b42\\b",
            },
            {
                "caseId": "longest-river",
                "input": "What is the longest river in the world? Reply with just the river name.",
                "evaluationRule": "contains",
                "expectedSubstring": "Nile",
            },
            {
                "caseId": "first-moon-walker",
                "input": "Who was the first human to walk on the Moon? Reply with just the name.",
                "evaluationRule": "contains",
                "expectedSubstring": "Armstrong",
            },
        ],
    },
]


def main() -> None:
    settings = get_settings()
    session_factory = create_session_factory(settings)
    with session_factory() as session:
        for payload in GOLDEN_DATASETS:
            session.merge(GoldenDataset(**payload))
        session.commit()

    print(f"Seeded {len(GOLDEN_DATASETS)} golden dataset(s).")


if __name__ == "__main__":
    main()
