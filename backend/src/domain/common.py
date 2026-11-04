from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


def generate_uuid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class CreatedAuditMixin:
    createdBy: Mapped[str] = mapped_column("created_by", String(255), nullable=False)
    createdAt: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )


class TimestampMixin:
    createdAt: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updatedAt: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
