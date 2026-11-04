from __future__ import annotations

from typing import Any

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import CreatedAuditMixin
from src.domain.enums import DeploymentRevisionState
from src.persistence.db import Base


class DeploymentRevision(CreatedAuditMixin, Base):
    __tablename__ = "deployment_revisions"

    deploymentRevisionId: Mapped[str] = mapped_column(
        "deployment_revision_id", String(100), primary_key=True
    )
    environmentId: Mapped[str] = mapped_column(
        "environment_id",
        ForeignKey("demo_environments.environment_id"),
        nullable=False,
    )
    modelConfigId: Mapped[str] = mapped_column(
        "model_config_id",
        ForeignKey("model_configurations.model_config_id"),
        nullable=False,
    )
    inferenceConfigId: Mapped[str] = mapped_column(
        "inference_config_id",
        ForeignKey("inference_configurations.inference_config_id"),
        nullable=False,
    )
    engineId: Mapped[str] = mapped_column(
        "engine_id",
        ForeignKey("inference_engines.engine_id"),
        nullable=False,
    )
    lifecycleState: Mapped[DeploymentRevisionState] = mapped_column(
        "lifecycle_state",
        Enum(DeploymentRevisionState, native_enum=False, length=32),
        nullable=False,
    )
    activePeriod: Mapped[dict[str, Any]] = mapped_column(
        "active_period", JSONB, nullable=False, default=dict
    )
    health: Mapped[dict[str, Any]] = mapped_column("health", JSONB, nullable=False, default=dict)
