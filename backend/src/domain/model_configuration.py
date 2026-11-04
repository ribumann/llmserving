from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import CreatedAuditMixin
from src.persistence.db import Base


class ModelConfiguration(CreatedAuditMixin, Base):
    __tablename__ = "model_configurations"

    modelConfigId: Mapped[str] = mapped_column("model_config_id", String(100), primary_key=True)
    environmentId: Mapped[str] = mapped_column(
        "environment_id",
        ForeignKey("demo_environments.environment_id"),
        nullable=False,
    )
    catalogEntryId: Mapped[str] = mapped_column(
        "catalog_entry_id",
        ForeignKey("model_catalog_entries.catalog_entry_id"),
        nullable=False,
    )
    resolvedCheckpointRef: Mapped[str] = mapped_column(
        "resolved_checkpoint_ref", String(200), nullable=False
    )
    modelSettings: Mapped[dict[str, Any]] = mapped_column(
        "model_settings",
        JSONB,
        nullable=False,
        default=dict,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
