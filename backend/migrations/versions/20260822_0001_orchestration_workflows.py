"""Create orchestration_workflows table for the internal callback API (User Story 10).

Backs `src/domain/orchestration_workflow.py` (data-model.md "Orchestration Workflow"),
the entity that ties a Durable Functions workflow instance back to the single-writer
lock held via `demo_environments.active_operation_id` (FR-052/FR-077).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260822_0001"
down_revision = "20260821_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orchestration_workflows",
        sa.Column("workflow_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "environment_id",
            sa.String(length=100),
            sa.ForeignKey("demo_environments.environment_id"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.String(length=100), nullable=False),
        sa.Column(
            "workflow_type",
            sa.Enum(
                "provision",
                "deploy",
                "evaluate-golden",
                "evaluate-benchmark",
                "performance-test",
                "export",
                "teardown",
                name="workflowtype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("dispatched_job_ref", sa.String(length=255), nullable=True),
        sa.Column("phase", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "completed",
                "failed",
                "cancelled",
                name="workflowstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_orchestration_workflows_environment_id",
        "orchestration_workflows",
        ["environment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_orchestration_workflows_environment_id", table_name="orchestration_workflows")
    op.drop_table("orchestration_workflows")
