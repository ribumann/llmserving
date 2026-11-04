"""evaluation_worker Container Apps Job (T136): runs golden-dataset
prompt cases against the deployed vLLM endpoint and reports a Result Report
`quality` object back through the internal callback API (data-model.md's
Result Report entity; FastAPI persists the actual Result Report record from
these diagnostics per data-model.md's Orchestration Workflow validation note).

Invocation contract (env vars set by the Durable Functions `dispatch_job`
activity as a job-start template override):

- `WORKFLOW_ID`    - the Orchestration Workflow this run reports against.
- `JOB_INPUT_JSON` - JSON object: {"environmentId": str, "runId": str,
                      "namePrefix": str (optional, default "llm"),
                      "cases": [{"caseId": str, "prompt": str,
                                 "deterministicCheck": str (optional)}]}.

A case's `status` is `pass`/`fail` when a `deterministicCheck` substring was
supplied and matched/didn't match the response, `skipped` when no check was
supplied (no automated verdict possible), or `errored` when the request
or rule fails. Canonical input/evaluationRule cases use the shared backend
scorer; legacy substring checks also grade the final answer, not reasoning.
This does not certify benchmark, invocation or report parity with the API.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.azure_demo_vm import resolve_private_ip, vllm_base_url  # noqa: E402
from common.callback_client import (  # noqa: E402
    CallbackClientError,
    WorkflowCallbackClient,
    job_input_from_env,
    required_env,
)
from common.telemetry import configure_job_telemetry  # noqa: E402
from common.vllm_client import submit_prompt  # noqa: E402
from src.evaluation.scoring import evaluate_golden_case  # noqa: E402


def _evaluate_case(base_url: str, case: dict[str, Any], submit: Any) -> dict[str, Any]:
    case_id = str(case.get("caseId", ""))
    prompt = str(case.get("input", case.get("prompt", "")))
    deterministic_check = case.get("deterministicCheck")

    result = submit(base_url, prompt)
    if not result.ok:
        return {
            "caseId": case_id,
            "status": "errored",
            "responseText": "",
            "latencySeconds": result.latency_seconds,
            "error": result.error,
        }

    if deterministic_check is None and not case.get("evaluationRule"):
        status = "skipped"
    else:
        rule = (
            case
            if case.get("evaluationRule")
            else {
                "evaluationRule": "contains",
                "expectedSubstring": str(deterministic_check),
            }
        )
        try:
            status = "pass" if evaluate_golden_case(rule, result.text) else "fail"
        except (ValueError, re.error) as error:
            return {
                "caseId": case_id,
                "status": "errored",
                "responseText": result.text,
                "latencySeconds": result.latency_seconds,
                "error": str(error),
            }

    return {
        "caseId": case_id,
        "status": status,
        "responseText": result.text,
        "latencySeconds": result.latency_seconds,
    }


def run(
    *,
    workflow_id: str,
    subscription_id: str,
    environment_id: str,
    run_id: str,
    cases: list[dict[str, Any]],
    name_prefix: str,
    callback: WorkflowCallbackClient,
    resolve_ip: Any = resolve_private_ip,
    submit: Any = submit_prompt,
) -> None:
    if not cases:
        raise CallbackClientError("JOB_INPUT_JSON must include a non-empty 'cases' list.")

    callback.report_progress(workflow_id, phase="resolving-endpoint")
    private_ip = resolve_ip(subscription_id, environment_id, name_prefix=name_prefix)
    base_url = vllm_base_url(private_ip)

    evaluated: list[dict[str, Any]] = []
    total = len(cases)
    for index, case in enumerate(cases):
        evaluated.append(_evaluate_case(base_url, case, submit))
        callback.report_progress(
            workflow_id,
            phase=f"evaluating case {index + 1}/{total}",
            diagnostics={"completed": index + 1, "total": total},
        )

    counts = {"passCount": 0, "failCount": 0, "erroredCount": 0, "skippedCount": 0}
    for case_result in evaluated:
        counts[f"{case_result['status']}Count"] = counts.get(f"{case_result['status']}Count", 0) + 1

    completeness = "complete" if counts["erroredCount"] == 0 else "partial"

    callback.complete_workflow(
        workflow_id,
        status="completed",
        phase="completed",
        diagnostics={
            "runId": run_id,
            "quality": {
                "cases": evaluated,
                "aggregate": {**counts, "totalCount": total},
            },
            "completenessIndicator": completeness,
        },
    )


def main() -> int:
    workflow_id = required_env("WORKFLOW_ID")
    logger = configure_job_telemetry(workflow_id, logger_name="evaluation_worker")
    payload = job_input_from_env()
    environment_id = str(payload.get("environmentId", ""))
    run_id = str(payload.get("runId", ""))
    name_prefix = str(payload.get("namePrefix", "llm"))
    cases = list(payload.get("cases", []))
    subscription_id = required_env("AZURE_SUBSCRIPTION_ID")

    logger.info("Starting evaluation run %s for environment %s", run_id, environment_id)
    with WorkflowCallbackClient() as callback:
        try:
            if not environment_id:
                raise CallbackClientError(
                    "JOB_INPUT_JSON must include a non-empty 'environmentId'."
                )
            run(
                workflow_id=workflow_id,
                subscription_id=subscription_id,
                environment_id=environment_id,
                run_id=run_id,
                cases=cases,
                name_prefix=name_prefix,
                callback=callback,
            )
        except Exception as exc:  # noqa: BLE001 - last-resort safety net, see terraform_runner
            logger.exception("Evaluation run %s failed", run_id)
            callback.complete_workflow(
                workflow_id,
                status="failed",
                phase="failed",
                diagnostics={"runId": run_id, "error": str(exc)},
            )
            return 1
    logger.info("Completed evaluation run %s", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
