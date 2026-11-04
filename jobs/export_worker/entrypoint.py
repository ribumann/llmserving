"""export_worker Container Apps Job (T136): serializes a Result Report to
CSV/JSON and uploads it to the `exports` blob container in `artifacts_storage`
(infra/control/main.tf), reporting the resulting blob path back through the
internal callback API.

Invocation contract (env vars set by the Durable Functions `dispatch_job`
activity as a job-start template override):

- `WORKFLOW_ID`    - the Orchestration Workflow this run reports against.
- `JOB_INPUT_JSON` - JSON object: {"runId": str, "format": "csv" | "json"
                      (optional, default "json"), "reportData": dict}.
                      `reportData` is a Result Report-shaped payload FastAPI
                      serializes and passes in directly - this job has no
                      database credentials of its own and never queries
                      FastAPI's domain data itself (data-model.md's
                      Orchestration Workflow validation note: "the workflow
                      itself carries no domain state").

Static env vars (set on every job by infra/control/main.tf, unused by other
jobs): `ARTIFACTS_STORAGE_ACCOUNT`, `EXPORTS_CONTAINER`.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.blob_export import upload_export  # noqa: E402
from common.callback_client import (  # noqa: E402
    CallbackClientError,
    WorkflowCallbackClient,
    job_input_from_env,
    required_env,
)
from common.telemetry import configure_job_telemetry  # noqa: E402

_ALLOWED_FORMATS = {"csv", "json"}


def _flatten(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flattens a Result Report's per-case quality results (if present) into
    CSV-friendly rows; falls back to a single summary row otherwise."""
    quality = report_data.get("quality") or {}
    cases = quality.get("cases")
    if isinstance(cases, list) and cases:
        return [dict(case) for case in cases]
    return [dict(report_data)]


def _serialize(report_data: dict[str, Any], export_format: str) -> tuple[bytes, str]:
    if export_format == "json":
        return json.dumps(report_data, indent=2).encode("utf-8"), "application/json"

    rows = _flatten(report_data)
    buffer = io.StringIO()
    fieldnames = sorted({key for row in rows for key in row})
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8"), "text/csv"


def run(
    *,
    workflow_id: str,
    run_id: str,
    export_format: str,
    report_data: dict[str, Any],
    account_name: str,
    container_name: str,
    callback: WorkflowCallbackClient,
    uploader: Any = upload_export,
) -> None:
    if export_format not in _ALLOWED_FORMATS:
        raise CallbackClientError(
            f"Unsupported export format '{export_format}'; "
            f"expected one of {sorted(_ALLOWED_FORMATS)}."
        )

    callback.report_progress(workflow_id, phase="serializing")
    content, content_type = _serialize(report_data, export_format)

    callback.report_progress(workflow_id, phase="uploading")
    blob_name = f"{run_id or workflow_id}.{export_format}"
    blob_path = uploader(
        account_name, container_name, blob_name, content, content_type=content_type
    )

    callback.complete_workflow(
        workflow_id,
        status="completed",
        phase="completed",
        diagnostics={"runId": run_id, "format": export_format, "blobPath": blob_path},
    )


def main() -> int:
    workflow_id = required_env("WORKFLOW_ID")
    logger = configure_job_telemetry(workflow_id, logger_name="export_worker")
    payload = job_input_from_env()
    run_id = str(payload.get("runId", ""))
    export_format = str(payload.get("format", "json"))
    report_data = dict(payload.get("reportData", {}))
    account_name = required_env("ARTIFACTS_STORAGE_ACCOUNT")
    container_name = required_env("EXPORTS_CONTAINER")

    logger.info("Starting export run %s format=%s", run_id, export_format)
    with WorkflowCallbackClient() as callback:
        try:
            if not report_data:
                raise CallbackClientError("JOB_INPUT_JSON must include a non-empty 'reportData'.")
            run(
                workflow_id=workflow_id,
                run_id=run_id,
                export_format=export_format,
                report_data=report_data,
                account_name=account_name,
                container_name=container_name,
                callback=callback,
            )
        except Exception as exc:  # noqa: BLE001 - last-resort safety net, see terraform_runner
            logger.exception("Export run %s failed", run_id)
            callback.complete_workflow(
                workflow_id,
                status="failed",
                phase="failed",
                diagnostics={"runId": run_id, "error": str(exc)},
            )
            return 1
    logger.info("Completed export run %s", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
