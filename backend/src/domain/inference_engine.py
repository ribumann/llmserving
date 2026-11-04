from __future__ import annotations

from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.persistence.db import Base


class InferenceEngine(Base):
    __tablename__ = "inference_engines"

    engineId: Mapped[str] = mapped_column("engine_id", String(50), primary_key=True)
    adapterContractVersion: Mapped[str] = mapped_column(
        "adapter_contract_version", String(32), nullable=False
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
