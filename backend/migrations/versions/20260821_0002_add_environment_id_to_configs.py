"""Add missing environment_id FK to model/inference configurations.

The foundation migration (20260819_0001) never added an ``environment_id``
column to ``model_configurations``/``inference_configurations``, even though
the ORM models (src/domain/model_configuration.py,
src/domain/inference_configuration.py) require it as a non-nullable FK to
``demo_environments``. That schema drift was never applied to production
(no follow-up migration was ever written and ``alembic upgrade head`` was
only ever run once, before the ORM models were extended), which is why
POST /environments/{id}/model-configurations and .../inference-configurations
started failing with 400/500s once the API attempted to persist a row using
a column the table doesn't have.

Column is added nullable first, any orphaned pre-existing rows without an
environment_id (rows that could only ever have been created before this bug
was noticed, since the ORM has required the field since inception) are
removed, then the column is made NOT NULL with the FK constraint - this is
safe regardless of current row count.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260821_0002"
down_revision = "20260819_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configurations",
        sa.Column("environment_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "inference_configurations",
        sa.Column("environment_id", sa.String(length=100), nullable=True),
    )

    # Orphaned rows predate this column and have no environment to backfill from.
    op.execute(sa.text("DELETE FROM model_configurations WHERE environment_id IS NULL"))
    op.execute(sa.text("DELETE FROM inference_configurations WHERE environment_id IS NULL"))

    op.alter_column("model_configurations", "environment_id", nullable=False)
    op.alter_column("inference_configurations", "environment_id", nullable=False)

    op.create_foreign_key(
        "fk_model_configurations_environment_id",
        "model_configurations",
        "demo_environments",
        ["environment_id"],
        ["environment_id"],
    )
    op.create_foreign_key(
        "fk_inference_configurations_environment_id",
        "inference_configurations",
        "demo_environments",
        ["environment_id"],
        ["environment_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_inference_configurations_environment_id",
        "inference_configurations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_model_configurations_environment_id", "model_configurations", type_="foreignkey"
    )
    op.drop_column("inference_configurations", "environment_id")
    op.drop_column("model_configurations", "environment_id")
