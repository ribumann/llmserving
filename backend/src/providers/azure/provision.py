"""Dispatches Terraform apply/destroy to the `terraform_runner` Container Apps
Job via the Durable Functions orchestration app (T140), instead of running
Terraform as a local subprocess.

Local Terraform execution, remote-state blob plumbing, and tfvars-file
management all now live in jobs/terraform_runner/entrypoint.py; this module
only creates/tracks the Orchestration Workflow record, persists the exact
Terraform variables used (so a later teardown can reuse them for `terraform
destroy` without regenerating e.g. a new SSH keypair), and starts the
orchestration. The apply/destroy itself completes asynchronously -
`WorkflowReconciliationService` (wired from internal_workflows.py's POST
/complete route) applies the terminal outcome back onto DemoEnvironment once
the job calls back through Durable Functions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from src.config import Settings
from src.domain.enums import DemoEnvironmentState, WorkflowStatus, WorkflowType
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import (
    EnvironmentLockedError,
    EnvironmentLockService,
    EnvironmentNotFoundError,
)
from src.domain.orchestration_workflow_service import (
    OrchestrationWorkflowService,
    WorkflowNotFoundError,
    WorkflowNotRunningError,
)
from src.providers.azure.functions_client import OrchestrationFunctionsClient
from src.providers.base import ProvisioningHandle, TeardownHandle


class ProvisioningContextMissingError(RuntimeError):
    """Raised when provisioning is invoked without a bound environment context."""


class TeardownVariablesMissingError(RuntimeError):
    """Raised when teardown is requested for an environment with no persisted
    `terraformVariables` to reuse for `terraform destroy` - i.e. it never
    completed a successful apply through this provisioner."""


@dataclass(slots=True, frozen=True)
class ProvisioningContext:
    environmentId: str
    operationId: str
    actorEmail: str
    region: str
    profileId: str
    profileSizeClass: str
    vmSize: str
    bootstrapModelRepo: str
    terraformVariables: dict[str, Any]
    fallbackRegions: list[str]


FunctionsClientFactory = Callable[[], OrchestrationFunctionsClient]


class AzureProvisioner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        telemetry: Any | None = None,
        functions_client_factory: FunctionsClientFactory | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._telemetry = telemetry
        self._functions_client_factory = functions_client_factory or OrchestrationFunctionsClient
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="azure-provision"
        )
        self._lock = Lock()
        self._bound_contexts: dict[tuple[str, str], ProvisioningContext] = {}
        self._workflow_service = OrchestrationWorkflowService()

    def bind_context(self, context: ProvisioningContext) -> None:
        with self._lock:
            self._bound_contexts[(context.profileId, context.region)] = context

    def submit(self, context: ProvisioningContext) -> ProvisioningHandle:
        """Start provisioning immediately for a fully-built context.

        This is the safe, non-racy entry point: unlike bind_context() +
        provisionEnvironment(), which key a shared dict by (profileId, region)
        and are vulnerable to concurrent requests for the same profile/region
        clobbering each other's context, this submits the exact context object
        the caller just built with no intervening lookup.
        """
        self._executor.submit(self._run, context)
        return ProvisioningHandle(
            operationId=context.operationId,
            phase="accepted",
            state=DemoEnvironmentState.PROVISIONING.value,
            diagnostics=[],
        )

    def provisionEnvironment(self, profileId: str, region: str) -> ProvisioningHandle:
        # Kept for ProviderAdapter interface compliance (contracts/provider-interface.md
        # only defines provisionEnvironment(profileId, region)). Prefer submit() when a
        # ProvisioningContext is already in hand, since this path is racy under
        # concurrent requests for the same profile/region.
        context = self._pop_context(profileId=profileId, region=region)
        return self.submit(context)

    def _pop_context(self, *, profileId: str, region: str) -> ProvisioningContext:
        with self._lock:
            context = self._bound_contexts.pop((profileId, region), None)
        if context is None:
            raise ProvisioningContextMissingError(
                f"No provisioning context was bound for profile '{profileId}' in region '{region}'."
            )
        return context

    def _run(self, context: ProvisioningContext) -> None:
        workflow_id: str | None = None
        try:
            workflow_id = self._start_workflow(
                environment_id=context.environmentId,
                operation_id=context.operationId,
                actor_email=context.actorEmail,
                workflow_type=WorkflowType.PROVISION,
                lifecycle_state=DemoEnvironmentState.PROVISIONING,
                terraform_variables=context.terraformVariables,
                extra_diagnostics={
                    "region": context.region,
                    "fallbackRegions": list(context.fallbackRegions),
                },
            )
            with self._functions_client_factory() as functions_client:
                functions_client.start_orchestration(
                    workflow_id=workflow_id,
                    workflow_type="provision",
                    job_input={
                        "action": "apply",
                        "environmentId": context.environmentId,
                        "terraformVariables": context.terraformVariables,
                    },
                )
        except Exception as exc:  # pragma: no cover - asserted via state changes in tests
            self._fail_dispatch(
                environment_id=context.environmentId,
                operation_id=context.operationId,
                actor_email=context.actorEmail,
                lifecycle_state=DemoEnvironmentState.PROVISIONING_FAILED,
                workflow_id=workflow_id,
                telemetry_phase="provision",
                error=exc,
            )

    def start_teardown(
        self, *, environment_id: str, operation_id: str, actor_email: str
    ) -> TeardownHandle:
        """Dispatch `terraform destroy` for an already-provisioned environment,
        reusing the exact `terraformVariables` persisted by a prior successful
        apply (providerState.terraform.variables). A fresh variable set would,
        at minimum, mint a brand-new SSH keypair every time (and Terraform
        would treat that as configuration drift on the running VM)."""
        self._executor.submit(self._run_teardown, environment_id, operation_id, actor_email)
        return TeardownHandle(
            operationId=operation_id,
            phase="accepted",
            state=DemoEnvironmentState.TEARING_DOWN.value,
            diagnostics=[],
        )

    def _run_teardown(self, environment_id: str, operation_id: str, actor_email: str) -> None:
        workflow_id: str | None = None
        try:
            terraform_variables = self._load_terraform_variables(environment_id)
            workflow_id = self._start_workflow(
                environment_id=environment_id,
                operation_id=operation_id,
                actor_email=actor_email,
                workflow_type=WorkflowType.TEARDOWN,
                lifecycle_state=DemoEnvironmentState.TEARING_DOWN,
                terraform_variables=terraform_variables,
                extra_diagnostics={},
            )
            with self._functions_client_factory() as functions_client:
                functions_client.start_orchestration(
                    workflow_id=workflow_id,
                    workflow_type="teardown",
                    job_input={
                        "action": "destroy",
                        "environmentId": environment_id,
                        "terraformVariables": terraform_variables,
                    },
                )
        except Exception as exc:  # pragma: no cover - asserted via state changes in tests
            self._fail_dispatch(
                environment_id=environment_id,
                operation_id=operation_id,
                actor_email=actor_email,
                lifecycle_state=DemoEnvironmentState.TEARDOWN_FAILED,
                workflow_id=workflow_id,
                telemetry_phase="teardown",
                error=exc,
            )

    def _load_terraform_variables(self, environment_id: str) -> dict[str, Any]:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environment_id)
            if environment is None:
                raise TeardownVariablesMissingError(
                    f"Environment '{environment_id}' was not found."
                )
            terraform_state = dict(environment.providerState or {}).get("terraform") or {}
            variables = terraform_state.get("variables")
            if not variables:
                raise TeardownVariablesMissingError(
                    f"Environment '{environment_id}' has no persisted Terraform variables to "
                    "reuse for teardown; it may never have completed provisioning."
                )
            return dict(variables)

    def _start_workflow(
        self,
        *,
        environment_id: str,
        operation_id: str,
        actor_email: str,
        workflow_type: WorkflowType,
        lifecycle_state: DemoEnvironmentState,
        terraform_variables: dict[str, Any],
        extra_diagnostics: dict[str, Any],
    ) -> str:
        with self._session_factory() as session:
            workflow = self._workflow_service.create_workflow(
                session,
                environment_id=environment_id,
                operation_id=operation_id,
                workflow_type=workflow_type,
            )
            self._workflow_service.record_progress(
                session,
                workflow_id=workflow.workflowId,
                diagnostics={"terraformVariables": terraform_variables, **extra_diagnostics},
            )

            environment = session.get(DemoEnvironment, environment_id)
            if environment is not None:
                provider_state = dict(environment.providerState or {})
                provider_state["terraform"] = {"variables": terraform_variables}
                environment.providerState = provider_state
                environment.lifecycleState = lifecycle_state
                environment.lastModifiedBy = actor_email
                session.add(environment)

            session.commit()
            return workflow.workflowId

    def _fail_dispatch(
        self,
        *,
        environment_id: str,
        operation_id: str,
        actor_email: str,
        lifecycle_state: DemoEnvironmentState,
        workflow_id: str | None,
        telemetry_phase: str,
        error: Exception,
    ) -> None:
        """Fail an owned dispatch and release its lock in the same transaction.

        A racing terminal callback or replacement operation must not be overwritten.
        """
        with self._session_factory() as session:
            try:
                if workflow_id is not None:
                    self._workflow_service.complete_workflow(
                        session,
                        workflow_id=workflow_id,
                        status=WorkflowStatus.FAILED,
                        phase="failed",
                        diagnostics={"error": str(error)},
                    )
                else:
                    EnvironmentLockService().release(
                        session,
                        environment_id=environment_id,
                        operation_id=operation_id,
                    )
            except (
                EnvironmentLockedError,
                EnvironmentNotFoundError,
                WorkflowNotFoundError,
                WorkflowNotRunningError,
            ) as exc:
                logging.getLogger(__name__).warning(
                    "Rejected dispatch-failure cleanup environment=%s operation=%s "
                    "workflow=%s reason=%s",
                    environment_id,
                    operation_id,
                    workflow_id,
                    type(exc).__name__,
                )
                return

            environment = session.get(DemoEnvironment, environment_id)
            if environment is not None:
                provider_state = dict(environment.providerState or {})
                provider_state["currentOperation"] = {
                    "operationId": operation_id,
                    "phase": "failed",
                    "state": lifecycle_state.value,
                    "diagnostics": [str(error)],
                }
                environment.providerState = provider_state
                environment.lifecycleState = lifecycle_state
                environment.lastModifiedBy = actor_email
                session.add(environment)
            session.commit()

        if self._telemetry is not None:
            self._telemetry.emit(
                operation_id=operation_id,
                event_type=f"provider.{telemetry_phase}.failed",
                payload={"environmentId": environment_id, "state": lifecycle_state.value},
                environment_id=environment_id,
            )
