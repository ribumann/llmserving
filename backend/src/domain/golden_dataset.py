from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import utcnow
from src.domain.enums import (
    DatasetProvenance,
    DuplicateCheckState,
    ReviewStatus,
)
from src.persistence.db import Base


class GoldenDataset(Base):
    __tablename__ = "golden_datasets"

    goldenDatasetId: Mapped[str] = mapped_column("golden_dataset_id", String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    duplicateCheckState: Mapped[DuplicateCheckState] = mapped_column(
        "duplicate_check_state",
        Enum(DuplicateCheckState, native_enum=False, length=32),
        nullable=False,
        default=DuplicateCheckState.NOT_CHECKED,
    )
    provenance: Mapped[DatasetProvenance] = mapped_column(
        Enum(DatasetProvenance, native_enum=False, length=32),
        nullable=False,
        default=DatasetProvenance.CURATED,
    )
    reviewStatus: Mapped[ReviewStatus] = mapped_column(
        "review_status",
        Enum(ReviewStatus, native_enum=False, length=32),
        nullable=False,
        default=ReviewStatus.UNREVIEWED,
    )
    generationContext: Mapped[dict[str, Any] | None] = mapped_column(
        "generation_context",
        JSONB,
        nullable=True,
    )
    createdAt: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
