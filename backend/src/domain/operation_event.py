from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import utcnow
from src.persistence.db import Base


class OperationEvent(Base):
    __tablename__ = "operation_events"

    eventId: Mapped[str] = mapped_column("event_id", String(36), primary_key=True)
    operationId: Mapped[str] = mapped_column(
        "operation_id", String(100), nullable=False, index=True
    )
    requestId: Mapped[str] = mapped_column("request_id", String(64), nullable=False, index=True)
    environmentId: Mapped[str | None] = mapped_column("environment_id", String(100), nullable=True)
    eventType: Mapped[str] = mapped_column("event_type", String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    createdAt: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
