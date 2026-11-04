# Feature Specification: Azure LLM Serving Demo

**Feature Branch**: `001-llm-serving-demo`

**Created**: 2026-08-19

**Status**: Active implementation. 11 of 12 user stories are implemented (several with known,
explicitly noted gaps); User Story 11 (additional runtime/evaluation settings) is largely not yet
implemented. See each User Story's own **Status** note below for specifics.

**Input**: User description: "Create an Azure-hosted demonstration solution for presenters to
provision infrastructure, deploy one self-hosted LLM, tune its serving configuration, evaluate
quality and performance, redeploy it, and compare experiments. Start with single-server deployment
profiles for selected 3B, 7B, and 70B Hugging Face models while preserving extension paths for
additional inference engines, multi-server deployments, team usage, and other cloud platforms."

## Clarifications

### Session 2026-08-19

- Q: Should interactive prompt testing be blocked while a performance or quality run is active on the same deployment? → A: Yes — prompt testing and evaluation runs share the same conflict rule as other operations; block interactive prompt submission while a quality or performance run is active on that deployment, and vice versa.
- Q: Should failed deployments or provisioning attempts retry automatically, or always require an explicit manual restart? → A: Failures are terminal; the system does not auto-retry, and the user must explicitly trigger any retry.
- Q: What data retention or privacy handling should apply to prompts and generated responses submitted during a demo? → A: Automated golden dataset, benchmark, and performance test suite runs are persisted as part of experiment records. Ad hoc interactive prompt testing is purged at the end of each user session.
- Q: What observability signals must the operator UI expose beyond the performance metrics already required (FR-026/FR-057)? → A: The UI surfaces metrics only for v1 (no additional log/trace view); underlying per-operation event logs and trace-capable instrumentation are still captured and stored so richer observability views can be added later without re-instrumenting.
- Q: Should the model catalog pin an exact immutable checkpoint revision (e.g., a Hugging Face commit hash) rather than just a model name and tag? → A: No — catalog entries may reference a mutable tag; reproducibility across runs is best-effort, not guaranteed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Provision a Demo Environment (Priority: P1)

As a presenter, I can select a validated Azure deployment profile and provision a complete demo
environment so that I can host a selected model without manually assembling cloud resources.

**Why this priority**: Automated, repeatable infrastructure is required before any model can be
deployed or demonstrated.

**Independent Test**: Starting with an authorized organization user and an empty target
environment, a presenter can preview the selected profile, provision it, and see whether every
required resource became ready or failed.

**Acceptance Scenarios**:

1. **Given** an authorized presenter and valid Azure target, **When** the presenter selects a
   validated 3B, 7B, or 70B profile and confirms provisioning, **Then** the system creates the
   required environment and reports progress and final readiness.
2. **Given** missing permissions, unavailable capacity, quota limits, or invalid profile inputs,
   **When** provisioning runs, **Then** the system reports the blocking condition and does not
   present the environment as ready.
3. **Given** a previously provisioned environment, **When** the presenter inspects it, **Then** the
   system shows the selected profile, current resource state, deployment revision, and known cost
   and capacity context.
4. **Given** a selected model-size profile and accessible Azure subscriptions, **When** the
   presenter prepares provisioning, **Then** the system evaluates relevant GPU quota and capacity
   signals by eligible region, recommends an available region as the default, and explains any
   uncertainty in the recommendation.
5. **Given** a recommended default region, **When** the presenter selects another eligible region,
   **Then** the system revalidates quota, capacity, profile compatibility, and known limitations
   before provisioning.

**Status**: ✅ Implemented. Azure quota/capacity preflight (`backend/src/providers/azure/preflight.py`),
`previewEnvironment`/`provisionEnvironment`/`getEnvironmentState` (`backend/src/providers/azure/preview.py`,
`provision.py`, `state.py`), the GPU VM Terraform module sized per profile (`infra/azure/main.tf`),
and `GET /profiles`, `GET /catalog`, `POST /environments/preview`, `POST /environments`,
`GET /environments/{environmentId}` (`backend/src/api/routes/catalog.py`, `environments.py`) are all
in place, with the frontend provision flow and environment detail view
(`frontend/src/pages/Provision.tsx`, `EnvironmentDetail.tsx`). Covered by
`backend/tests/contract/test_environments_preview.py`, `test_environments_create.py`,
`backend/tests/integration/test_provision_flow.py`, and `e2e/tests/provision.spec.ts`.

---

### User Story 2 - Deploy and Exercise One Model (Priority: P2)

As a presenter, I can select an approved Hugging Face model checkpoint, configure its inference
behavior, deploy one model to the environment, and submit prompts so that I can demonstrate
self-hosted inference.

**Why this priority**: A working, reproducible model deployment is the core demonstration outcome.

**Independent Test**: A presenter can deploy one supported checkpoint with the initial inference
engine, observe its lifecycle, submit a prompt, and trace the response to the exact configuration
and deployment revision.

**Acceptance Scenarios**:

1. **Given** a ready environment and valid access to a selected checkpoint, **When** the presenter
   deploys a valid model and inference configuration, **Then** the system reports deployment
   progress and exposes the model only after it is ready.
2. **Given** a ready deployment, **When** an authenticated user submits a prompt, **Then** the system
   returns the generated response, timing summary, and deployment revision.
3. **Given** an invalid configuration, incompatible profile, unavailable checkpoint, or failed
   deployment, **When** deployment is attempted, **Then** the system reports actionable errors and
   does not label the model ready.
4. **Given** an existing deployment, **When** an authenticated presenter changes the model or
   inference configuration, **Then** the system records a new configuration revision and requires
   explicit redeployment before it becomes active.

**Status**: ✅ Implemented. vLLM engine adapter (`backend/src/engines/vllm/adapter.py`, `prompt.py`),
`ProviderAdapter.deployRevision` (`backend/src/providers/azure/deploy.py`), HF gated-checkpoint
credential handling that forwards but never persists the token (`backend/src/domain/hf_credentials.py`),
model/inference configuration versioning and deployment/prompt endpoints
(`backend/src/api/routes/configurations.py`, `deployments.py`, `prompts.py`), and the interactive-prompt
session-end purge job (`backend/src/domain/prompt_purge.py`) are all implemented, with the frontend
deploy/exercise pages (`frontend/src/pages/Deploy.tsx`, `Exercise.tsx`) and configuration version
history (`frontend/src/components/ConfigVersionHistory.tsx`). Covered by
`backend/tests/contract/test_deployments.py`, `test_prompts.py`,
`backend/tests/integration/test_deploy_exercise_flow.py`, and `e2e/tests/deploy-exercise.spec.ts`.

---

### User Story 3 - Evaluate Quality (Priority: P3)

As a presenter, I can run curated golden tests and selected short standard benchmarks against the
deployed model so that I can demonstrate whether serving changes preserve acceptable output
quality.

**Why this priority**: Optimization results are only meaningful when performance gains can be
assessed alongside model quality.

**Independent Test**: A presenter can run a versioned quality suite containing curated prompts,
deterministic checks, and two or three selected short benchmarks, then inspect complete and
incomplete outcomes.

**Acceptance Scenarios**:

1. **Given** a ready deployment and valid quality suite, **When** the presenter starts the suite,
   **Then** every case records its input reference, evaluation rule, observed outcome, status, and
   deployment revision.
2. **Given** a completed quality run, **When** a user opens the report, **Then** the system shows
   deterministic-check results, benchmark results, aggregate summaries, and failed cases.
3. **Given** a golden dataset generated with AI assistance, **When** it is registered for use,
   **Then** its origin, generation context, version, and review status are visible.
4. **Given** an interrupted run, **When** a user views the report, **Then** completed, failed,
   skipped, and unexecuted cases remain distinguishable.

**Status**: ✅ Implemented. Golden dataset registration with provenance/review-status
(`backend/src/evaluation/golden_dataset.py`), seeded GSM8K/IFEval/MMLU-mini benchmark definitions
(`backend/src/evaluation/seed_benchmarks.py`), `lm-evaluation-harness` integration against the deployed
vLLM endpoint (`backend/src/evaluation/lm_eval_runner.py`), quality-run orchestration with per-case
outcome recording (`backend/src/evaluation/run_quality.py`), and the run/report/cancel endpoints
(`backend/src/api/routes/runs.py`) are all in place, with the frontend quality-run and report pages
(`frontend/src/pages/QualityRun.tsx`, `QualityReport.tsx`) and provenance badge
(`frontend/src/components/ProvenanceBadge.tsx`). Covered by
`backend/tests/contract/test_quality_runs.py`, `backend/tests/integration/test_quality_flow.py`,
`backend/tests/unit/test_quality_run_states.py`, and `e2e/tests/quality.spec.ts`.

---

### User Story 4 - Measure Serving Performance (Priority: P4)

As a presenter, I can run a defined load profile and inspect model-serving metrics so that I can
demonstrate latency, throughput, reliability, and accelerator utilization.

**Why this priority**: Serving optimization requires repeatable measurements under explicit
conditions.

**Independent Test**: A presenter can execute one versioned workload and receive time-to-first-token,
inter-token latency, end-to-end latency, throughput, failure, and accelerator-utilization results.

**Acceptance Scenarios**:

1. **Given** a ready deployment and valid workload, **When** the presenter starts a performance run,
   **Then** the system records warm-up, input profile, concurrency, duration or request count, and
   completion criteria.
2. **Given** a completed run, **When** a user opens the report, **Then** all required metrics are
   shown with units, distribution summaries where applicable, and the exact test conditions.
3. **Given** overload, service failure, or incomplete monitoring data, **When** the run stops,
   **Then** the system preserves diagnostics, labels incomplete metrics, and does not present the
   run as successful.

**Status**: ✅ Implemented. Performance workload definitions (`backend/src/performance/workload.py`),
`LLMPerf` primary runner (`backend/src/performance/llmperf_runner.py`), vLLM benchmark CLI as a
secondary vLLM-authoritative runner (`backend/src/performance/vllm_bench_runner.py`), the vLLM engine
adapter's TTFT/inter-token/end-to-end/throughput/utilization capture
(`backend/src/engines/vllm/performance.py`), and orchestration that never reports an incomplete run
as successful (`backend/src/performance/run_performance.py`) are all in place, wired through
`backend/src/api/routes/runs.py`, with the frontend run-trigger and report pages
(`frontend/src/pages/PerformanceRun.tsx`, `PerformanceReport.tsx`). Covered by
`backend/tests/contract/test_performance_runs.py`, `backend/tests/integration/test_performance_flow.py`,
`backend/tests/unit/test_performance_incomplete.py`, and `e2e/tests/performance.spec.ts`.

---

### User Story 5 - Retune, Redeploy, and Compare (Priority: P5)

As a presenter, I can change inference settings, redeploy the model, rerun tests, and compare the
new revision with prior experiments so that an audience can understand optimization tradeoffs.

**Why this priority**: The complete learning experience depends on showing how a configuration
change affects quality, performance, and resource use.

**Independent Test**: A presenter can create a new configuration revision, redeploy it, repeat the
same tests, and compare both revisions side by side without losing the original records.

**Acceptance Scenarios**:

1. **Given** a completed experiment, **When** the presenter changes configuration and redeploys,
   **Then** the prior deployment and results remain immutable and linked to the original revision.
2. **Given** two results produced under equivalent conditions, **When** the presenter compares them,
   **Then** the system shows configuration, quality, performance, failure, and utilization
   differences side by side.
3. **Given** results with materially different conditions, **When** they are compared, **Then** the
   system identifies those differences and warns that the results are not directly comparable.

**Status**: ✅ Implemented. `POST /comparisons` and `GET /comparisons/{comparisonId}`
(`backend/src/api/routes/comparisons.py`) build configuration/quality/performance/failure/utilization
diffs across 2+ Result Reports (`backend/src/domain/comparison_builder.py`) and flag materially
different conditions - checkpoint, test definition, profile, region, or provider - as
not-directly-comparable (`backend/src/domain/comparability.py`, FR-059). Redeploying a revision
supersedes the prior one while keeping it and its results immutable and queryable
(`backend/src/domain/deployment_revision_repo.py`); a run-ID allocation bug that could let a rerun
after redeploy silently overwrite an earlier run's record was found and fixed while adding this
coverage. Frontend retune/redeploy flow (`frontend/src/pages/Retune.tsx`), side-by-side comparison
view (`frontend/src/pages/Compare.tsx`), and comparability-warning banner
(`frontend/src/components/ComparabilityWarning.tsx`) were already in place. Covered by
`backend/tests/contract/test_comparisons.py`, `backend/tests/unit/test_comparability.py`,
`backend/tests/unit/test_revision_immutability.py`, `backend/tests/integration/test_compare_flow.py`,
and `e2e/tests/compare.spec.ts`.

---

### User Story 6 - Tear Down Safely (Priority: P6)

As a presenter, I can preview and explicitly tear down the Azure resources after a demonstration
while preserving or exporting experiment records so that unnecessary resources do not continue
running.

**Why this priority**: Explicit cleanup limits avoidable cloud cost without sacrificing the learning
record.

**Independent Test**: A presenter can preview affected resources, confirm teardown, verify the
environment is removed, and still access or export retained experiment records.

**Acceptance Scenarios**:

1. **Given** an existing environment, **When** the presenter requests teardown, **Then** the system
   previews resources and consequences before requiring explicit confirmation.
2. **Given** confirmed teardown, **When** cleanup completes, **Then** the system reports every
   removed, retained, and failed resource action.
3. **Given** retained experiment history, **When** infrastructure is removed, **Then** records remain
   available in the selected preservation location or export.

**Status**: ✅ Implemented, with 2 known test gaps. Teardown preview/execute endpoints
(`POST /environments/{id}/teardown/preview`, `POST /environments/{id}/teardown`) live in
`backend/src/api/routes/environments.py`, backed by `teardownPreview`/`teardownEnvironment` on the
Azure adapter (`backend/src/providers/azure/adapter.py`); retained experiment records stay queryable
after teardown (`GET /environments/{id}/runs` has no lifecycle gate), and `ExperimentHistory.tsx`
implements client-side export (JSON download of an existing report) satisfying FR-061 without a
dedicated backend export endpoint. Frontend teardown flow lives in `frontend/src/pages/Teardown.tsx`.
Covered by `backend/tests/contract/test_environments_teardown.py` (preview success/404, teardown
202/409-locked). **Gaps**: no integration test exercising a full teardown-then-verify-retained-records
flow, and no Playwright e2e spec for teardown (`e2e/tests/teardown.spec.ts` does not exist).

---

### User Story 7 - Test and Demo Locally Without Cloud GPU (Priority: P7)

As a presenter, I can provision a local, non-Azure demo environment that serves a small Qwen model
through a locally installed inference runtime so that I can exercise deployment, prompting, quality
evaluation, and performance testing on my own machine while Azure GPU capacity is unavailable, being
requested, or simply not needed for a quick rehearsal.

**Why this priority**: Azure GPU quota approval can take days, and presenters and engineers need a
way to validate the end-to-end workflow, rehearse a demo, and catch integration regressions without
waiting on cloud capacity. This is a lower-priority convenience path layered on top of the core
Azure-hosted demonstration (User Stories 1-6) rather than a replacement for it.

**Independent Test**: A presenter with no Azure access and a supported local machine can provision a
local demo environment, deploy a small Qwen checkpoint through the locally installed inference
runtime, submit a prompt, run a quality suite, and run a performance workload, receiving the same
report shapes as the Azure path, clearly labeled as a local, non-Azure execution context.

**Acceptance Scenarios**:

1. **Given** a presenter's machine with the required local inference runtime installed (or the system
   guiding them to install it), **When** the presenter selects the local demo profile, **Then** the
   system provisions a local demo environment without requiring any Azure subscription, quota check,
   or region selection.
2. **Given** a ready local demo environment, **When** the presenter deploys a supported small Qwen
   checkpoint, **Then** the system ensures the checkpoint is available to the local runtime (pulling
   it if necessary), reports deployment progress, and exposes the model only once it responds to
   health checks.
3. **Given** a ready local deployment, **When** the presenter submits a prompt or starts a quality or
   performance run, **Then** the system produces the same report shapes as the Azure-hosted path,
   using the local inference runtime instead of Azure-hosted vLLM.
4. **Given** a completed local run and a completed Azure-hosted run, **When** the presenter compares
   them, **Then** the system labels the comparison as not directly comparable (per FR-059) because
   the infrastructure profile and accelerator context differ, while still showing the underlying
   metrics.
5. **Given** the local inference runtime is not installed, not running, or the requested checkpoint
   cannot be pulled, **When** the presenter attempts to provision or deploy, **Then** the system
   reports the specific blocking condition and remediation guidance rather than presenting the
   environment or deployment as ready.

**Status**: ✅ Implemented, with 1 known test gap. Local provider and Ollama engine adapters
(`backend/src/providers/local/adapter.py`, `backend/src/engines/ollama/adapter.py`), local-specific
error/remediation messaging (`backend/src/providers/local/errors.py`), and frontend local-profile
handling (`frontend/src/pages/Provision.tsx`'s `isLocalProfile()` branch,
`frontend/src/components/ComparabilityWarning.tsx`'s local not-directly-comparable messaging) are all
in place. Covered by `backend/tests/unit/test_local_provider.py`, `test_ollama_engine.py`,
`backend/tests/integration/test_local_demo_flow.py`, `test_local_comparability.py`, and
`test_local_provider_failures.py`. **Gap**: no Playwright e2e spec for the local/Ollama path
(`e2e/tests/local_demo.spec.ts` does not exist).

---

### User Story 8 - Navigate and Configure Without Memorizing IDs (Priority: P8)

As a presenter or engineer, I can pick environments, golden datasets, performance workloads, and
model/inference configurations from discoverable lists showing human-readable names and status,
instead of typing or pasting raw identifiers, and I experience the application through a visually
consistent, accessible Fluent 2 (Fluent UI v9) design so that the workflow feels professional,
trustworthy, and usable without out-of-band knowledge of internal IDs.

**Why this priority**: This is a usability and polish pass layered on top of the fully working core
workflow (User Stories 1-7). It does not unlock new capability, but it removes the single biggest
friction point observed in hands-on use (manual ID entry across Deploy, Exercise, Quality Run, and
Performance Run) and brings the UI to a consistent, accessible visual standard. It is intentionally
sequenced last so the underlying workflow is proven correct before investing in its presentation.

**Independent Test**: A user with no prior knowledge of any environment ID, dataset ID, workload ID,
or configuration version can complete the full Provision -> Deploy -> Exercise -> Quality/Performance
-> Compare -> Teardown workflow purely by selecting entries from lists/pickers, never typing a raw
identifier by hand, while every page renders using consistent Fluent 2 components, spacing, and
color/typography tokens (including keyboard and screen-reader accessible navigation).

**Acceptance Scenarios**:

1. **Given** one or more environments already exist, **When** a user opens Deploy, Exercise, Quality
   Run, or Performance Run, **Then** the system presents a searchable list of existing environments
   (name, state, region) to choose from, and selecting one loads its context automatically without a
   separate manual "load" step requiring a typed ID.
2. **Given** one or more registered golden datasets exist, **When** a user starts a quality run,
   **Then** the system presents a searchable list of datasets showing name, version, and provenance
   status, instead of a free-text dataset ID field.
3. **Given** one or more performance workload definitions exist, **When** a user starts a performance
   run, **Then** the system presents a searchable list of workloads showing name and description,
   instead of a free-text workload ID field.
4. **Given** existing model or inference configuration versions for an environment, **When** a user
   opens Deploy, **Then** the system presents a picker of existing configurations (version, key
   settings, created date) as a first-class alternative to creating a new one, without requiring the
   user to scroll to a separate history table to reuse a prior version.
5. **Given** the sidebar navigation, **When** a user is not currently working within a specific
   environment or run, **Then** the system does not present links that resolve to hardcoded or
   placeholder identifiers that are known in advance to 404 or error.
6. **Given** any page in the application, **When** rendered, **Then** all interactive controls (forms,
   buttons, tables, dropdowns, dialogs) use the Fluent 2 design system consistently, with a single
   visual hierarchy for primary vs. secondary actions, accessible labels (no duplicate/conflicting
   `aria-label` plus `<label>` pairs), and keyboard-navigable landmarks (including a correctly labeled
   navigation landmark and a skip-to-content link).

**Status**: 🟡 Partially implemented (4/6 scenarios pass). The Fluent UI v9 rebuild
(`@fluentui/react-components`) is in place app-wide (`frontend/src/App.tsx`), and the Environment
Picker (`frontend/src/components/EnvironmentPicker.tsx`, used by Deploy/Exercise/QualityRun/
PerformanceRun), Configuration Version Picker (`frontend/src/components/ConfigVersionHistory.tsx`),
and nav (no hardcoded/placeholder IDs in `App.tsx`'s route table) satisfy scenarios 1, 4, and 5.
**Gaps**: (a) golden dataset selection (`QualityRun.tsx`) and performance workload selection
(`PerformanceRun.tsx`) still use a free-text `Input` + HTML `<datalist>` instead of a proper searchable
Fluent picker component; (b) the nav landmark (`NavDrawer` in `App.tsx`) has no skip-to-content link
to the `<main>` region; (c) several fields (e.g. `Exercise.tsx`'s Prompt/Parameters JSON, `QualityRun.tsx`'s
Run type/Golden dataset, `Deploy.tsx`'s Catalog entry) set a redundant `aria-label` alongside their
Fluent `<Field label=...>`, creating duplicate/conflicting accessible names.

---

### User Story 9 - Diagnose and Recover from Failures Quickly (Priority: P9)

As a presenter or engineer running the demo, when an operation fails I can see enough detail — in
the operator UI, in the API response, and in the system's own logs — to understand what went wrong
and what to do next, instead of a generic "unexpected error" that requires someone to manually tail
server logs to find the real cause.

**Why this priority**: This is a hardening/refactoring pass layered on top of the working core
workflow (User Stories 1-8). Hands-on use has repeatedly surfaced failures (missing network
configuration, database schema mismatches, provider/API errors) where the operator UI and API
responses show only a generic message, forcing a manual, out-of-band log-tail session to find the
actual cause. It does not add new user-facing capability, so it is sequenced after the functional
stories, but it directly increases the demo's day-to-day operability and removes undocumented
tribal knowledge currently required to keep it running.

**Independent Test**: An operator with no prior access to server-side logs can, from the operator UI
alone (or a single retained diagnostics response), identify the specific failing component and
underlying cause for a provisioning error, a deployment error, and an unexpected server error, and
take a corrective action, without needing to SSH into a container or tail cloud logs.

**Acceptance Scenarios**:

1. **Given** any request that fails with an unhandled server error, **When** the error is returned to
   the caller, **Then** the response MUST include a stable error code, a human-readable summary, and
   a request/correlation ID that can be cross-referenced against the server's own structured logs.
2. **Given** any request that fails with an unhandled server error, **When** the backend logs the
   failure, **Then** the log entry MUST include the full exception type, message, and stack trace,
   plus the request path, method, and correlation ID, at a severity that is retained and searchable
   in the deployed environment's log destination.
3. **Given** a known, anticipated failure mode (for example, missing required configuration, a
   downstream dependency being unreachable, or a schema/data inconsistency), **When** it occurs,
   **Then** the system MUST return an actionable message that names the specific missing/invalid
   input or dependency, not just a generic failure code.
4. **Given** a long-running operation (provisioning, deployment, evaluation run, teardown) that fails
   partway through, **When** an operator inspects it, **Then** they MUST be able to see which step
   failed and the captured diagnostic detail for that step, consistent with the event log captured
   per FR-062.
5. **Given** the operator UI encounters a non-2xx API response, **When** it renders the error to the
   user, **Then** it MUST surface the backend's error code and message (not just a generic "Failed to
   fetch" or a blank/console-only error), so the failure is visible without opening browser developer
   tools.

**Status**: ✅ Implemented (4/5 scenarios pass, 1 minor gap). Structured error responses with
`requestId`/`code`/`message`/`details` (`backend/src/api/errors.py`, `backend/src/api/app.py`),
correlation-ID logging (`backend/src/api/correlation.py`), named actionable messages for known failure
modes (missing golden dataset/`runs.py`, missing HF token/`deployments.py`, unreachable Ollama/
`providers/local/errors.py`), and per-step diagnostics for long-running operations
(`backend/src/domain/workflow_reconciliation.py`, surfaced via `GET /environments/{id}`) are all in
place. The frontend `ApiError` client (`frontend/src/services/apiClient.ts`) and per-page error
handling (`Deploy.tsx`, `Provision.tsx`, `Exercise.tsx`) surface the backend's code/message instead of a
generic failure. **Gap**: the global unhandled-exception log line
(`backend/src/api/errors.py`, `LOGGER.exception("Unhandled request failure", ...)`) captures the
exception/traceback but omits request method, path, and request ID from that specific log entry,
making cross-referencing a returned `requestId` against server logs harder than intended.

---

### User Story 10 - Deploy Through the Baseline Azure Pilot Architecture (Priority: P0 - Foundational)

As a presenter or operator, I can deploy and operate the demo through a PaaS-hosted control plane
while GPU-serving resources remain isolated and disposable, so that development is fast, operations
remain understandable, and teardown removes expensive resources without losing experiment history.

**Why this priority**: This story defines the infrastructure and orchestration architecture that
every other user story runs on top of. It replaces the original single-resource-group,
App-Service-only topology (User Stories 1-9 remain functionally unchanged) with a three-resource-
group baseline — shared networking/platform services, a persistent application control plane, and a
disposable per-environment GPU resource group — coordinated through Azure Durable Functions and
executed through Azure Container Apps Jobs. It is marked foundational (P0) rather than sequenced
after P9 because it constrains how every other story's infrastructure and orchestration is built,
even though it introduces no new end-user-facing capability.

**Independent Test**: An operator can reach the deployed web application over Container Apps HTTPS
ingress with Entra ID SSO, provision and tear down a demo environment whose resources live only in
`rg-llm-demo-{environmentId}`, and confirm that the shared network/platform resources
(`rg-llm-shared-{stage}`) and the application control plane (`rg-llm-control-{stage}`, including
retained experiment records) remain intact and reachable after that teardown.

**Acceptance Scenarios**:

1. **Given** the deployed control plane, **When** an authenticated presenter opens the application
   URL, **Then** they reach the React/FastAPI application through Azure Container Apps' built-in
   HTTPS ingress and Microsoft Entra ID SSO, with no Application Gateway, Azure Front Door, or Azure
   Firewall in the request path.
2. **Given** a presenter starts a provisioning, deployment, evaluation, performance, export, or
   teardown action, **When** FastAPI receives the request, **Then** it atomically acquires the
   target environment's single-writer lock before starting an Azure Durable Functions workflow, and
   rejects the request immediately with an actionable HTTP 409 if the lock is already held.
3. **Given** a started workflow, **When** it needs to run Terraform, **Then** Azure Durable Functions
   dispatches the work to an Azure Container Apps Job rather than executing Terraform itself or
   inside the FastAPI process, and Durable Functions itself never exposes a web API or owns domain
   state.
4. **Given** a demo environment is provisioned, **When** Terraform applies infrastructure, **Then**
   shared/control-plane resources are created and updated only in `rg-llm-shared-{stage}` and
   `rg-llm-control-{stage}`, while environment-owned GPU resources are created only in
   `rg-llm-demo-{environmentId}`.
5. **Given** a deployed demo environment, **When** its network configuration is inspected, **Then**
   the GPU VM has no public IP and accepts inference traffic only from the Container Apps subnet or
   another explicitly authorized control-plane workload identity/source.
6. **Given** a deployment, evaluation, performance, cancellation, export, or teardown operation is
   running, **When** an operator inspects it, **Then** the system exposes current phase, elapsed
   time, and a terminal state (ready/failed/cancelled/torn down) consistent with FR-049/FR-055.
7. **Given** a demo environment ready for teardown, **When** teardown is confirmed, **Then** Terraform
   destroy removes only `rg-llm-demo-{environmentId}` and its environment-owned resources, and
   previously retained experiment records, reports, and control-plane services remain accessible.
8. **Given** a presenter supplies a Hugging Face credential for a gated checkpoint, **When** any
   provisioning, deployment, or evaluation operation runs, **Then** that credential is absent from
   Durable Functions workflow history/inputs, Terraform state and plan output, PostgreSQL, Blob
   Storage, Service Bus messages, application logs, traces, and experiment records — it exists only
   in the active deployment worker's process memory for the duration of that operation.
9. **Given** an interactive prompt is submitted, **When** telemetry and exception capture occur,
   **Then** the prompt and response bodies are absent from any persistent store or telemetry record,
   consistent with FR-060.
10. **Given** the local/Ollama execution path (User Story 7), **When** it is exercised against this
    architecture, **Then** it continues to satisfy the existing provider and engine contracts
    unchanged, since it does not provision any of the three Azure resource groups.

**Status**: ✅ Implemented. Three-resource-group Terraform baseline (`infra/shared/`, `infra/control/`,
`infra/demo/`) replaced the original single-VM/App-Service topology; Container Apps HTTPS
ingress + Entra ID SSO, Durable Functions orchestration dispatching to Container Apps Jobs, and the
single-writer lock/409 semantics are all in place per Phase 10 of `tasks.md` (T126-T145, all complete).
Historical implementation notes are not validation evidence for a new deployment.
The local/Ollama path (User Story 7) is unaffected since it provisions none of the three
Azure resource groups.

---

### User Story 11 - Configure Additional Runtime and Evaluation Settings (Priority: P11)

As a presenter or operator, I can adjust advanced serving and evaluation parameters (for example, the
model's maximum generation token budget, whether the chat template is applied for a given quality
benchmark, and reasoning/"thinking" trace handling) directly through deployment and benchmark
configuration rather than requiring a code change and application redeploy, so that the same
functional evaluation pipeline can be retuned quickly when a model family's defaults do not fit a
benchmark or workload out of the box.

**Why this priority**: Getting evaluations running correctly end-to-end (User Story 3) matters more
than getting the best possible score on any single benchmark. This story is explicitly lower priority
than functional correctness: it exists to remove the need for source changes when the *right* answer
is "use a different value for an existing parameter" (e.g., a larger generation token budget for a
reasoning model, or a different end-of-thinking marker), not to add new evaluation capabilities.

**Independent Test**: An operator can change a runtime/evaluation setting (e.g. maximum generation
tokens for a benchmark that uses chat-completions) through configuration, rerun the affected
benchmark or workload without any application code change or image rebuild, and see the new setting
take effect.

**Acceptance Scenarios**:

1. **Given** a quality benchmark whose default generation token budget is too small for a given
   model's reasoning/"thinking" output, **When** an operator raises that budget through
   configuration, **Then** the next run against that benchmark uses the new value without a backend
   code change or redeploy.
2. **Given** a benchmark or deployment configuration with no explicit override for a given setting,
   **When** a run executes, **Then** the system falls back to a documented default so existing
   behavior is unchanged for configurations that do not opt in.
3. **Given** an invalid or out-of-range value for an advanced setting, **When** an operator saves it,
   **Then** the system rejects the change with an actionable validation message instead of silently
   accepting a value that would fail at run time.

**Status**: 🔴 Largely not implemented (~20% complete). Only the read-path exists: `maxGenTokens` and
`useChatCompletions` are read from `BenchmarkDefinition.presentationSubset` with in-code defaults
(`backend/src/evaluation/lm_eval_runner.py`, defaulting to 2048/`False`), verified by
`backend/tests/unit/test_lm_eval_runner.py`. Everything else required by this story is missing:
(a) no API endpoint exists to create or update a benchmark definition's settings — only
`GET /benchmark-definitions` (`backend/src/api/routes/runs.py`); (b) no frontend UI lets an operator
view or change these settings; (c) `think_end_token` (the reasoning/"thinking" end marker) is hardcoded
to `"</think>"` in `lm_eval_runner.py` rather than configurable; (d) no validation exists anywhere for
these settings, so an invalid value (e.g. a negative or absurdly large `maxGenTokens`) would only fail
at run time, not be rejected at save time; (e) the documented-defaults requirement (FR-092) is not
met — `data-model.md` does not mention `maxGenTokens`/`useChatCompletions`/`think_end_token` at all.
An operator today can only change these settings by editing seed data / the database directly, which
does not satisfy this story's "without a code change" independent test. **Remaining work**: add a
benchmark-settings update endpoint with Pydantic validation (range-checked `maxGenTokens`, documented
defaults), make `think_end_token` configurable, add a frontend settings UI, and document defaults in
`data-model.md`.

---

### User Story 12 - Deploy Microsoft Phi Models (Priority: P12)

As a presenter, I can select a Microsoft Phi-family checkpoint (small, medium, and large slots,
alongside the existing Gemma, Llama, and Chinese-origin families) when deploying a model, so that the
demo can showcase Microsoft's own model family using the same provision/deploy/evaluate/compare flow
as every other supported family.

**Why this priority**: The core multi-family catalog and deployment pipeline (User Stories 1-5) must
exist first; adding another family is a catalog extension on top of already-working infrastructure,
not a new capability, so it is sequenced last.

**Independent Test**: A presenter can pick a Phi catalog entry for each of the small, medium, and
large profile slots, deploy it through the existing Deploy flow, and run the same prompt, quality, and
performance flows used for every other model family, with no Phi-specific code path required.

**Acceptance Scenarios**:

1. **Given** the model catalog, **When** a presenter opens the model picker for any deployment
   profile slot (3B/7B/70B), **Then** at least one ungated Microsoft Phi checkpoint is available and
   selectable alongside the existing Gemma, Llama, and Chinese-origin entries.
2. **Given** a selected Phi catalog entry, **When** the presenter deploys it, **Then** deployment,
   prompting, quality evaluation, and performance testing all succeed using the same engine adapter
   and report shapes as any other family, with no separate Phi-specific handling.
3. **Given** a Phi checkpoint assigned to the large (70B-class) profile slot, **When** the presenter
   inspects its catalog details, **Then** the UI clearly states the checkpoint's actual parameter
   count and that it stands in for the 70B slot, since Phi has no dense 70B-class checkpoint.

**Status**: ✅ Implemented. `ModelFamily.PHI` added to the domain enum; three ungated catalog entries
(`phi-3.5-mini-instruct`, `phi-4`, `phi-3.5-moe-instruct`) seeded across the 3B/7B/70B slots via the
existing `CATALOG_ENTRIES` shape (no Phi-specific fields or code path); Deploy's catalog-context panel
now surfaces the entry's descriptive notes, including the 70B-slot stand-in explanation for the MoE
checkpoint. Covered by `backend/tests/unit/test_seed_catalog_phi.py`.

---

### Edge Cases

- The selected Azure region lacks quota or capacity for the profile.
- A 70B profile cannot be fulfilled on available single-server hardware.
- Hugging Face credentials are absent, invalid, expired, or unauthorized for a gated checkpoint.
- A checkpoint revision is removed or changed upstream after a configuration was created.
- Model and inference settings exceed available accelerator memory or are mutually incompatible.
- Provisioning, model download, deployment, evaluation, or teardown is interrupted.
- Two browser sessions attempt to modify or redeploy the same environment concurrently.
- A user requests teardown while a deployment, evaluation, or redeployment is still active.
- A user cancels a run that already produced partial results, or cancels the same run twice in
  quick succession.
- A redeployment is requested while a previous redeployment for the same environment has not
  finished.
- A quality dataset has duplicate cases, missing provenance, or unreviewed AI-generated content.
- A workload would exceed configured safety limits for concurrency, duration, or request count.
- Monitoring data is partial or unavailable during a performance run.
- Results use different checkpoints, datasets, workloads, infrastructure, or environmental
  conditions.
- The local inference runtime required for User Story 7 is not installed, not running, or reachable
  only on a non-default port.
- The local machine lacks sufficient memory or disk space to pull or run the selected small Qwen
  checkpoint.
- A presenter attempts to run a full-scale performance workload against the local environment and
  expects results comparable to the Azure-hosted accelerator path.
- No environments, golden datasets, performance workloads, or configuration versions exist yet when a
  user opens a picker, and the empty list must not be mistaken for a loading or error state.
- The list of environments, datasets, workloads, or configuration versions is large enough that a
  user needs to search/filter rather than scroll a flat list.
- An unexpected server error occurs and the only detail available is a generic failure message, with
  no correlation ID or log detail to trace it back to a root cause.
- The database schema and the application's data model diverge (for example, after an incomplete or
  unapplied migration), producing errors that are opaque to both the operator and the presenter.
- The Container Apps Job or Durable Functions activity holding a Hugging Face credential in memory
  is lost (crash, eviction, restart) before completing its operation; the operation must fail
  terminally rather than retry with a re-derived or cached credential.
- A Container Apps Job reports progress or a terminal result to FastAPI after its parent workflow or
  environment lock has already been released or superseded (e.g., a very late callback after
  cancellation).
- Terraform state or plan output for a per-environment apply would otherwise capture a Hugging Face
  token passed as a variable; the design must prevent this rather than merely avoid printing it.
- A demo environment's teardown is requested while shared or control-plane resources it depends on
  (VNet, Postgres, Key Vault) are mid-update; teardown must still remove only the disposable
  resource group.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST require organization SSO authentication before exposing the demo.
- **FR-002**: Any user authenticated through organization SSO MUST be able to view deployments,
  prompts, experiment status, and reports.
- **FR-003**: For the first release, any user authenticated through organization SSO MAY perform
  provisioning, configuration changes, deployment actions, cancellation, and teardown; restricting
  these actions to a subset of authenticated users (role-based authorization) is deferred to a
  later release.
- **FR-004**: Every configuration-changing or destructive action MUST record the acting user's
  identity from the SSO session for audit purposes.
- **FR-005**: The system MUST provide validated Azure single-server profiles suitable for selected
  3B, 7B, and 70B model classes.
- **FR-006**: Each profile MUST expose its region, resource assumptions, capacity requirements,
  expected model class, configurable inputs, and known limitations before provisioning.
- **FR-007**: The system MUST preview, provision, inspect, update where supported, and report the
  state of the Azure demo environment through automated workflows.
- **FR-008**: Provisioning and teardown operations MUST expose progress, failure diagnostics, and
  final state without reporting partial success as complete.
- **FR-009**: The initial release MUST support one active model deployment per demo environment.
- **FR-010**: The system MUST provide a curated catalog of selected Hugging Face models and pinned
  checkpoints compatible with the validated profiles.
- **FR-011**: The system MUST accept presenter-supplied credentials for gated catalog entries
  without persisting or displaying those credentials in experiment records.
- **FR-012**: Model configurations MUST identify the catalog entry, exact checkpoint, model
  settings, access requirements, profile compatibility, and licensing notes. Checkpoint identity
  MAY reference a mutable Hugging Face tag rather than an immutable revision hash; reproducibility
  across runs is best-effort and the recorded checkpoint identifier is only guaranteed to be
  accurate as of the run's provisioning time.
- **FR-013**: Inference configurations MUST expose all presenter-controlled serving and generation
  settings, including visible defaults.
- **FR-014**: The inference layer MUST support a pluggable engine contract while the first release
  provides one engine implementation.
- **FR-015**: The initial engine implementation and single-server deployment MUST NOT prevent future
  engines or multi-server deployment profiles from being added without redefining experiment
  records.
- **FR-016**: The system MUST validate the combined infrastructure, model, checkpoint, and inference
  configuration before deployment.
- **FR-017**: Users MUST be able to inspect deployment lifecycle, readiness, errors, active revision,
  and available resource information.
- **FR-018**: Authenticated users MUST be able to submit prompts to a ready deployment and see the
  response, errors, timing summary, and active revision.
- **FR-019**: Every configuration change MUST create a revision, and activating that revision MUST
  require an explicit redeployment.
- **FR-020**: The system MUST preserve immutable snapshots of infrastructure profile, model,
  checkpoint, inference settings, test definition, and relevant environment context for every run.
- **FR-021**: The system MUST support versioned curated golden datasets with deterministic
  evaluation rules.
- **FR-022**: AI-generated golden data MUST retain generation provenance and review status.
- **FR-023**: The first release MUST support two or three selected standard quality benchmarks that
  can complete within a presentation-oriented runtime.
- **FR-024**: Quality reports MUST account for every declared case as passed, failed, errored,
  skipped, or incomplete and MUST provide aggregate summaries.
- **FR-025**: Performance workloads MUST define warm-up, input profile, concurrency, request count or
  duration, safety limits, and completion criteria.
- **FR-026**: Performance reports MUST include time to first token, inter-token latency,
  end-to-end latency, throughput, request failures, and available accelerator utilization.
- **FR-027**: Metric reports MUST include units, applicable distributions, test conditions, and
  completeness indicators.
- **FR-028**: Experiment runs MUST distinguish queued, running, completed, cancelled, failed, and
  incomplete states.
- **FR-029**: Operators MUST be able to cancel an active run without losing collected results and
  diagnostics.
- **FR-030**: The system MUST preserve configurations, deployment revisions, test definitions,
  results, and comparisons across redeployments.
- **FR-031**: Users MUST be able to compare compatible deployment revisions across configuration,
  quality, performance, failures, and accelerator utilization.
- **FR-032**: The system MUST detect materially different comparison conditions and display a
  comparability warning.
- **FR-033**: Teardown MUST require a resource preview and explicit operator confirmation.
- **FR-034**: Teardown MUST support preservation or export of experiment records and MUST report
  failed cleanup actions.
- **FR-035**: The web experience MUST guide the presenter through provisioning, deployment,
  inference, quality testing, performance testing, retuning, redeployment, comparison, and teardown.
- **FR-036**: The system MUST label the solution as a learning and demonstration environment rather
  than a production-ready serving platform.
- **FR-037**: Cloud provisioning, model deployment, and teardown logic MUST sit behind a single
  internal provider interface so that experiment, evaluation, and comparison concepts do not depend
  on Azure-specific APIs. Implementing an equivalent non-Azure provider is out of scope for this
  release.
- **FR-038**: Before provisioning, the system MUST evaluate the selected Azure subscription's
  relevant GPU quota and available capacity signals across eligible regions for the chosen profile.
- **FR-039**: The system MUST recommend the best eligible region with sufficient known quota and
  capacity as the default and MUST show the evidence, timestamp, and uncertainty behind that
  recommendation.
- **FR-040**: Presenters MUST be able to override the recommended region, but provisioning MUST
  revalidate quota, capacity, profile compatibility, and known regional limitations for the
  selected region.
- **FR-041**: Before selecting the initial inference engine, the project MUST research the most
  relevant current self-hosted LLM serving frameworks and compare their model support, accelerator
  support, single-server capabilities, performance features, operability, extensibility, licensing,
  project health, and Azure suitability.
- **FR-042**: The initial inference engine selection MUST document the evaluated alternatives,
  evidence, decision criteria, tradeoffs, and reasons for selection while retaining the pluggable
  engine requirement.
- **FR-043**: Before finalizing the initial model catalog, the project MUST research representative
  Gemma, Llama, and relevant Chinese-origin model families and checkpoints across the 3B, 7B, and
  70B classes.
- **FR-044**: Initial model selections MUST document checkpoint availability, license and access
  constraints, profile compatibility, expected demonstration value, language coverage, and known
  evaluation limitations.
- **FR-045**: Before selecting the initial two or three standard benchmarks, the project MUST
  research relevant quality benchmarks and compare their task coverage, model compatibility,
  licensing, reproducibility, runtime, result interpretability, contamination risk, and suitability
  for a live presentation.
- **FR-063**: Before selecting the tooling that executes golden dataset checks, standard benchmarks,
  and performance workloads, the project MUST research relevant LLM evaluation and test frameworks
  (for example, harnesses for deterministic quality checks, LLM-judged scoring, and load/performance
  testing) and compare their scoring methodology, benchmark and metric compatibility, deterministic
  vs. judged evaluation support, extensibility to custom golden datasets, performance/load testing
  capability, licensing, and operability within the web operator application.
- **FR-064**: The selected evaluation and test framework(s) MUST document the evaluated
  alternatives, evidence, decision criteria, and tradeoffs, and MUST be selected so that the
  pass/fail and percentile reporting requirements (FR-056, FR-057) are directly satisfiable without
  additional bespoke scoring infrastructure.
- **FR-046**: The Azure implementation MAY use managed platform services for application hosting,
  identity integration, monitoring, messaging, secrets, and persistent data when they reduce
  operational burden.
- **FR-047**: Configuration revisions, deployment history, test definitions, experiment results,
  and comparisons MUST be stored as versioned documents in a database technology that also runs on
  at least one other major cloud provider, without relying on Azure-only identifiers as primary
  keys.
- **FR-048**: The web operator application MUST be the primary control surface for environment
  preflight, provisioning, model deployment, configuration revision, prompt testing, evaluation,
  comparison, export, and teardown.
- **FR-049**: Long-running operations in the web application MUST expose current phase, elapsed
  time, progress when measurable, cancellation availability, actionable errors, and links to
  retained diagnostics.
- **FR-050**: After documented initial bootstrap and authentication prerequisites are satisfied, a
  presenter MUST be able to complete the full demonstration workflow without using a command-line
  or cloud-provider portal.
- **FR-051**: Azure infrastructure MUST be defined using tooling suited to Azure's native
  capabilities; standardizing on one cross-cloud infrastructure language is not required for this
  release. A future non-Azure provider selects its own native infrastructure tooling when it is
  built.
- **FR-052**: The system MUST enforce single-writer semantics per demo environment: only one
  provisioning, deployment, teardown, quality run, performance run, or interactive prompt
  submission MAY be active against a given deployment at a time, and a conflicting attempt MUST be
  rejected with an actionable message rather than silently queued, overwritten, or allowed to run
  concurrently and contaminate results.
- **FR-053**: The system MUST reject a teardown request while a deployment, evaluation, or
  redeployment operation is active for that environment, and MUST direct the user to cancel or wait
  for it to finish first.
- **FR-054**: Cancelling an active run MUST be idempotent: repeated cancellation requests for the
  same run MUST NOT alter already-recorded diagnostics or create duplicate cancellation records.
- **FR-055**: Every long-running operation (provisioning, deployment, evaluation run, teardown)
  MUST have a defined, finite set of allowed state transitions, and any action that would violate
  them MUST be rejected rather than silently accepted. Failure is a terminal state reached
  automatically only after any bounded internal error handling completes; the system MUST NOT
  auto-retry a failed operation, and the user MUST explicitly trigger any subsequent retry.
- **FR-056**: Each golden test case and benchmark result MUST be evaluated against a pass/fail or
  regression threshold documented in its test definition, rather than reporting only raw observed
  values.
- **FR-057**: Performance latency metrics MUST report at minimum a median (p50) and a tail
  percentile (p95 or higher) in addition to any other summary statistics.
- **FR-058**: The system MUST define and record a fixed reference execution profile (for example,
  cached model weights, a warm accelerator, and a specific concurrency/request-count workload) that
  the 60-minute end-to-end target is measured against.
- **FR-059**: A comparison MUST be labeled "not directly comparable" whenever checkpoint, dataset,
  workload, infrastructure profile, or region differ between two results, and MUST still display
  the underlying metrics.
- **FR-060**: Ad hoc interactive prompt submissions (FR-018) and their responses MUST be purged at
  the end of each user session or at demo environment teardown, whichever occurs first, and MUST
  NOT be retained as part of persisted experiment records.
- **FR-061**: Golden dataset test cases, benchmark runs, and performance workload runs, including
  their inputs and generated outputs, MUST be persisted as part of experiment records per FR-030
  and MUST be available for export before teardown.
- **FR-062**: The system MUST capture a per-operation, timestamped event log (and trace-capable
  instrumentation) for every provisioning, deployment, evaluation, and teardown operation. For the
  first release, the operator UI only needs to surface summary metrics and diagnostics (SC-007);
  the captured event log MUST be structured so a future release can expose it without
  re-instrumenting the system.
- **FR-065**: The system MUST support a local, non-Azure demo environment kind whose provisioning
  requires no Azure subscription, quota check, or region selection, satisfying the same provider
  interface (FR-037) as the Azure implementation.
- **FR-066**: The local demo environment MUST serve models through a locally installed inference
  runtime (Ollama) rather than the Azure-hosted vLLM engine, while exposing the same inference
  engine contract (FR-014).
- **FR-067**: The model catalog MUST include at least one small Qwen checkpoint marked compatible
  with the local demo profile, sized to run on commodity presenter hardware (CPU-only or a single
  consumer GPU).
- **FR-068**: Deploying to the local demo environment MUST ensure the selected checkpoint is present
  in the local inference runtime, pulling it automatically when it is absent, and MUST report
  pull/readiness progress and failures using the same deployment lifecycle model as the Azure path
  (FR-017).
- **FR-069**: When the local inference runtime is not installed, not reachable, or a checkpoint pull
  fails, the system MUST report the specific blocking condition and remediation guidance rather than
  marking the local environment or deployment ready.
- **FR-070**: Comparisons between a local-environment result and an Azure-environment result MUST be
  labeled "not directly comparable" per FR-059, since infrastructure profile and accelerator context
  always differ between the two.
- **FR-071**: The system MUST log every unhandled server error with the full exception type, message,
  and stack trace, plus the request path, method, and a correlation ID, at a severity that is
  retained and searchable in the deployed environment's log destination.
- **FR-072**: Every API error response — validation failures, known business-rule failures, and
  unhandled server errors alike — MUST include a stable error code, a human-readable message that
  names the specific failing input or dependency where known, and a request/correlation ID; unhandled
  errors MUST NOT expose internal stack traces to the caller but MUST allow correlation to the
  matching server-side log entry via that ID.
- **FR-073**: The operator web application MUST surface the backend's error code and message for any
  failed action directly in the UI, including for network/connectivity failures, rather than leaving
  the failure visible only in the browser console.
- **FR-074**: The Azure implementation MUST organize infrastructure into exactly three resource-group
  boundaries: a retained `rg-llm-shared-{stage}` for shared networking and platform services, a
  retained `rg-llm-control-{stage}` for the persistent application control plane, and a disposable
  `rg-llm-demo-{environmentId}` per demo environment containing only that environment's GPU
  resources (User Story 10).
- **FR-075**: The operator web application (React + FastAPI) MUST run on Azure Container Apps using
  its built-in HTTPS ingress and Microsoft Entra ID authentication; the system MUST NOT add an
  Application Gateway, Azure Front Door, Azure Firewall, Bastion host, or a public IP for the GPU VM
  unless an existing requirement in this specification proves one is necessary.
- **FR-076**: FastAPI MUST remain the system-of-record owner for authentication, authorization
  policy, request validation, API contracts, domain state transitions, audit records, PostgreSQL
  access, environment lock admission, and user-facing operation status; long-running-workflow
  coordination MUST NOT be moved into FastAPI itself.
- **FR-077**: Azure Durable Functions MUST coordinate only long-running workflows — provisioning,
  deployment, evaluation, performance testing, export, cancellation, and teardown — and MUST NOT
  expose a web API or own core domain logic.
- **FR-078**: Isolated Terraform, model deployment, quality-benchmark, performance-benchmark, and
  export workloads MUST execute in Azure Container Apps Jobs, not inside the FastAPI process or the
  Durable Functions host process.
- **FR-079**: Each Azure demo environment's GPU VM MUST have no public IP and MUST be reachable only
  from authorized control-plane workloads; the vLLM serving port MUST be allowed only from the
  required Container Apps subnet or explicitly identified workload identities/network sources.
- **FR-080**: Retained experiment records (per FR-030/FR-061) and control-plane services (Container
  Apps, Durable Functions, PostgreSQL, Storage, Key Vault, ACR, monitoring) MUST remain available and
  unaffected when any single demo environment's resource group is torn down.
- **FR-081**: The system MUST use managed identities for Azure resource access and MUST apply
  least-privilege Azure RBAC separately to the FastAPI app, Durable Functions, Terraform jobs,
  evaluation/performance jobs, and the GPU VM, rather than sharing one broad identity across all of
  them.
- **FR-082**: Presenter-supplied Hugging Face credentials MUST NOT be written to PostgreSQL, Blob
  Storage, Terraform state, Durable Functions inputs/history, Service Bus messages, application logs,
  traces, or API responses at any point; the credential MUST be passed directly to the active
  deployment worker and held only in that process's memory for the duration of the operation.
- **FR-083**: If the worker process holding a Hugging Face credential in memory is lost before
  completing its operation, the system MUST fail that operation terminally (no retry with a cached or
  re-derived credential) and require an explicit user retry that resupplies the credential.
- **FR-084**: The system MUST NOT durably store interactive prompt or response bodies (per FR-060),
  and telemetry/exception capture MUST NOT record those bodies even transiently in traces or error
  reports.
- **FR-085**: The system MUST encrypt data in transit and at rest using Azure-managed capabilities for
  every retained store (PostgreSQL, Storage, Key Vault secrets); customer-managed keys MAY be
  documented as an optional later enhancement but are not required for the pilot.
- **FR-086**: FastAPI, Durable Functions, Container Apps Jobs, and provisioning/deployment operations
  MUST propagate an OpenTelemetry-compatible correlation ID across every hop of a single logical
  operation, sent to Application Insights (telemetry) and Log Analytics (operational logs).
- **FR-087**: The system MUST raise alerts for failed workflows, unhealthy deployments, unavailable
  PostgreSQL, Container Apps Job failures, missing accelerator metrics, and configured budget
  thresholds.
- **FR-088**: Every Azure resource created by this architecture MUST be tagged consistently with
  ownership, stage, environment ID (where applicable), deployment revision (where applicable), cost
  center, and expiry/teardown metadata.
- **FR-089**: No component in this architecture (FastAPI, Durable Functions, or Container Apps Jobs)
  MAY automatically retry an operation after it reaches a terminal failure state; any retry MUST be an
  explicit new user action, consistent with FR-055.
- **FR-090**: Terraform for the three resource-group boundaries MUST be structured so that a
  per-environment (`rg-llm-demo-{environmentId}`) apply or destroy operation cannot create, modify, or
  delete resources in `rg-llm-shared-{stage}` or `rg-llm-control-{stage}`.
- **FR-091**: Deployment (inference configuration) and benchmark definitions MUST expose an
  extensible "additional settings" surface for advanced runtime/evaluation parameters (for example,
  maximum generation token budget, chat-template/completions mode, and reasoning-trace handling) that
  can be changed through configuration alone, without an application code change or redeploy.
- **FR-092**: Any advanced runtime/evaluation setting not explicitly overridden MUST fall back to a
  documented default, so existing configurations and results remain unaffected by the presence of the
  extensible settings surface.
- **FR-093**: The system MUST validate advanced runtime/evaluation setting values at the time they are
  saved and MUST reject invalid or out-of-range values with an actionable message rather than
  deferring failure to run time.
- **FR-094**: The model catalog MUST include at least one ungated Microsoft Phi checkpoint compatible
  with each of the small (3B), medium (7B), and large (70B) profile slots, using the same deployment,
  evaluation, and comparison paths as every other model family (no Phi-specific code path).

### Key Entities

- **Cloud Deployment Profile**: A validated, provider-specific description of infrastructure for a
  model class, including capacity assumptions, configurable inputs, and limitations. A local,
  non-Azure profile backed by a locally installed inference runtime is one supported provider kind
  (User Story 7).
- **Demo Environment**: A provisioned cloud environment with lifecycle, provider, region, profile,
  resource state, and deployment history.
- **Model Catalog Entry**: An approved model with Hugging Face identity, available checkpoints,
  access requirements, licensing notes, size class, and compatible profiles.
- **Model Configuration**: A versioned selection of model checkpoint and model-specific settings.
- **Inference Configuration**: A versioned set of serving and generation settings associated with an
  inference engine.
- **Deployment Revision**: An immutable record connecting an environment, model configuration,
  inference configuration, engine, lifecycle, and active period.
- **Golden Dataset**: A versioned curated prompt set with deterministic checks, provenance, and
  review status.
- **Benchmark Definition**: A selected, versioned standard quality benchmark and its presentation
  subset.
- **Performance Workload**: A versioned definition of inputs, warm-up, concurrency, duration or
  volume, safety limits, and completion criteria.
- **Experiment Run**: An execution record connecting a deployment revision, test definition,
  environment context, status, timing, diagnostics, and measurements.
- **Result Report**: Quality, latency, throughput, failure, and utilization outcomes with units and
  completeness.
- **Comparison**: A retained view of differences and comparability conditions across selected runs.
- **Orchestration Workflow**: A Durable Functions workflow instance coordinating one long-running
  operation (provisioning, deployment, evaluation, performance test, export, cancellation, or
  teardown) for a Demo Environment; carries a correlation ID shared with FastAPI, the dispatched
  Container Apps Job, and telemetry, and owns only phase/elapsed-time/cancellation/terminal-state
  tracking, never domain data (User Story 10, FR-077, FR-086).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A presenter can complete the functional workflow of provisioning, deploying one model,
  submitting a prompt, running quality and performance tests, retuning, redeploying, and comparing
  results without using tools outside the guided solution.
- **SC-002**: Under the documented reference execution profile (FR-058), the end-to-end workflow
  completes within 60 minutes; when it exceeds 60 minutes, each phase duration is visible so the
  limiting step can be investigated.
- **SC-003**: 100% of completed experiment reports identify the exact infrastructure profile, model
  checkpoint, inference configuration, engine, deployment revision, and test definition used.
- **SC-004**: 100% of quality cases are accounted for as passed, failed, errored, skipped, or
  incomplete.
- **SC-005**: 100% of completed performance reports include time to first token, inter-token
  latency (median and tail percentile per FR-057), end-to-end latency (median and tail percentile),
  throughput, failures, accelerator utilization when available, units, and workload conditions.
- **SC-006**: A presenter can identify configuration changes and principal quality and performance
  tradeoffs between two comparable revisions in under two minutes.
- **SC-007**: Every failed provisioning, deployment, evaluation, or teardown operation presents a
  visible failure state and at least one actionable diagnostic without exposing credentials.
- **SC-008**: Repeating an unchanged test against an unchanged deployment preserves all test
  conditions required to investigate variance.
- **SC-009**: A teardown preview accounts for every managed resource, and the final report records
  every resource as removed, retained, or failed.
- **SC-010**: Every provisioning attempt records a current regional quota and capacity preflight,
  and the default region is selected only from regions that pass all known profile checks.
- **SC-011**: The initial serving framework, model catalog, benchmark set, and evaluation/test
  framework each have a reviewable comparison that identifies evaluated alternatives, evidence,
  decision criteria, and explicit tradeoffs before implementation choices are finalized.
- **SC-012**: No two provisioning, deployment, teardown, quality-run, performance-run, or
  prompt-submission operations run concurrently against the same demo environment; conflicting
  attempts are rejected with an actionable message.
- **SC-013**: 100% of golden test cases and benchmark results are evaluated against a documented
  pass/fail or regression threshold rather than left as unjudged raw values.
- **SC-014**: After initial bootstrap, a presenter can complete 100% of the demonstration workflow
  through the web operator application, including recovery from a failed operation or access to its
  diagnostics.
- **SC-015**: A presenter with no Azure access can provision a local demo environment, deploy a small
  Qwen checkpoint, submit a prompt, and complete a quality and a performance run entirely on their
  own machine, with reports labeled as local/non-Azure and not directly comparable to Azure-hosted
  results.
- **SC-016**: 100% of unhandled server errors produce a correlation ID that a support engineer can use
  to locate a matching structured log entry containing the underlying exception, without needing
  direct database or code access to reproduce the failure.
- **SC-017**: 100% of demo-environment teardowns remove only that environment's disposable resource
  group; every retained control-plane resource and experiment record remains reachable immediately
  afterward.
- **SC-018**: No deployed demo environment ever exposes a public IP on its GPU VM, and no Application
  Gateway, Azure Front Door, or Azure Firewall resource exists in the deployed topology.
- **SC-019**: A search of PostgreSQL, Blob Storage, Terraform state/plan output, Durable Functions
  history, application logs, and traces for a presenter-supplied Hugging Face credential used in any
  completed operation returns zero matches.
- **SC-020**: Every long-running operation dispatched through Durable Functions carries a correlation
  ID traceable end-to-end across FastAPI, the Durable Functions workflow, and any Container Apps Job
  it triggered, in Application Insights/Log Analytics.

## Assumptions

- The first release is optimized for a presenter demonstrating to an audience; later use by a small
  FDE engineering team is anticipated but collaborative editing is not required initially.
- Azure is the first supported cloud, while the conceptual model must permit additional cloud
  providers later.
- Azure managed platform services are acceptable for the first release; a second cloud provider
  implementation is not built now but the provider interface (FR-037) keeps that path open.
- Azure infrastructure uses tooling suited to Azure's native capabilities; a future provider selects
  its own native infrastructure approach when it is built.
- The first release deploys one model on one server per demo environment; multi-model and
  multi-server operation are future extensions.
- The catalog contains a deliberately small, research-selected set of Hugging Face models and pinned
  checkpoints across the 3B, 7B, and 70B classes, with Gemma, Llama, Microsoft Phi, and relevant
  Chinese-origin model families included among the candidates. Checkpoint identity may be a mutable
  Hugging Face tag rather than an immutable revision hash, so exact reproducibility across runs is
  best-effort.
- Availability of the 70B profile depends on regional single-server accelerator capacity and quota.
- Azure capacity signals can be incomplete or change after preflight; recommendations communicate
  this uncertainty and provisioning remains the authoritative availability check.
- The local demo environment (User Story 7) is a convenience/testing path layered on the same
  provider and engine contracts as Azure; it is not a production alternative, is not expected to
  produce performance numbers comparable to Azure-hosted GPU serving, and depends on the presenter
  installing Ollama and having enough local memory/disk for the selected small Qwen checkpoint.
- The first release implements one research-selected inference engine behind a pluggable contract.
- Standard benchmark selection and runtime budgets will be finalized through comparative research
  during planning, and the first release includes two or three presentation-oriented benchmarks.
- The evaluation and test framework(s) used to execute golden dataset checks, benchmarks, and
  performance workloads will be selected through comparative research during planning, per FR-063
  and FR-064.
- The static operator password concept was removed after review: for this release, any user
  authenticated through organization SSO may perform all functionality, including provisioning,
  configuration changes, and teardown. Role-based restriction is deferred to a later release.
- Experiment records are retained independently from ephemeral serving resources and can be
  exported before teardown.
- The Azure implementation follows a PaaS-first baseline pilot architecture (User Story 10): Azure
  Container Apps for the web application, Azure Durable Functions for long-running-workflow
  coordination only, Azure Container Apps Jobs for isolated Terraform/deployment/evaluation/
  performance/export execution, and a private (no public IP) per-environment GPU VM, organized into
  exactly three resource-group boundaries (`rg-llm-shared-{stage}`, `rg-llm-control-{stage}`,
  `rg-llm-demo-{environmentId}`). This replaces the earlier single-VM-per-environment-plus-App-
  Service topology; no in-place migration path is assumed since the prior Azure environment was
  already torn down before this architecture was adopted.
- Key Vault holds application and platform secrets (including the PostgreSQL connection
  string/admin credentials) for the retained control plane, but is never used to retain
  presenter-supplied Hugging Face credentials beyond the active operation (FR-082/FR-083).
- Public internet access, production service guarantees, autoscaling, billing, multi-tenant
  isolation, and production support commitments are out of scope.
