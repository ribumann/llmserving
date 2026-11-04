"""Add missing health column to deployment_revisions.

The foundation migration (20260819_0001) never added a ``health`` column to
``deployment_revisions``, even though the ORM model
(src/domain/deployment_revision.py) requires it as a non-nullable JSONB
column with a dict default. This is the same class of schema drift fixed in
20260821_0002 (missing environment_id on model/inference configurations):
the ORM was extended after the foundation migration was written, and no
follow-up migration was ever added for this column.

POST /environments/{id}/deployments persists a DeploymentRevision with a
``health`` value on every call, so every deployment attempt failed with an
unhandled `psycopg`/SQLAlchemy "column does not exist" error, surfaced to
API callers as a generic 500 ("The server encountered an unexpected
error.") instead of a meaningful ApiError.

The column is added NOT NULL with a JSONB `{}` server default so it can be
introduced in a single step regardless of existing row count.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260823_0001"
down_revision = "20260822_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deployment_revisions",
        sa.Column(
            "health",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("deployment_revisions", "health")
