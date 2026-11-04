"""Add User Story 3 golden dataset metadata."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260819_0002"
down_revision = "20260819_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    provenance = sa.Enum(
        "curated",
        "ai-generated",
        name="datasetprovenance",
        native_enum=False,
        length=32,
    )
    review_status = sa.Enum(
        "reviewed",
        "unreviewed",
        name="reviewstatus",
        native_enum=False,
        length=32,
    )

    with op.batch_alter_table("golden_datasets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "name",
                sa.String(length=200),
                nullable=False,
                server_default="Imported Golden Dataset",
            )
        )
        batch_op.add_column(
            sa.Column(
                "provenance",
                provenance,
                nullable=False,
                server_default="curated",
            )
        )
        batch_op.add_column(
            sa.Column(
                "review_status",
                review_status,
                nullable=False,
                server_default="unreviewed",
            )
        )
        batch_op.add_column(
            sa.Column("generation_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch_op.alter_column("name", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("golden_datasets") as batch_op:
        batch_op.drop_column("created_at")
        batch_op.drop_column("generation_context")
        batch_op.drop_column("review_status")
        batch_op.drop_column("provenance")
        batch_op.drop_column("name")
