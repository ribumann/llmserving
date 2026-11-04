from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import CreatedAuditMixin
from src.persistence.db import Base


class InferenceConfiguration(CreatedAuditMixin, Base):
    __tablename__ = "inference_configurations"

    inferenceConfigId: Mapped[str] = mapped_column(
        "inference_config_id", String(100), primary_key=True
    )
    environmentId: Mapped[str] = mapped_column(
        "environment_id",
        ForeignKey("demo_environments.environment_id"),
        nullable=False,
    )
    engineId: Mapped[str] = mapped_column(
        "engine_id",
        ForeignKey("inference_engines.engine_id"),
        nullable=False,
    )
    servingSettings: Mapped[dict[str, Any]] = mapped_column(
        "serving_settings",
        JSONB,
        nullable=False,
        default=dict,
    )
    generationSettings: Mapped[dict[str, Any]] = mapped_column(
        "generation_settings",
        JSONB,
        nullable=False,
        default=dict,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
