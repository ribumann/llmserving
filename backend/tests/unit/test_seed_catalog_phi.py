from __future__ import annotations

from src.domain.enums import ModelFamily, ModelSizeClass
from src.persistence.seed_catalog import CATALOG_ENTRIES


def test_catalog_includes_ungated_phi_entry_per_size_class() -> None:
    """FR-094: an ungated Phi checkpoint must exist for each 3B/7B/70B profile slot."""
    phi_entries = [entry for entry in CATALOG_ENTRIES if entry["family"] == ModelFamily.PHI]

    size_classes_covered = {entry["sizeClass"] for entry in phi_entries if not entry["isGated"]}

    assert size_classes_covered == {
        ModelSizeClass.THREE_B,
        ModelSizeClass.SEVEN_B,
        ModelSizeClass.SEVENTY_B,
    }


def test_phi_entries_use_same_shape_as_other_families() -> None:
    """Phi entries must not require any special-cased fields beyond the standard catalog shape."""
    expected_keys = {
        "catalogEntryId",
        "family",
        "sizeClass",
        "huggingFaceRepoId",
        "checkpointRef",
        "isGated",
        "license",
        "compatibleProfileIds",
        "quantizationRequired",
        "notes",
    }

    phi_entries = [entry for entry in CATALOG_ENTRIES if entry["family"] == ModelFamily.PHI]
    assert phi_entries, "expected at least one Phi catalog entry"

    for entry in phi_entries:
        assert set(entry.keys()) == expected_keys
