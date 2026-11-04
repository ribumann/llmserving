from __future__ import annotations

from typing import Any

from sqlalchemy import Enum, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.enums import ComparisonStatus
from src.persistence.db import Base


class Comparison(Base):
    __tablename__ = "comparisons"

    comparisonId: Mapped[str] = mapped_column("comparison_id", String(100), primary_key=True)
    resultReportIds: Mapped[list[str]] = mapped_column(
        "result_report_ids",
        ARRAY(String(100)),
        nullable=False,
        default=list,
    )
    configurationDiff: Mapped[dict[str, Any]] = mapped_column(
        "configuration_diff", JSONB, nullable=False, default=dict
    )
    qualityDiff: Mapped[dict[str, Any]] = mapped_column(
        "quality_diff", JSONB, nullable=False, default=dict
    )
    performanceDiff: Mapped[dict[str, Any]] = mapped_column(
        "performance_diff", JSONB, nullable=False, default=dict
    )
    failureDiff: Mapped[dict[str, Any]] = mapped_column(
        "failure_diff", JSONB, nullable=False, default=dict
    )
    utilizationDiff: Mapped[dict[str, Any]] = mapped_column(
        "utilization_diff", JSONB, nullable=False, default=dict
    )
    comparabilityStatus: Mapped[ComparisonStatus] = mapped_column(
        "comparability_status",
        Enum(ComparisonStatus, native_enum=False, length=32),
        nullable=False,
    )
    comparabilityReasons: Mapped[list[str]] = mapped_column(
        "comparability_reasons",
        ARRAY(Text()),
        nullable=False,
        default=list,
    )
