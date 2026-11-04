from __future__ import annotations

from src.domain.comparability import assess_provider_comparability
from src.domain.enums import ComparisonStatus, ProviderType


def test_local_results_are_not_directly_comparable_to_azure_results() -> None:
    status, reasons = assess_provider_comparability(ProviderType.LOCAL, ProviderType.AZURE)

    assert status == ComparisonStatus.NOT_DIRECTLY_COMPARABLE
    assert reasons
    assert "not directly comparable" in reasons[0].lower()
