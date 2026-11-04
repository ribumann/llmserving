from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.errors import with_request_id
from src.domain.catalog import ModelCatalogEntry
from src.domain.profile import CloudDeploymentProfile
from src.persistence.db import get_db_session

router = APIRouter(tags=["catalog"])


def _enum_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return value


def _serialize_profile(profile: CloudDeploymentProfile) -> dict[str, object]:
    return {
        "profileId": profile.profileId,
        "provider": _enum_value(profile.provider),
        "modelSizeClass": _enum_value(profile.modelSizeClass),
        "eligibleRegions": list(profile.eligibleRegions),
        "vmSku": profile.vmSku,
        "capacityAssumptions": dict(profile.capacityAssumptions or {}),
        "configurableInputs": dict(profile.configurableInputs or {}),
        "knownLimitations": list(profile.knownLimitations),
        "version": profile.version,
    }


def _serialize_catalog_entry(entry: ModelCatalogEntry) -> dict[str, object]:
    return {
        "catalogEntryId": entry.catalogEntryId,
        "family": _enum_value(entry.family),
        "sizeClass": _enum_value(entry.sizeClass),
        "huggingFaceRepoId": entry.huggingFaceRepoId,
        "checkpointRef": entry.checkpointRef,
        "isGated": entry.isGated,
        "license": entry.license,
        "compatibleProfileIds": list(entry.compatibleProfileIds),
        "quantizationRequired": entry.quantizationRequired,
        "notes": entry.notes,
    }


@router.get("/profiles")
def list_profiles(
    request: Request, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    profiles = session.scalars(
        select(CloudDeploymentProfile).order_by(CloudDeploymentProfile.profileId)
    ).all()
    return with_request_id(
        {"profiles": [_serialize_profile(profile) for profile in profiles]},
        getattr(request.state, "request_id", None),
    )


@router.get("/catalog")
def list_catalog(request: Request, session: Session = Depends(get_db_session)) -> dict[str, object]:
    entries = session.scalars(
        select(ModelCatalogEntry).order_by(ModelCatalogEntry.catalogEntryId)
    ).all()
    return with_request_id(
        {"catalog": [_serialize_catalog_entry(entry) for entry in entries]},
        getattr(request.state, "request_id", None),
    )
