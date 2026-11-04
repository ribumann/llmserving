from __future__ import annotations

from typing import Any

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.enums import ModelSizeClass, ProviderType
from src.persistence.db import Base


class CloudDeploymentProfile(Base):
    __tablename__ = "cloud_deployment_profiles"

    profileId: Mapped[str] = mapped_column("profile_id", String(100), primary_key=True)
    provider: Mapped[ProviderType] = mapped_column(
        Enum(ProviderType, native_enum=False, length=32),
        nullable=False,
    )
    modelSizeClass: Mapped[ModelSizeClass] = mapped_column(
        "model_size_class",
        Enum(ModelSizeClass, native_enum=False, length=16),
        nullable=False,
    )
    eligibleRegions: Mapped[list[str]] = mapped_column(
        "eligible_regions",
        ARRAY(String(100)),
        nullable=False,
        default=list,
    )
    vmSku: Mapped[str] = mapped_column("vm_sku", String(100), nullable=False)
    capacityAssumptions: Mapped[dict[str, Any]] = mapped_column(
        "capacity_assumptions",
        JSONB,
        nullable=False,
        default=dict,
    )
    configurableInputs: Mapped[dict[str, Any]] = mapped_column(
        "configurable_inputs",
        JSONB,
        nullable=False,
        default=dict,
    )
    knownLimitations: Mapped[list[str]] = mapped_column(
        "known_limitations",
        ARRAY(Text()),
        nullable=False,
        default=list,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
