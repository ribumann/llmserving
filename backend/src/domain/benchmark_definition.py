from __future__ import annotations

from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.persistence.db import Base


class BenchmarkDefinition(Base):
    __tablename__ = "benchmark_definitions"

    benchmarkId: Mapped[str] = mapped_column("benchmark_id", String(100), primary_key=True)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    presentationSubset: Mapped[dict[str, Any]] = mapped_column(
        "presentation_subset",
        JSONB,
        nullable=False,
        default=dict,
    )
    passFailThreshold: Mapped[dict[str, Any]] = mapped_column(
        "pass_fail_threshold",
        JSONB,
        nullable=False,
        default=dict,
    )
