from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import utcnow
from src.domain.enums import ExperimentRunStatus, ExperimentRunType, RetentionClass
from src.persistence.db import Base


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    runId: Mapped[str] = mapped_column("run_id", String(100), primary_key=True)
    deploymentRevisionId: Mapped[str] = mapped_column(
        "deployment_revision_id",
        ForeignKey("deployment_revisions.deployment_revision_id"),
        nullable=False,
    )
    runType: Mapped[ExperimentRunType] = mapped_column(
        "run_type",
        Enum(ExperimentRunType, native_enum=False, length=32),
        nullable=False,
    )
    testDefinitionRef: Mapped[str | None] = mapped_column(
        "test_definition_ref", String(100), nullable=True
    )
    status: Mapped[ExperimentRunStatus] = mapped_column(
        Enum(ExperimentRunStatus, native_enum=False, length=32),
        nullable=False,
    )
    environmentContextSnapshot: Mapped[dict[str, Any]] = mapped_column(
        "environment_context_snapshot",
        JSONB,
        nullable=False,
        default=dict,
    )
    startedAt: Mapped[datetime] = mapped_column(
        "started_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    endedAt: Mapped[datetime | None] = mapped_column(
        "ended_at", DateTime(timezone=True), nullable=True
    )
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    eventLogRef: Mapped[str | None] = mapped_column("event_log_ref", String(100), nullable=True)
    cancellationRequests: Mapped[list[dict[str, Any]]] = mapped_column(
        "cancellation_requests",
        JSONB,
        nullable=False,
        default=list,
    )
    retentionClass: Mapped[RetentionClass] = mapped_column(
        "retention_class",
        Enum(RetentionClass, native_enum=False, length=32),
        nullable=False,
    )
