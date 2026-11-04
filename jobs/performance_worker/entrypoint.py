"""performance_worker Container Apps Job (T136): runs a concurrent load test
against the deployed vLLM endpoint and reports a Result Report `performance`
object (data-model.md Result Report; Performance Workload entity).

Invocation contract (env vars set by the Durable Functions `dispatch_job`
activity as a job-start template override):

- `WORKFLOW_ID`    - the Orchestration Workflow this run reports against.
- `JOB_INPUT_JSON` - JSON object: {"environmentId": str, "runId": str,
                      "namePrefix": str (optional, default "llm"),
                      "workload": {"concurrency": int, "requestCount": int,
                                    "prompt": str,
                                    "safetyLimits": {"maxConcurrency": int,
                                                      "maxRequests": int}
                                    (optional)}}.

Only end-to-end request latency and throughput are measured here (a plain
HTTP client can time a full response); TTFT and inter-token latency require
streaming the response token-by-token, which this job does not yet do, so
both are reported as unavailable rather than fabricated
(contracts/engine-interface.md: "MUST label utilization data as unavailable
rather than fabricate a value"). Accelerator utilization is unavailable for
the same reason - this job has no access to the VM's GPU telemetry.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
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

# Hard ceilings applied regardless of what a caller requests (Edge Cases: "workload
# safety limits" / data-model.md Performance Workload's `safetyLimits`) so a
# misconfigured or malicious job input can't runaway-load the shared demo VM.
HARD_MAX_CONCURRENCY = 32
HARD_MAX_REQUESTS = 2000


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1)))
    return sorted_values[index]


def run(
    *,
    workflow_id: str,
    subscription_id: str,
    environment_id: str,
    run_id: str,
    prompt: str,
    concurrency: int,
    request_count: int,
    name_prefix: str,
    callback: WorkflowCallbackClient,
    resolve_ip: Any = resolve_private_ip,
    submit: Any = submit_prompt,
) -> None:
    if request_count <= 0:
        raise CallbackClientError("'workload.requestCount' must be a positive integer.")

    concurrency = max(1, min(concurrency, HARD_MAX_CONCURRENCY))
    request_count = min(request_count, HARD_MAX_REQUESTS)

    callback.report_progress(workflow_id, phase="resolving-endpoint")
    private_ip = resolve_ip(subscription_id, environment_id, name_prefix=name_prefix)
    base_url = vllm_base_url(private_ip)

    callback.report_progress(
        workflow_id,
        phase="running-load-test",
        diagnostics={"concurrency": concurrency, "requestCount": request_count},
    )

    latencies: list[float] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for result in pool.map(lambda _: submit(base_url, prompt), range(request_count)):
            if result.ok:
                latencies.append(result.latency_seconds)
            else:
                failures += 1

    sorted_latencies = sorted(latencies)
    total_latency = sum(latencies)
    throughput = (len(latencies) / total_latency) if total_latency > 0 else 0.0

    callback.complete_workflow(
        workflow_id,
        status="completed",
        phase="completed",
        diagnostics={
            "runId": run_id,
            "performance": {
                "endToEndLatencySeconds": {
                    "p50": _percentile(sorted_latencies, 0.5),
                    "p95": _percentile(sorted_latencies, 0.95),
                    "unit": "seconds",
                },
                "timeToFirstToken": {"available": False},
                "interTokenLatency": {"available": False},
                "throughput": {"value": throughput, "unit": "requests_per_second"},
                "failures": {"count": failures, "total": request_count},
                "acceleratorUtilization": {"available": False},
            },
            "completenessIndicator": "complete" if failures == 0 else "partial",
        },
    )


def main() -> int:
    workflow_id = required_env("WORKFLOW_ID")
    logger = configure_job_telemetry(workflow_id, logger_name="performance_worker")
    payload = job_input_from_env()
    environment_id = str(payload.get("environmentId", ""))
    run_id = str(payload.get("runId", ""))
    name_prefix = str(payload.get("namePrefix", "llm"))
    workload = dict(payload.get("workload", {}))
    prompt = str(workload.get("prompt", "Hello, how are you?"))
    concurrency = int(workload.get("concurrency", 1))
    request_count = int(workload.get("requestCount", 0))
    subscription_id = required_env("AZURE_SUBSCRIPTION_ID")

    logger.info("Starting performance run %s for environment %s", run_id, environment_id)
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
                prompt=prompt,
                concurrency=concurrency,
                request_count=request_count,
                name_prefix=name_prefix,
                callback=callback,
            )
        except Exception as exc:  # noqa: BLE001 - last-resort safety net, see terraform_runner
            logger.exception("Performance run %s failed", run_id)
            callback.complete_workflow(
                workflow_id,
                status="failed",
                phase="failed",
                diagnostics={"runId": run_id, "error": str(exc)},
            )
            return 1
    logger.info("Completed performance run %s", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
