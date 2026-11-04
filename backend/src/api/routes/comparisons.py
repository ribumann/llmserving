from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.errors import ApiError, with_request_id
from src.domain.comparison import Comparison
from src.domain.comparison_builder import ComparisonBuilder, ComparisonInputError
from src.persistence.db import get_db_session

router = APIRouter(tags=["comparisons"])


class ComparisonCreateRequest(BaseModel):
    reportIds: list[str]
    # Accepted for client convenience (e.g. labeling a bookmarked comparison
    # URL) but not persisted: data-model.md's Comparison entity has no title
    # field, and the value never appears in the response.
    title: str | None = None


def _serialize(comparison: Comparison, reports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "comparisonId": comparison.comparisonId,
        "comparabilityStatus": comparison.comparabilityStatus.value,
        "reasons": list(comparison.comparabilityReasons or []),
        "reports": reports,
        "sections": [
            {
                "title": "Configuration",
                "items": list((comparison.configurationDiff or {}).get("rows") or []),
            },
            {
                "title": "Quality",
                "items": list((comparison.qualityDiff or {}).get("rows") or []),
            },
            {
                "title": "Performance",
                "items": list((comparison.performanceDiff or {}).get("rows") or []),
            },
            {
                "title": "Failures",
                "items": list((comparison.failureDiff or {}).get("rows") or []),
            },
            {
                "title": "Accelerator utilization",
                "items": list((comparison.utilizationDiff or {}).get("rows") or []),
            },
        ],
    }


@router.post("/comparisons", status_code=201)
def create_comparison(
    payload: ComparisonCreateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    if len(payload.reportIds) < 2:
        raise ApiError(
            status_code=400,
            code="insufficient_reports",
            message="A comparison requires at least two report ids.",
            details={"reportIds": payload.reportIds},
        )

    comparison_id = f"comparison-{uuid4().hex[:12]}"
    builder = ComparisonBuilder(session)
    try:
        comparison, reports = builder.build(
            comparison_id=comparison_id, report_ids=payload.reportIds
        )
    except ComparisonInputError as exc:
        raise ApiError(
            status_code=404,
            code="result_report_not_found",
            message=str(exc),
            details={"reportIds": payload.reportIds},
        ) from exc

    session.add(comparison)
    session.commit()

    return with_request_id(
        _serialize(comparison, reports),
        getattr(request.state, "request_id", None),
    )


@router.get("/comparisons/{comparison_id}")
def get_comparison(
    comparison_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    comparison = session.get(Comparison, comparison_id)
    if comparison is None:
        raise ApiError(
            status_code=404,
            code="comparison_not_found",
            message=f"Comparison '{comparison_id}' was not found.",
            details={"comparisonId": comparison_id},
        )

    reports = ComparisonBuilder(session).resolve_reports_payload(comparison)
    return with_request_id(
        _serialize(comparison, reports),
        getattr(request.state, "request_id", None),
    )
