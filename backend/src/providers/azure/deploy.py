"""Pre-dispatches the `model_deployment` Container Apps Job directly (carrying
the real Hugging Face token, FR-082/FR-083), then hands off monitoring to the
Durable Functions orchestration app via `preDispatchedExecutionName` (T140).

Unlike provision/teardown, `deploy` never goes through the Functions app's own
`dispatch_job` activity - the credential-carrying job-start call must never
pass through, or be logged by, the Functions app (see functions_client.py's
module docstring).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from src.config import Settings
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DeploymentRevisionState, WorkflowStatus, WorkflowType
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import EnvironmentLockService
from src.domain.orchestration_workflow_service import OrchestrationWorkflowService
from src.domain.workflow_reconciliation import DEPLOYMENT_REVISION_ID_KEY
from src.providers.azure.container_jobs import JobDispatchResult, dispatch_job
from src.providers.azure.functions_client import OrchestrationFunctionsClient
from src.providers.base import DeploymentHandle


@dataclass(slots=True, frozen=True)
class DeploymentContext:
    environmentId: str
    deploymentRevisionId: str
    operationId: str
    actorEmail: str
    engineId: str
    modelConfig: Mapping[str, Any]
    inferenceConfig: Mapping[str, Any]
    targetEnvironment: Mapping[str, Any]
    hfToken: str = ""


JobDispatcher = Callable[..., JobDispatchResult]
FunctionsClientFactory = Callable[[], OrchestrationFunctionsClient]


def _serving_settings_to_extra_args(serving_settings: Mapping[str, Any]) -> list[str]:
    """Turns `inferenceConfig.servingSettings` (e.g. {"max_model_len": 8192,
    "gpu_memory_utilization": 0.9}) into `vllm serve` CLI flags.

    Without this, vLLM falls back to the model's native max sequence length
    (e.g. 40960 for Qwen3), which reliably exceeds available KV cache memory
    on single-GPU demo hardware (T4/A10) and crash-loops the container even
    though the operator already configured a smaller `max_model_len`.
    """
    args: list[str] = []
    for key, value in serving_settings.items():
        flag = f"--{str(key).replace('_', '-')}"
        args.append(flag)
        args.append(str(value))
    return args


class AzureDeployer:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        telemetry: Any | None = None,
        functions_client_factory: FunctionsClientFactory | None = None,
        job_dispatcher: JobDispatcher = dispatch_job,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._telemetry = telemetry
        self._functions_client_factory = functions_client_factory or OrchestrationFunctionsClient
        self._job_dispatcher = job_dispatcher
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="azure-deploy"
        )
        self._workflow_service = OrchestrationWorkflowService()

    def submit(self, context: DeploymentContext) -> DeploymentHandle:
        self._executor.submit(self._run, context)
        return DeploymentHandle(
            operationId=context.operationId,
            deploymentRevisionId=context.deploymentRevisionId,
            phase="accepted",
            state=DeploymentRevisionState.DEPLOYING.value,
            diagnostics=[],
        )

    def _run(self, context: DeploymentContext) -> None:
        workflow_id: str | None = None
        try:
            with self._session_factory() as session:
                workflow = self._workflow_service.create_workflow(
                    session,
                    environment_id=context.environmentId,
                    operation_id=context.operationId,
                    workflow_type=WorkflowType.DEPLOY,
                )
                self._workflow_service.record_progress(
                    session,
                    workflow_id=workflow.workflowId,
                    diagnostics={DEPLOYMENT_REVISION_ID_KEY: context.deploymentRevisionId},
                )
                self._mark_revision(
                    session,
                    context=context,
                    lifecycle_state=DeploymentRevisionState.DEPLOYING,
                    phase="dispatching",
                    health={"status": "unknown", "diagnostics": []},
                )
                workflow_id = workflow.workflowId
                session.commit()

            # `modelRepo` must be the actual Hugging Face repo id (e.g.
            # "Qwen/Qwen3-4B") - it is passed verbatim as `vllm serve --model`
            # (see jobs/model_deployment/entrypoint.py, infra/demo/cloud-init.tftpl).
            # `resolvedCheckpointRef` is a *revision within* that repo (default
            # "main", mirrors `ModelCatalogEntry.checkpointRef`) and is never a
            # loadable model id on its own - passing it alone previously caused
            # every vLLM container to try (and fail) to load a model literally
            # named "main". Fall back to `resolvedCheckpointRef`/`modelRepo` for
            # callers that don't yet supply `huggingFaceRepoId`.
            model_repo = str(
                context.modelConfig.get("huggingFaceRepoId")
                or context.modelConfig.get("resolvedCheckpointRef")
                or context.modelConfig.get("modelRepo")
                or ""
            )
            revision = str(context.modelConfig.get("resolvedCheckpointRef") or "main")
            serving_settings = context.inferenceConfig.get("servingSettings") or {}
            extra_args = _serving_settings_to_extra_args(serving_settings)
            job_result = self._job_dispatcher(
                self._settings.container_apps_resource_group or "",
                self._settings.job_name_model_deployment or "",
                {
                    "WORKFLOW_ID": workflow_id,
                    "JOB_INPUT_JSON": json.dumps(
                        {
                            "environmentId": context.environmentId,
                            "modelRepo": model_repo,
                            "revision": revision,
                            "hfToken": context.hfToken,
                            "extraArgs": extra_args,
                        }
                    ),
                },
            )

            with self._functions_client_factory() as functions_client:
                functions_client.start_orchestration(
                    workflow_id=workflow_id,
                    workflow_type="deploy",
                    pre_dispatched_execution_name=job_result.execution_name,
                )
        except Exception as exc:  # pragma: no cover - state asserted through tests
            self._fail(context, workflow_id=workflow_id, error=exc)

    def _mark_revision(
        self,
        session: Session,
        *,
        context: DeploymentContext,
        lifecycle_state: DeploymentRevisionState,
        phase: str,
        health: dict[str, Any] | None = None,
        diagnostics: list[str] | None = None,
    ) -> None:
        revision = session.get(DeploymentRevision, context.deploymentRevisionId)
        environment = session.get(DemoEnvironment, context.environmentId)
        if revision is not None:
            revision.lifecycleState = lifecycle_state
            if health is not None:
                revision.health = health
            session.add(revision)
        if environment is not None:
            provider_state = dict(environment.providerState or {})
            provider_state["currentOperation"] = {
                "operationId": context.operationId,
                "phase": phase,
                "state": lifecycle_state.value,
                "diagnostics": diagnostics or list((health or {}).get("diagnostics") or []),
            }
            environment.providerState = provider_state
            environment.lastModifiedBy = context.actorEmail
            session.add(environment)

    def _fail(
        self, context: DeploymentContext, *, workflow_id: str | None, error: Exception
    ) -> None:
        with self._session_factory() as session:
            if workflow_id is not None:
                try:
                    self._workflow_service.complete_workflow(
                        session,
                        workflow_id=workflow_id,
                        status=WorkflowStatus.FAILED,
                        phase="failed",
                        diagnostics={"error": str(error)},
                    )
                except Exception:
                    pass  # workflow may already be terminal (e.g. a racing callback)

            self._mark_revision(
                session,
                context=context,
                lifecycle_state=DeploymentRevisionState.DEPLOYMENT_FAILED,
                phase="failed",
                health={"status": "unhealthy", "diagnostics": [str(error)]},
                diagnostics=[str(error)],
            )

            if workflow_id is None:
                environment = session.get(DemoEnvironment, context.environmentId)
                if environment is not None:
                    try:
                        EnvironmentLockService().release(
                            session,
                            environment_id=context.environmentId,
                            operation_id=context.operationId,
                            force=True,
                        )
                    except Exception:
                        environment.activeOperationId = None
            session.commit()

        if self._telemetry is not None:
            self._telemetry.emit(
                operation_id=context.operationId,
                event_type="provider.deploy.failed",
                payload={
                    "environmentId": context.environmentId,
                    "deploymentRevisionId": context.deploymentRevisionId,
                    "state": DeploymentRevisionState.DEPLOYMENT_FAILED.value,
                },
                environment_id=context.environmentId,
            )
