from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import utcnow
from src.persistence.db import Base


class AuditLogEntry(Base):
    __tablename__ = "audit_log_entries"

    auditLogId: Mapped[str] = mapped_column("audit_log_id", String(36), primary_key=True)
    requestId: Mapped[str] = mapped_column("request_id", String(64), nullable=False, index=True)
    actorId: Mapped[str] = mapped_column("actor_id", String(255), nullable=False)
    actorEmail: Mapped[str] = mapped_column("actor_email", String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    statusCode: Mapped[int] = mapped_column("status_code", Integer, nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    createdAt: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
