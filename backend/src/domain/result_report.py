from __future__ import annotations

from typing import Any

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.enums import CompletenessIndicator
from src.persistence.db import Base


class ResultReport(Base):
    __tablename__ = "result_reports"

    resultReportId: Mapped[str] = mapped_column("result_report_id", String(100), primary_key=True)
    runId: Mapped[str] = mapped_column(
        "run_id",
        ForeignKey("experiment_runs.run_id"),
        nullable=False,
        unique=True,
    )
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    performance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    completenessIndicator: Mapped[CompletenessIndicator] = mapped_column(
        "completeness_indicator",
        Enum(CompletenessIndicator, native_enum=False, length=32),
        nullable=False,
    )
    referenceExecutionProfileRef: Mapped[str | None] = mapped_column(
        "reference_execution_profile_ref",
        String(100),
        nullable=True,
    )
