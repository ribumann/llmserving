# Contracts: Cloud Provider Interface

**Input**: FR-037, FR-046, FR-051 in [spec.md](../spec.md)

Internal interface that all Azure-specific provisioning, deployment, and teardown logic sits
behind, so the domain, evaluation, and comparison layers never call Azure APIs directly. Two
implementations exist: `azure` (v1's primary path) and `local` (User Story 7's `LocalProviderAdapter`,
`backend/src/providers/local/adapter.py`, serving a small Qwen checkpoint through a locally installed
Ollama runtime with no Azure dependency). The interface exists so a provider can be added without
changing the domain model (FR-037). This is intentionally minimal — no
multi-provider export/import guarantee or adapter documentation mandate is implied (rubber-duck
review trim).

## Interface

```text
ProviderAdapter:
  previewEnvironment(profileId, regionOverride?) -> RegionRecommendation
    # Evaluates GPU quota/capacity signals across eligible regions (FR-038),
    # recommends a default with evidence + timestamp + uncertainty note (FR-039),
    # or revalidates a presenter-selected region override (FR-040).

  provisionEnvironment(profileId, region) -> ProvisioningHandle
    # Async; caller polls/subscribes for progress and terminal state (FR-007, FR-008).
    # MUST NOT report partial success as ready (FR-008).

  getEnvironmentState(environmentId) -> EnvironmentState
    # Resource state, active revision info, known cost/capacity context (FR-017).

  deployRevision(environmentId, modelConfig, inferenceConfig, engineId) -> DeploymentHandle
    # Validates combined infra + model + checkpoint + inference config before deploying (FR-016).

  teardownPreview(environmentId) -> TeardownPreview
    # Enumerates every managed resource and the consequence of removing it (FR-033).
    # MUST be rejected if an operation is currently active on the environment (FR-053).

  teardownEnvironment(environmentId, previewToken) -> TeardownHandle
    # Executes teardown; final report marks every resource removed, retained, or failed (FR-034).
```

## Contract Rules

- All handles/results surface progress, failure diagnostics, and terminal state distinctly; no
  operation may report success while resources remain in a non-terminal or partially-created
  state (FR-008, FR-055).
- The adapter never persists or displays HF gated-checkpoint credentials it forwards during
  deployment (FR-011); per User Story 10, the Azure implementation MUST NOT allow that credential to
  reach PostgreSQL, Terraform state/plan output, Durable Functions workflow inputs/history, or any
  log/trace — it is forwarded directly to the Container Apps Job process that performs the
  deployment and held only in that process's memory (FR-082/FR-083).
- Failures are terminal from the adapter's perspective; retry is always a new caller-initiated
  invocation, never internal auto-retry (FR-055, Clarification 2). A lost worker process holding a
  credential is a terminal failure requiring an explicit retry that resupplies the credential
  (FR-083).
- `previewEnvironment` and `teardownPreview` are read-only and do not acquire the environment's
  single-writer lock; every other method does, and MUST reject immediately with HTTP 409 if the lock
  is already held rather than queueing the request (FR-052, User Story 10 Acceptance Scenario 2).

## Azure Implementation Notes (non-normative)

- Provisioning/teardown execute Terraform (HCL, `azurerm` provider) per
  `Cloud Deployment Profile` definitions (FR-051, research.md Section 6). Terraform was chosen
  over Azure Bicep specifically because HCL is a cross-cloud IaC language, keeping the tooling
  reusable if a second cloud provider is added later, even though v1 implements Azure only.
- Quota/capacity evaluation uses Azure's usage/quota signals plus allocation-failure handling as
  detailed in `research.md` Section 4; recommendations explicitly carry uncertainty because Azure
  capacity signals can be stale or incomplete (spec Assumptions).
- Per User Story 10 (research.md Section 7), the Azure `ProviderAdapter` implementation does not
  execute Terraform or engine deployment itself. `provisionEnvironment`, `deployRevision`, and
  `teardownEnvironment` acquire the environment lock, then start an Azure Durable Functions workflow
  (an `Orchestration Workflow` record, see data-model.md) carrying a correlation ID; that workflow
  dispatches the actual Terraform apply/destroy or model-deployment work to an isolated Azure
  Container Apps Job (`terraform_runner` / `model_deployment`, FR-078). The job reports progress and
  the terminal result back to FastAPI through the internal callback API (contracts/api.md), which is
  what ultimately resolves the `ProvisioningHandle`/`DeploymentHandle`/`TeardownHandle` to a terminal
  state. Terraform for `provisionEnvironment`/`teardownEnvironment` targets only
  `rg-llm-demo-{environmentId}` (FR-074, FR-090); it never touches `rg-llm-shared-{stage}` or
  `rg-llm-control-{stage}`.

## Local Implementation Notes (non-normative, User Story 7)

- `LocalProviderAdapter` (`backend/src/providers/local/adapter.py`) never provisions any Azure
  resource group and skips quota/capacity evaluation entirely; `previewEnvironment` always
  recommends the `local-ollama` profile with no region/quota context (FR-065).
- `provisionEnvironment`/`getEnvironmentState` consider the environment `ready` once the locally
  installed Ollama endpoint responds to a health check; no Durable Functions workflow or Container
  Apps Job is involved, since this path runs entirely in-process (FR-067).
- `deployRevision` pulls the requested checkpoint into Ollama if it is not already present
  (`POST /api/pull`) before marking the revision ready (FR-068).
- `teardownPreview`/`teardownEnvironment` for the local provider are a no-op beyond releasing the
  local environment record — there is no cloud infrastructure to enumerate or destroy.
- Remediation-message mapping for "Ollama not installed/unreachable" and "checkpoint pull failed"
  lives in `backend/src/providers/local/errors.py` and is surfaced through the same
  failure-reporting model as the Azure provider (FR-069).
- Any result produced by a local-provider environment is unconditionally labeled
  `not-directly-comparable` when compared against another environment's results, since the
  infrastructure profile and accelerator context differ (FR-070, FR-059).
