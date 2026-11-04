from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.persistence.db import Base


class PerformanceWorkload(Base):
    __tablename__ = "performance_workloads"

    workloadId: Mapped[str] = mapped_column("workload_id", String(100), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    warmup: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    inputProfile: Mapped[dict[str, Any]] = mapped_column(
        "input_profile", JSONB, nullable=False, default=dict
    )
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    durationOrRequestCount: Mapped[dict[str, Any]] = mapped_column(
        "duration_or_request_count",
        JSONB,
        nullable=False,
        default=dict,
    )
    safetyLimits: Mapped[dict[str, Any]] = mapped_column(
        "safety_limits", JSONB, nullable=False, default=dict
    )
    completionCriteria: Mapped[dict[str, Any]] = mapped_column(
        "completion_criteria",
        JSONB,
        nullable=False,
        default=dict,
    )
