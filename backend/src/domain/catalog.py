from __future__ import annotations

from sqlalchemy import Boolean, Enum, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.enums import ModelFamily, ModelSizeClass
from src.persistence.db import Base


class ModelCatalogEntry(Base):
    __tablename__ = "model_catalog_entries"

    catalogEntryId: Mapped[str] = mapped_column("catalog_entry_id", String(100), primary_key=True)
    family: Mapped[ModelFamily] = mapped_column(
        Enum(ModelFamily, native_enum=False, length=32),
        nullable=False,
    )
    sizeClass: Mapped[ModelSizeClass] = mapped_column(
        "size_class",
        Enum(ModelSizeClass, native_enum=False, length=16),
        nullable=False,
    )
    huggingFaceRepoId: Mapped[str] = mapped_column(
        "hugging_face_repo_id", String(200), nullable=False
    )
    checkpointRef: Mapped[str] = mapped_column("checkpoint_ref", String(200), nullable=False)
    isGated: Mapped[bool] = mapped_column("is_gated", Boolean, nullable=False, default=False)
    license: Mapped[str] = mapped_column(String(200), nullable=False)
    compatibleProfileIds: Mapped[list[str]] = mapped_column(
        "compatible_profile_ids",
        ARRAY(String(100)),
        nullable=False,
        default=list,
    )
    quantizationRequired: Mapped[bool] = mapped_column(
        "quantization_required",
        Boolean,
        nullable=False,
        default=False,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
