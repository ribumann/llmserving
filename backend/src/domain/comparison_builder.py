from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.domain.comparability import assess_run_comparability
from src.domain.comparison import Comparison
from src.domain.deployment_revision_repo import DeploymentRevisionRepository
from src.domain.experiment_run import ExperimentRun
from src.domain.result_report import ResultReport


class ComparisonInputError(ValueError):
    """Raised when the requested report ids cannot form a valid comparison."""


def _quality_row(report_id: str, quality: dict[str, Any] | None) -> dict[str, Any] | None:
    if not quality:
        return None
    aggregate = dict(quality.get("aggregate") or {})
    return {
        "reportId": report_id,
        "totalCases": aggregate.get("totalCases"),
        "passed": aggregate.get("passed"),
        "failed": aggregate.get("failed"),
        "errored": aggregate.get("errored"),
        "incomplete": aggregate.get("incomplete"),
        "passRate": aggregate.get("passRate"),
    }


def _performance_row(report_id: str, performance: dict[str, Any] | None) -> dict[str, Any] | None:
    if not performance:
        return None
    metrics = dict(performance.get("metrics") or {})
    return {
        "reportId": report_id,
        "timeToFirstTokenMs": metrics.get("timeToFirstTokenMs"),
        "interTokenLatencyMs": metrics.get("interTokenLatencyMs"),
        "endToEndLatencyMs": metrics.get("endToEndLatencyMs"),
        "throughputTokensPerSec": metrics.get("throughputTokensPerSec"),
    }


def _utilization_row(report_id: str, performance: dict[str, Any] | None) -> dict[str, Any] | None:
    if not performance:
        return None
    utilization = dict(performance.get("acceleratorUtilization") or {})
    if not utilization.get("available"):
        return None
    return {
        "reportId": report_id,
        "details": utilization.get("details"),
    }


def _failure_row(
    report_id: str, quality: dict[str, Any] | None, performance: dict[str, Any] | None
) -> dict[str, Any] | None:
    quality_aggregate = dict((quality or {}).get("aggregate") or {})
    request_failures = dict((performance or {}).get("requestFailures") or {})
    row = {
        "reportId": report_id,
        "qualityFailed": quality_aggregate.get("failed"),
        "qualityErrored": quality_aggregate.get("errored"),
        "performanceFailedRequests": request_failures.get("count"),
        "performanceTotalRequests": request_failures.get("total"),
    }
    if all(value is None for key, value in row.items() if key != "reportId"):
        return None
    return row


class ComparisonBuilder:
    """Builds a retained `Comparison` (data-model.md "Comparison", FR-031/032)
    from 2+ `Result Report` ids, deriving every diff and the comparability
    verdict from each report's run's immutable `environmentContextSnapshot`
    (FR-020) rather than live environment/revision state, so a later redeploy
    or teardown never changes what an already-built comparison says.
    """

    def __init__(
        self,
        session: Session,
        *,
        revisions: DeploymentRevisionRepository | None = None,
    ) -> None:
        self._session = session
        self._revisions = revisions or DeploymentRevisionRepository()

    def build(
        self, *, comparison_id: str, report_ids: list[str]
    ) -> tuple[Comparison, list[dict[str, Any]]]:
        if len(report_ids) < 2:
            raise ComparisonInputError("A comparison requires at least two report ids.")

        contexts = [self._load_context(report_id) for report_id in report_ids]
        snapshots = [context["snapshot"] for context in contexts]
        comparability_status, reasons = assess_run_comparability(snapshots)

        reports_payload: list[dict[str, Any]] = []
        configuration_rows: list[dict[str, Any]] = []
        quality_rows: list[dict[str, Any]] = []
        performance_rows: list[dict[str, Any]] = []
        failure_rows: list[dict[str, Any]] = []
        utilization_rows: list[dict[str, Any]] = []

        for context in contexts:
            report: ResultReport = context["report"]
            run: ExperimentRun = context["run"]
            snapshot = context["snapshot"]
            revision = self._revisions.get(self._session, run.deploymentRevisionId)

            reports_payload.append(
                {
                    "reportId": report.resultReportId,
                    "revisionId": run.deploymentRevisionId,
                    "environmentId": snapshot.get("environmentId"),
                }
            )

            model_configuration = dict(snapshot.get("modelConfiguration") or {})
            inference_configuration = dict(snapshot.get("inferenceConfiguration") or {})
            configuration_rows.append(
                {
                    "reportId": report.resultReportId,
                    "checkpoint": model_configuration.get("resolvedCheckpointRef"),
                    "servingSettings": inference_configuration.get("servingSettings"),
                    "generationSettings": inference_configuration.get("generationSettings"),
                    "profileId": snapshot.get("profileId"),
                    "region": snapshot.get("region"),
                    "provider": snapshot.get("provider"),
                    "revisionLifecycleState": (
                        revision.lifecycleState.value if revision is not None else None
                    ),
                }
            )

            quality_row = _quality_row(report.resultReportId, report.quality)
            if quality_row is not None:
                quality_rows.append(quality_row)

            performance_row = _performance_row(report.resultReportId, report.performance)
            if performance_row is not None:
                performance_rows.append(performance_row)

            utilization_row = _utilization_row(report.resultReportId, report.performance)
            if utilization_row is not None:
                utilization_rows.append(utilization_row)

            failure_row = _failure_row(report.resultReportId, report.quality, report.performance)
            if failure_row is not None:
                failure_rows.append(failure_row)

        comparison = Comparison(
            comparisonId=comparison_id,
            resultReportIds=[context["report"].resultReportId for context in contexts],
            configurationDiff={"rows": configuration_rows},
            qualityDiff={"rows": quality_rows},
            performanceDiff={"rows": performance_rows},
            failureDiff={"rows": failure_rows},
            utilizationDiff={"rows": utilization_rows},
            comparabilityStatus=comparability_status,
            comparabilityReasons=reasons,
        )
        return comparison, reports_payload

    def resolve_reports_payload(self, comparison: Comparison) -> list[dict[str, Any]]:
        """Re-derives the `reports` summary for an already-built `Comparison`
        (used by `GET /comparisons/{comparisonId}`, which only has the
        retained diff rows on hand, not the original request's contexts)."""
        payload: list[dict[str, Any]] = []
        for report_id in comparison.resultReportIds:
            context = self._load_context(report_id, required=False)
            if context is None:
                payload.append({"reportId": report_id, "revisionId": None, "environmentId": None})
                continue
            payload.append(
                {
                    "reportId": report_id,
                    "revisionId": context["run"].deploymentRevisionId,
                    "environmentId": context["snapshot"].get("environmentId"),
                }
            )
        return payload

    def _load_context(self, report_id: str, *, required: bool = True) -> dict[str, Any] | None:
        report = self._session.get(ResultReport, report_id)
        if report is None:
            if required:
                raise ComparisonInputError(f"Result report '{report_id}' was not found.")
            return None
        run = self._session.get(ExperimentRun, report.runId)
        if run is None:
            if required:
                raise ComparisonInputError(
                    f"Experiment run for result report '{report_id}' was not found."
                )
            return None
        return {
            "report": report,
            "run": run,
            "snapshot": dict(run.environmentContextSnapshot or {}),
        }
