from __future__ import annotations

from typing import Any

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.common import TimestampMixin
from src.domain.enums import DemoEnvironmentState, ProviderType
from src.persistence.db import Base


class DemoEnvironment(TimestampMixin, Base):
    __tablename__ = "demo_environments"

    environmentId: Mapped[str] = mapped_column("environment_id", String(100), primary_key=True)
    profileId: Mapped[str] = mapped_column(
        "profile_id",
        ForeignKey("cloud_deployment_profiles.profile_id"),
        nullable=False,
    )
    provider: Mapped[ProviderType] = mapped_column(
        Enum(ProviderType, native_enum=False, length=32),
        nullable=False,
    )
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    regionRecommendation: Mapped[dict[str, Any] | None] = mapped_column(
        "region_recommendation",
        JSONB,
        nullable=True,
    )
    lifecycleState: Mapped[DemoEnvironmentState] = mapped_column(
        "lifecycle_state",
        Enum(DemoEnvironmentState, native_enum=False, length=32),
        nullable=False,
    )
    activeDeploymentRevisionId: Mapped[str | None] = mapped_column(
        "active_deployment_revision_id",
        ForeignKey("deployment_revisions.deployment_revision_id"),
        nullable=True,
    )
    activeOperationId: Mapped[str | None] = mapped_column(
        "active_operation_id", String(100), nullable=True
    )
    providerState: Mapped[dict[str, Any]] = mapped_column(
        "provider_state",
        JSONB,
        nullable=False,
        default=dict,
    )
    createdBy: Mapped[str] = mapped_column("created_by", String(255), nullable=False)
    lastModifiedBy: Mapped[str] = mapped_column("last_modified_by", String(255), nullable=False)
