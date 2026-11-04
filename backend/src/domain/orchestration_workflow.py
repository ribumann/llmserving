from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import utcnow
from src.domain.enums import WorkflowStatus, WorkflowType
from src.persistence.db import Base


class OrchestrationWorkflow(Base):
    """A Durable Functions workflow instance coordinating one long-running operation
    for a Demo Environment (User Story 10, FR-077, data-model.md "Orchestration
    Workflow"). Provider-agnostic at the domain layer: for the Azure provider this
    maps 1:1 to a Durable Functions orchestrator instance; the local/Ollama provider
    (User Story 7) never creates one of these records.

    Carries no domain state itself (model config, inference config, results) - only
    orchestration progress (data-model.md Validation). Domain records are written by
    FastAPI when a Container Apps Job reports back through the internal callback API
    (contracts/api.md); this entity is the correlation point that ties that callback
    traffic back to the single-writer lock held via `DemoEnvironment.activeOperationId`.
    """

    __tablename__ = "orchestration_workflows"

    workflowId: Mapped[str] = mapped_column("workflow_id", String(100), primary_key=True)
    environmentId: Mapped[str] = mapped_column(
        "environment_id",
        ForeignKey("demo_environments.environment_id"),
        nullable=False,
    )
    # Ties this workflow to the single-writer lock value held in
    # DemoEnvironment.activeOperationId while the workflow runs (FR-052).
    operationId: Mapped[str] = mapped_column("operation_id", String(100), nullable=False)
    workflowType: Mapped[WorkflowType] = mapped_column(
        "workflow_type",
        Enum(WorkflowType, native_enum=False, length=32),
        nullable=False,
    )
    dispatchedJobRef: Mapped[str | None] = mapped_column(
        "dispatched_job_ref", String(255), nullable=True
    )
    phase: Mapped[str] = mapped_column(String(255), nullable=False, default="accepted")
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, native_enum=False, length=32),
        nullable=False,
        default=WorkflowStatus.RUNNING,
    )
    cancellationRequested: Mapped[bool] = mapped_column(
        "cancellation_requested", Boolean, nullable=False, default=False
    )
    # Progress/result diagnostics reported via PATCH/complete callbacks, surfaced to
    # the operator UI (FR-049). Must never contain an HF credential or interactive
    # prompt/response body - enforced by src.domain.hf_credentials before this is set
    # (FR-082/FR-084, contracts/api.md internal callback contract rule).
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    startedAt: Mapped[datetime] = mapped_column(
        "started_at", DateTime(timezone=True), nullable=False, default=utcnow
    )
    endedAt: Mapped[datetime | None] = mapped_column(
        "ended_at", DateTime(timezone=True), nullable=True
    )
