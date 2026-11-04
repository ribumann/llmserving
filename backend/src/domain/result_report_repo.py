from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.enums import CompletenessIndicator
from src.domain.result_report import ResultReport

QUALITY_STATUSES = ("passed", "failed", "errored", "skipped", "incomplete")


def build_quality_aggregate(statuses: list[str]) -> dict[str, int | float]:
    counts = {status: 0 for status in QUALITY_STATUSES}
    for status in statuses:
        if status in counts:
            counts[status] += 1
    total = len(statuses)
    passed = counts["passed"]
    pass_rate = (passed / total) if total else 0.0
    return {
        "totalCases": total,
        "passed": passed,
        "failed": counts["failed"],
        "errored": counts["errored"],
        "skipped": counts["skipped"],
        "incomplete": counts["incomplete"],
        "passRate": round(pass_rate, 4),
    }


class ResultReportRepository:
    def get_by_run_id(self, session: Session, run_id: str) -> ResultReport | None:
        if hasattr(session, "result_reports"):
            for item in session.result_reports.values():
                if item.runId == run_id:
                    return item
            return None
        return session.execute(
            select(ResultReport).where(ResultReport.runId == run_id)
        ).scalar_one_or_none()

    def upsert(
        self,
        session: Session,
        *,
        run_id: str,
        quality: dict[str, Any] | None,
        performance: dict[str, Any] | None,
        completeness_indicator: CompletenessIndicator,
        reference_execution_profile_ref: str | None = None,
    ) -> ResultReport:
        report = self.get_by_run_id(session, run_id)
        if report is None:
            report = ResultReport(
                resultReportId=f"report-{uuid4().hex[:12]}",
                runId=run_id,
                quality=deepcopy(quality),
                performance=deepcopy(performance),
                completenessIndicator=completeness_indicator,
                referenceExecutionProfileRef=reference_execution_profile_ref,
            )
        else:
            report.quality = deepcopy(quality)
            report.performance = deepcopy(performance)
            report.completenessIndicator = completeness_indicator
            report.referenceExecutionProfileRef = reference_execution_profile_ref
        session.add(report)
        return report

    @staticmethod
    def progress(report: ResultReport | None) -> dict[str, int]:
        quality = dict(report.quality or {}) if report is not None else {}
        aggregate = dict(quality.get("aggregate") or {})
        total = int(aggregate.get("totalCases") or 0)
        incomplete = int(aggregate.get("incomplete") or 0)
        return {"totalCases": total, "completedCases": max(total - incomplete, 0)}
