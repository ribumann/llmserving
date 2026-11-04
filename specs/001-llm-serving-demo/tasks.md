---

description: "Task list for the Azure LLM Serving Demo feature"
---

# Tasks: Azure LLM Serving Demo

**Input**: Design documents from `/specs/001-llm-serving-demo/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

**Tests**: Included. `plan.md`'s own project structure defines `backend/tests/{contract,integration,unit}/` and picks pytest/Vitest/Playwright specifically to validate the interface contracts and quickstart scenarios, so contract/integration/e2e tests are treated as required deliverables, not optional extras.

**Organization**: Tasks are grouped by user story (P1-P6 from spec.md) to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1-US6)
- File paths are relative to the repository root, per `plan.md`'s Project Structure (`backend/`, `frontend/`, `infra/azure/`)

## Path Conventions

- **Backend**: `backend/src/`, `backend/tests/`
- **Frontend**: `frontend/src/`, `frontend/tests/`
- **Infra**: `infra/azure/` (Terraform, `azurerm` provider — research.md Section 6)
- **End-to-end**: `e2e/tests/` (Playwright, drives `quickstart.md` scenarios against a running backend+frontend)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure per `plan.md`'s Project Structure section.

- [x] T001 Create the `backend/`, `frontend/`, and `infra/azure/` directory skeleton per `plan.md` Project Structure
- [x] T002 Initialize the Python 3.11+ backend project (`backend/pyproject.toml` with FastAPI, uvicorn, SQLAlchemy, `psycopg`, `lm_eval[api]`, `llmperf` dependencies per research.md)
- [x] T003 [P] Initialize the TypeScript + React frontend project (`frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`)
- [x] T004 [P] Configure backend linting/formatting (`ruff`, `black`) in `backend/pyproject.toml`
- [x] T005 [P] Configure frontend linting/formatting (ESLint, Prettier) in `frontend/.eslintrc.cjs`, `frontend/.prettierrc`
- [x] T006 Initialize the Terraform project (`infra/azure/providers.tf`, `infra/azure/variables.tf`, `infra/azure/backend.tf` for remote state) using the `azurerm` provider per research.md Section 6
- [x] T007 [P] Configure `pytest` + `pytest-asyncio` (`backend/pytest.ini`, `backend/tests/conftest.py`) per research.md Section 5c
- [x] T008 [P] Configure Vitest + React Testing Library (`frontend/vitest.config.ts`, `frontend/tests/setup.ts`)
- [x] T009 [P] Configure Playwright (`e2e/playwright.config.ts`) targeting a local backend+frontend instance
- [x] T010 Set up environment configuration management (`backend/src/config.py`, `backend/.env.example`) covering PostgreSQL connection, Azure subscription/tenant, HF token passthrough, and vLLM/lm-eval/LLMPerf tool paths

**Checkpoint**: Tooling and project skeletons exist; no feature code yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure — persistence, auth, audit, single-writer lock, and the two internal adapter interfaces — that every user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Persistence

- [x] T011 Set up PostgreSQL connection/session management (`backend/src/persistence/db.py`) per research.md Section 5b
- [x] T012 Set up the Alembic migration framework (`backend/migrations/env.py`, `backend/alembic.ini`)
- [x] T013 [P] Create the `Cloud Deployment Profile` model + migration (`backend/src/domain/profile.py`) per data-model.md
- [x] T014 [P] Create the `Model Catalog Entry` model + migration (`backend/src/domain/catalog.py`) per data-model.md
- [x] T015 [P] Create the `Demo Environment` model + migration, including the `activeOperationId` single-writer lock field (`backend/src/domain/environment.py`) per data-model.md
- [x] T016 [P] Create the `Model Configuration` model + migration (`backend/src/domain/model_configuration.py`) per data-model.md
- [x] T017 [P] Create the `Inference Configuration` model + migration (`backend/src/domain/inference_configuration.py`) per data-model.md
- [x] T018 [P] Create the `Inference Engine` model + migration, seeded with the `vllm` engine record (`backend/src/domain/inference_engine.py`) per data-model.md and research.md Section 1
- [x] T019 [P] Create the `Deployment Revision` model + migration (`backend/src/domain/deployment_revision.py`) per data-model.md
- [x] T020 [P] Create the `Golden Dataset` model + migration (`backend/src/domain/golden_dataset.py`) per data-model.md
- [x] T021 [P] Create the `Benchmark Definition` model + migration (`backend/src/domain/benchmark_definition.py`) per data-model.md
- [x] T022 [P] Create the `Performance Workload` model + migration (`backend/src/domain/performance_workload.py`) per data-model.md
- [x] T023 [P] Create the `Experiment Run` model + migration, including the `retentionClass` (`persisted` \| `session-ephemeral`) field (`backend/src/domain/experiment_run.py`) per data-model.md and FR-060/FR-061
- [x] T024 [P] Create the `Result Report` model + migration (`backend/src/domain/result_report.py`) per data-model.md
- [x] T025 [P] Create the `Comparison` model + migration (`backend/src/domain/comparison.py`) per data-model.md

### Cross-Cutting Backend Concerns

- [x] T026 Implement organization SSO auth middleware (`backend/src/api/auth.py`) per FR-001
- [x] T027 Implement audit-trail capture recording the caller's SSO identity on every mutating endpoint (`backend/src/api/audit.py`) per FR-004
- [x] T028 Implement the single-writer lock acquire/release helper against `Demo Environment.activeOperationId`, covering provisioning, deployment, teardown, evaluation, performance, and interactive prompt submission (`backend/src/domain/environment_lock.py`) per FR-052/FR-053, Clarification 1
- [x] T029 Implement per-operation event-log/trace instrumentation capture, independent of what the v1 UI surfaces (`backend/src/api/telemetry.py`) per FR-062
- [x] T030 Implement the shared API error-shape middleware and `requestId` correlation (`backend/src/api/errors.py`) per contracts/api.md Error Shape

### Internal Adapter Interfaces

- [x] T031 [P] Define the `ProviderAdapter` interface (Python Protocol/ABC) with `previewEnvironment`, `provisionEnvironment`, `getEnvironmentState`, `deployRevision`, `teardownPreview`, `teardownEnvironment` (`backend/src/providers/base.py`) per contracts/provider-interface.md
- [x] T032 [P] Define the `InferenceEngineAdapter` interface (Python Protocol/ABC) with `describeSettings`, `deploy`, `getHealth`, `submitPrompt`, `runPerformanceWorkload`, `cancel` (`backend/src/engines/base.py`) per contracts/engine-interface.md
- [x] T033 [P] Contract test scaffolding validating any `ProviderAdapter` implementation against the interface contract rules (`backend/tests/contract/test_provider_interface.py`) per contracts/provider-interface.md
- [x] T034 [P] Contract test scaffolding validating any `InferenceEngineAdapter` implementation against the interface contract rules (`backend/tests/contract/test_engine_interface.py`) per contracts/engine-interface.md
- [x] T035 FastAPI application skeleton wiring routing, auth, audit, and error middleware together (`backend/src/api/app.py`)
- [x] T036 Seed the 9-checkpoint model catalog (Gemma/Llama/Qwen x small/medium/large) into `Model Catalog Entry` (`backend/src/persistence/seed_catalog.py`) per research.md Section 2

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Provision a Demo Environment (Priority: P1) 🎯 MVP

**Goal**: A presenter can select a validated Azure deployment profile, preview region/quota/capacity recommendations, provision a complete demo environment, and inspect its state.

**Independent Test**: Starting with an authorized organization user and an empty target environment, a presenter can preview the selected profile, provision it, and see whether every required resource became ready or failed (spec.md User Story 1 Independent Test).

### Tests for User Story 1

- [x] T037 [P] [US1] Contract test for `POST /environments/preview` (`backend/tests/contract/test_environments_preview.py`) per contracts/api.md
- [x] T038 [P] [US1] Contract test for `POST /environments` and `GET /environments/{environmentId}` (`backend/tests/contract/test_environments_create.py`) per contracts/api.md
- [x] T039 [P] [US1] Integration test for the full provision flow, including a region-override revalidation path (`backend/tests/integration/test_provision_flow.py`) per FR-038-040

### Implementation for User Story 1

- [x] T040 [US1] Implement the Azure provider's quota/capacity preflight sequence (usages API, resource-SKUs API) (`backend/src/providers/azure/preflight.py`) per research.md Section 4
- [x] T041 [US1] Implement `ProviderAdapter.previewEnvironment` for Azure, including region fallback ordering and uncertainty messaging (`backend/src/providers/azure/preview.py`) per research.md Section 4, FR-038/039
- [x] T042 [US1] Implement the Terraform GPU VM module (`infra/azure/main.tf`, `infra/azure/variables.tf`) targeting `Standard_NC16as_T4_v3` / `Standard_NC24ads_A100_v4` / `Standard_NC80adis_H100_v5` by size class per research.md Sections 4 and 6
- [x] T043 [US1] Implement `ProviderAdapter.provisionEnvironment` for Azure, orchestrating async Terraform apply with progress polling and `AllocationFailed` handling (`backend/src/providers/azure/provision.py`) per FR-007/008, research.md Section 4
- [x] T044 [US1] Implement `ProviderAdapter.getEnvironmentState` for Azure (`backend/src/providers/azure/state.py`) per FR-017
- [x] T045 [US1] Implement `GET /profiles` and `GET /catalog` endpoints (`backend/src/api/routes/catalog.py`) per FR-005/006/010
- [x] T046 [US1] Implement `POST /environments/preview` endpoint, read-only, no lock acquisition (`backend/src/api/routes/environments.py`) per FR-039, contracts/api.md
- [x] T047 [US1] Implement `POST /environments` endpoint with `202 Accepted` + polling semantics and region-override revalidation (`backend/src/api/routes/environments.py`) per FR-008/040
- [x] T048 [US1] Implement `GET /environments/{environmentId}` endpoint (`backend/src/api/routes/environments.py`) per FR-017
- [x] T049 [US1] Frontend: provision flow page (profile select -> preview -> confirm -> progress) (`frontend/src/pages/Provision.tsx`)
- [x] T050 [US1] Frontend: environment detail view (profile, resource state, deployment revision, capacity context) (`frontend/src/pages/EnvironmentDetail.tsx`)
- [x] T051 [US1] Frontend: API client for profile/catalog/environment endpoints (`frontend/src/services/environmentsApi.ts`)
- [x] T052 [US1] Playwright e2e test for quickstart.md Scenario 1 (`e2e/tests/provision.spec.ts`)

**Checkpoint**: User Story 1 is fully functional and independently testable — a presenter can provision an environment end-to-end.

---

## Phase 4: User Story 2 - Deploy and Exercise One Model (Priority: P2)

**Goal**: A presenter can select an approved checkpoint, configure inference behavior, deploy one model, and submit prompts against it.

**Independent Test**: A presenter can deploy one supported checkpoint with vLLM, observe its lifecycle, submit a prompt, and trace the response to the exact configuration and deployment revision (spec.md User Story 2 Independent Test).

### Tests for User Story 2

- [x] T053 [P] [US2] Contract test for model-configuration/inference-configuration/deployment endpoints (`backend/tests/contract/test_deployments.py`) per contracts/api.md
- [x] T054 [P] [US2] Contract test for `POST /environments/{environmentId}/prompts` (`backend/tests/contract/test_prompts.py`) per contracts/api.md, FR-060
- [x] T055 [P] [US2] Integration test for the deploy-then-prompt flow, including a config-change-requires-redeploy check (`backend/tests/integration/test_deploy_exercise_flow.py`) per FR-019

### Implementation for User Story 2

- [x] T056 [US2] Implement the vLLM engine adapter's `describeSettings`, `deploy`, and `getHealth` against the `vllm/vllm-openai` image (`backend/src/engines/vllm/adapter.py`) per contracts/engine-interface.md, research.md Section 1
- [x] T057 [US2] Implement the vLLM engine adapter's `submitPrompt`, returning response text and TTFT/inter-token timing inputs (`backend/src/engines/vllm/prompt.py`) per FR-018/026
- [x] T058 [US2] Implement `ProviderAdapter.deployRevision` for Azure, validating combined infra + model + checkpoint + inference config before invoking the vLLM adapter (`backend/src/providers/azure/deploy.py`) per FR-016
- [x] T059 [US2] Implement HF gated-checkpoint credential handling: accept, forward to deployment, never persist or display (`backend/src/domain/hf_credentials.py`) per FR-011
- [x] T060 [US2] Implement `POST /environments/{environmentId}/model-configurations` and `.../inference-configurations` endpoints, each creating a new version (`backend/src/api/routes/configurations.py`) per FR-012/013/019
- [x] T061 [US2] Implement `POST /environments/{environmentId}/deployments` and `GET .../deployments/{revisionId}` endpoints (`backend/src/api/routes/deployments.py`) per FR-016/017/019
- [x] T062 [US2] Implement `POST /environments/{environmentId}/prompts` endpoint enforcing the single-writer lock against active quality/performance runs (`backend/src/api/routes/prompts.py`) per Clarification 1, FR-052
- [x] T063 [US2] Implement the session-end purge job for interactive prompt records (`backend/src/domain/prompt_purge.py`) per FR-060
- [x] T064 [US2] Frontend: deploy/configure page (model + inference configuration, explicit deploy trigger) (`frontend/src/pages/Deploy.tsx`)
- [x] T065 [US2] Frontend: exercise/prompt console page showing response, timing, and revision (`frontend/src/pages/Exercise.tsx`)
- [x] T066 [US2] Frontend: configuration version history component (`frontend/src/components/ConfigVersionHistory.tsx`)
- [x] T067 [US2] Playwright e2e test for quickstart.md Scenario 2 (`e2e/tests/deploy-exercise.spec.ts`)

**Checkpoint**: User Stories 1 AND 2 both work independently — a presenter can provision, deploy, and exercise a model end-to-end.

---

## Phase 5: User Story 3 - Evaluate Quality (Priority: P3)

**Goal**: A presenter can run curated golden tests and standard benchmarks against the deployed model and inspect complete/incomplete outcomes.

**Independent Test**: A presenter can run a versioned quality suite (curated prompts, deterministic checks, GSM8K/IFEval/MMLU-mini) and inspect complete and incomplete outcomes (spec.md User Story 3 Independent Test).

### Tests for User Story 3

- [x] T068 [P] [US3] Contract test for `POST/GET /runs` (quality types) and `/runs/{runId}/report` (`backend/tests/contract/test_quality_runs.py`) per contracts/api.md
- [x] T069 [P] [US3] Integration test for a combined golden-dataset + standard-benchmark run (`backend/tests/integration/test_quality_flow.py`) per FR-021-024

### Implementation for User Story 3

- [x] T070 [US3] Implement golden dataset registration with provenance (`curated`\|`ai-generated`) and review-status validation (`backend/src/evaluation/golden_dataset.py`) per FR-021/022, spec.md Edge Case ("unreviewed AI-generated content")
- [x] T071 [US3] Seed the `Benchmark Definition` records for GSM8K, IFEval, and MMLU 5-subject mini with their presentation subsets and pass/fail thresholds (`backend/src/evaluation/seed_benchmarks.py`) per research.md Section 3, FR-056
- [x] T072 [US3] Integrate `lm-evaluation-harness` via its `local-completions` backend against the deployed vLLM endpoint (`backend/src/evaluation/lm_eval_runner.py`) per research.md Section 3
- [x] T073 [US3] Implement quality-run orchestration: single-writer lock, per-case outcome recording (passed/failed/errored/skipped/incomplete) (`backend/src/evaluation/run_quality.py`) per FR-024/056, Clarification 1
- [x] T074 [US3] Implement `POST /environments/{environmentId}/runs` for `quality-golden` and `quality-benchmark` run types (`backend/src/api/routes/runs.py`) per FR-021/023
- [x] T075 [US3] Implement `GET /runs/{runId}` (status/diagnostics/partial results) and `GET /runs/{runId}/report` (`backend/src/api/routes/runs.py`) per FR-028/029/024
- [x] T076 [US3] Implement `POST /runs/{runId}/cancel` as an idempotent operation (`backend/src/api/routes/runs.py`) per FR-054
- [x] T077 [US3] Implement `Result Report` persistence with `retentionClass=persisted` for automated suite runs (`backend/src/domain/result_report_repo.py`) per FR-061
- [x] T078 [US3] Frontend: quality run trigger + progress page (`frontend/src/pages/QualityRun.tsx`)
- [x] T079 [US3] Frontend: quality report view (deterministic-check results, benchmark results, aggregate summary, failed cases) (`frontend/src/pages/QualityReport.tsx`)
- [x] T080 [US3] Frontend: golden-dataset provenance/review-status badge component (`frontend/src/components/ProvenanceBadge.tsx`)
- [x] T081 [US3] Unit test: interrupted run keeps completed/failed/skipped/unexecuted cases distinguishable (`backend/tests/unit/test_quality_run_states.py`) per spec.md Acceptance Scenario US3.4
- [x] T082 [US3] Playwright e2e test for quickstart.md Scenario 3 (`e2e/tests/quality.spec.ts`)

**Checkpoint**: User Stories 1-3 work independently — quality evaluation is demonstrable end-to-end.

---

## Phase 6: User Story 4 - Measure Serving Performance (Priority: P4)

**Goal**: A presenter can run a defined load profile and inspect latency, throughput, reliability, and accelerator-utilization metrics.

**Independent Test**: A presenter can execute one versioned workload and receive TTFT, inter-token latency, end-to-end latency, throughput, failure, and accelerator-utilization results (spec.md User Story 4 Independent Test).

### Tests for User Story 4

- [x] T083 [P] [US4] Contract test for performance-type `POST/GET /runs` and report retrieval (`backend/tests/contract/test_performance_runs.py`) per contracts/api.md
- [x] T084 [P] [US4] Integration test for a full performance-workload run (`backend/tests/integration/test_performance_flow.py`) per FR-025-027

### Implementation for User Story 4

- [x] T085 [US4] Implement `Performance Workload` definition creation (warm-up, input profile, concurrency, duration/request count, completion criteria) (`backend/src/performance/workload.py`) per FR-025
- [x] T086 [US4] Integrate `LLMPerf` as the primary performance runner against the vLLM OpenAI-compatible endpoint (`backend/src/performance/llmperf_runner.py`) per research.md Section 3
- [x] T087 [US4] Integrate the vLLM benchmark CLI (`vllm bench serve`) as a secondary, vLLM-authoritative runner (`backend/src/performance/vllm_bench_runner.py`) per research.md Section 3
- [x] T088 [US4] Implement the vLLM engine adapter's `runPerformanceWorkload`, streaming/accumulating TTFT, inter-token latency, end-to-end latency, throughput, and accelerator utilization with p50/p95 support (`backend/src/engines/vllm/performance.py`) per FR-025-027/057
- [x] T089 [US4] Implement performance-run orchestration with overload/service-failure/partial-monitoring handling — never presented as successful when incomplete (`backend/src/performance/run_performance.py`) per FR-027/029, spec.md Acceptance Scenario US4.3
- [x] T090 [US4] Wire `POST /environments/{environmentId}/runs` (type=`performance`) and report retrieval to the performance orchestration (`backend/src/api/routes/runs.py`) per FR-025
- [x] T091 [US4] Frontend: performance run trigger page (workload parameters) (`frontend/src/pages/PerformanceRun.tsx`)
- [x] T092 [US4] Frontend: performance report view (TTFT/ITL/E2E/throughput with units and distribution summaries, exact test conditions) (`frontend/src/pages/PerformanceReport.tsx`)
- [x] T093 [US4] Unit test: overload/incomplete-monitoring-data runs are labeled incomplete, never successful (`backend/tests/unit/test_performance_incomplete.py`) per spec.md Acceptance Scenario US4.3
- [x] T094 [US4] Playwright e2e test for quickstart.md Scenario 4 (`e2e/tests/performance.spec.ts`)

**Checkpoint**: User Stories 1-4 work independently — the full evidence-driven optimization loop (deploy, evaluate quality, measure performance) is demonstrable.

---

## Phase 7: User Story 5 - Retune, Redeploy, and Compare (Priority: P5)

**Goal**: A presenter can change inference settings, redeploy, rerun tests, and compare the new revision with prior experiments.

**Independent Test**: A presenter can create a new configuration revision, redeploy it, repeat the same tests, and compare both revisions side by side without losing the original records (spec.md User Story 5 Independent Test).

### Tests for User Story 5

- [x] T095 [P] [US5] Contract test for `POST /comparisons` and `GET /comparisons/{comparisonId}` (`backend/tests/contract/test_comparisons.py`) per contracts/api.md
- [x] T096 [P] [US5] Integration test for retune -> redeploy -> rerun -> compare, asserting the original revision/results remain immutable (`backend/tests/integration/test_compare_flow.py`) per FR-019/020

### Implementation for User Story 5

- [x] T097 [US5] Implement deployment-revision immutability and supersede-linking on redeploy (`backend/src/domain/deployment_revision_repo.py`) per FR-019/020
- [x] T098 [US5] Implement the comparison builder (config, quality, performance, failure, and utilization diffs across 2+ `Result Report`s) (`backend/src/domain/comparison_builder.py`) per FR-031/032
- [x] T099 [US5] Implement the comparability-condition check that flags and warns when compared results were produced under materially different conditions (`backend/src/domain/comparability.py`) per FR-059
- [x] T100 [US5] Implement `POST /comparisons` and `GET /comparisons/{comparisonId}` endpoints (`backend/src/api/routes/comparisons.py`) per contracts/api.md
- [x] T101 [US5] Frontend: retune flow (new configuration version -> redeploy), reusing the Deploy page components (`frontend/src/pages/Retune.tsx`)
- [x] T102 [US5] Frontend: side-by-side comparison view (`frontend/src/pages/Compare.tsx`)
- [x] T103 [US5] Frontend: comparability-warning banner component (`frontend/src/components/ComparabilityWarning.tsx`)
- [x] T104 [US5] Unit test: prior revisions and results remain immutable and linked after redeploy (`backend/tests/unit/test_revision_immutability.py`) per spec.md Acceptance Scenario US5.1
- [x] T105 [US5] Unit test: comparison of materially different conditions is flagged and warned (`backend/tests/unit/test_comparability.py`) per spec.md Acceptance Scenario US5.3
- [x] T106 [US5] Playwright e2e test for quickstart.md Scenario 5 (`e2e/tests/compare.spec.ts`)

**Checkpoint**: User Stories 1-5 work independently — the complete optimization/learning narrative (retune, redeploy, compare) is demonstrable.

---

## Phase 8: User Story 6 - Tear Down Safely (Priority: P6)

**Goal**: A presenter can preview and explicitly tear down Azure resources while preserving or exporting experiment records.

**Independent Test**: A presenter can preview affected resources, confirm teardown, verify the environment is removed, and still access or export retained experiment records (spec.md User Story 6 Independent Test).

### Tests for User Story 6

- [x] T107 [P] [US6] Contract test for teardown preview/execute endpoints (implemented as `backend/tests/contract/test_environments_teardown.py`, not `test_teardown.py` as originally named — covers preview success/404 and teardown 202/409-locked) per contracts/api.md
- [ ] T108 [P] [US6] Integration test for full teardown with retained/exportable experiment records (`backend/tests/integration/test_teardown_flow.py`) per FR-033/034/061 — **gap**: does not exist under any name; no integration test currently exercises a full teardown-then-verify-retained-records flow end to end

### Implementation for User Story 6

- [x] T109 [US6] Implement `ProviderAdapter.teardownPreview` for Azure: resource enumeration + consequences, rejected while an operation is active (implemented inline in `backend/src/providers/azure/adapter.py`, not a separate `teardown_preview.py` file) per FR-033/053
- [x] T110 [US6] Implement `ProviderAdapter.teardownEnvironment` for Azure via Terraform destroy, reporting each resource as removed/retained/failed (implemented inline in `backend/src/providers/azure/adapter.py`, not a separate `teardown.py` file) per FR-034
- [x] T111 [US6] Implement `POST /environments/{environmentId}/teardown/preview` and `POST .../teardown` endpoints, requiring a prior preview token (`backend/src/api/routes/environments.py`) per contracts/api.md
- [x] T112 [US6] Implement experiment-record retention/export after teardown, independent of infrastructure lifecycle — implemented as client-side export in `frontend/src/pages/ExperimentHistory.tsx` (fetches an existing report via `getPerformanceRunReport`/`getQualityRunReport` and downloads it) plus a lifecycle-agnostic `GET /environments/{environmentId}/runs` (`backend/src/api/routes/runs.py`), rather than a dedicated `backend/src/domain/experiment_export.py` backend export module, per FR-061
- [x] T113 [US6] Frontend: teardown preview + explicit confirmation flow page (`frontend/src/pages/Teardown.tsx`)
- [x] T114 [US6] Frontend: teardown report view (removed/retained/failed per resource) — implemented inline within `frontend/src/pages/Teardown.tsx` (resource outcome table), not a separate `TeardownReport.tsx` component
- [x] T115 [US6] Frontend: post-teardown experiment history/export view (`frontend/src/pages/ExperimentHistory.tsx`)
- [x] T116 [US6] Unit test: teardown request rejected while an operation is active on the environment — covered by the 409-locked case in `backend/tests/contract/test_environments_teardown.py`, not a separate `test_teardown_lock.py` unit test, per FR-053
- [ ] T117 [US6] Playwright e2e test for quickstart.md Scenario 6 (`e2e/tests/teardown.spec.ts`) — **gap**: does not exist; `e2e/tests/` has no teardown spec

**Checkpoint**: All six user stories are independently functional — the full demo lifecycle (provision through teardown) is demonstrable end-to-end.

---

## Phase 9: User Story 7 - Test and Demo Locally Without Cloud GPU (Priority: P7)

**Goal**: A presenter with no Azure access can provision a local demo environment, deploy a small Qwen checkpoint via a locally installed inference runtime (Ollama), and run the same prompt/quality/performance flows as the Azure path.

**Independent Test**: A presenter can provision a local environment without Azure credentials or quota, deploy a small Qwen checkpoint (pulling it if absent), submit a prompt, run a quality check, and run a performance workload, all producing the same report shapes as the Azure path but labeled as local/non-comparable (spec.md User Story 7 Independent Test).

### Tests for User Story 7

- [x] T126 [P] [US7] Contract test for the local `ProviderAdapter` implementation against the shared provider contract suite (`backend/tests/contract/test_local_provider.py`) per FR-065/037
- [x] T127 [P] [US7] Contract test for the Ollama `InferenceEngineAdapter` implementation against the shared engine contract suite (`backend/tests/contract/test_ollama_engine.py`) per FR-066/014
- [x] T128 [P] [US7] Integration test for local provision -> deploy (with checkpoint pull) -> prompt -> quality run -> performance run (`backend/tests/integration/test_local_demo_flow.py`) per FR-067/068

### Implementation for User Story 7

- [x] T129 [US7] Add `ProviderType.LOCAL = "local"` to the provider enum (`backend/src/domain/enums.py`) per FR-065
- [x] T130 [US7] Implement `LocalProviderAdapter` (`backend/src/providers/local/adapter.py`): `preview_with_details` always recommends the local profile with no quota check, `start_provisioning`/`getEnvironmentState` mark the environment ready once the Ollama endpoint responds, matching the method names actually called by `backend/src/api/routes/environments.py` per FR-065
- [x] T131 [US7] Implement `start_deployment` on `LocalProviderAdapter`: pulls the checkpoint in Ollama if absent (via `POST /api/pull`), reports progress/failure through the existing deployment lifecycle states, and marks the revision ready once the model is present (`backend/src/providers/local/adapter.py`) per FR-068/069
- [x] T132 [US7] Implement `OllamaEngineAdapter` (`backend/src/engines/ollama/adapter.py`) implementing the engine adapter's health/prompt/quality/performance methods against Ollama's OpenAI-compatible endpoints (`/v1/chat/completions`), reporting accelerator utilization as unavailable per FR-066/026
- [x] T133 [US7] Add a `local-ollama` `Cloud Deployment Profile` (no `eligibleRegions`/`vmSku`, commodity-hardware `capacityAssumptions`) and mark at least one small Qwen `Model Catalog Entry` (e.g. `qwen2.5-0.5b-instruct` or `qwen3-4b`) compatible with it (`backend/src/domain/seed_data.py` or equivalent) per FR-067
- [x] T134 [US7] Implement remediation-message mapping for "Ollama not installed/reachable" and "checkpoint pull failed" conditions, surfaced through the standard failure-reporting model (`backend/src/providers/local/errors.py`) per FR-069
- [x] T135 [US7] Frontend: allow selecting "Local (Ollama)" as a provider option in the environment creation flow, reusing existing Provision/Deploy pages (`frontend/src/pages/Provision.tsx`, `frontend/src/pages/Deploy.tsx`)
- [x] T136 [US7] Frontend: local/non-comparable labeling on result reports and comparisons produced from a local environment (`frontend/src/components/ComparabilityWarning.tsx`) per FR-070
- [x] T137 [US7] Unit test: comparisons involving a local-environment result are always labeled "not directly comparable" (`backend/tests/unit/test_local_comparability.py`) per FR-070/059
- [x] T138 [US7] Unit test: deployment fails with remediation guidance when Ollama is unreachable or the checkpoint pull fails, without marking the environment/deployment ready (`backend/tests/unit/test_local_provider_failures.py`) per spec.md Acceptance Scenario US7.5
- [ ] T139 [US7] Playwright e2e test for quickstart.md Scenario 7 (local provision -> deploy -> prompt -> quality -> performance) (`e2e/tests/local_demo.spec.ts`) — **gap**: does not exist; `e2e/tests/` has no local-demo spec
- [x] T140 [P] [US7] Document local setup (installing Ollama, pulling a Qwen checkpoint, running the app fully locally) in `README.md`/`quickstart.md`

**Checkpoint**: A presenter can run the full demo narrative on their own machine with no Azure dependency, in addition to all six Azure-backed user stories.

---

## Phase 10: User Story 10 - Deploy Through the Baseline Azure Pilot Architecture (Priority: P0 - Foundational)

**Goal**: Replace the single-VM-plus-App-Service Azure topology with the three-resource-group
baseline pilot architecture (Container Apps, Durable Functions, Container Apps Jobs, private GPU
VM) described in `plan.md` Target Platform and `research.md` Section 7, without changing the
functional behavior of User Stories 1-9.

**Independent Test**: See spec.md User Story 10 Independent Test and `quickstart.md` Scenario 8.

**⚠️ Ordering note**: Although foundational in scope, this phase is sequenced after Stories 1-9
because it refactors already-working infrastructure/orchestration rather than introducing new
domain capability; execute it before any further Azure deployment work.

### Infrastructure (Terraform)

- [x] T126 [P] Write the migration/replacement plan documenting why in-place migration from
  `infra/azure`+`infra/database`+`infra/app-host` is not attempted (topology change) and that this
  is a safe full replacement (prior Azure environment already torn down) (`infra/README.md` or
  `docs/infra-migration.md`)
- [x] T127 Create `infra/shared/` Terraform module: VNet + 4 subnets, private DNS zones/links, NSGs,
  NAT Gateway, ACR, Key Vault, Log Analytics + Application Insights (FR-074, research.md Section 7)
- [x] T128 Create `infra/control/` Terraform module: Container Apps environment + Container App
  (React+FastAPI, HTTPS ingress, Entra ID auth), Container Apps Job definitions (terraform runner,
  model deployment, evaluation, performance, export), Durable Functions app + hosting plan,
  PostgreSQL Flexible Server (private access), Storage accounts/containers (Functions state, TF
  state, artifacts/exports), managed identities, least-privilege RBAC, diagnostics, alerts
  (FR-074/FR-081/FR-087)
- [x] T129 Replace `infra/azure/` with `infra/demo/`: private GPU VM + NIC on `snet-gpu` (no public
  IP, no Bastion), OS/model-cache disks, NVIDIA driver extension, environment monitoring config
  (FR-079, FR-090)
- [x] T130 [P] Ensure `infra/demo/` Terraform cannot reference/modify `rg-llm-shared-{stage}` or
  `rg-llm-control-{stage}` resources beyond read-only data sources (FR-090)
- [x] T131 [P] Verify Terraform variables/outputs never pass or surface a Hugging Face credential
  (FR-082); add a repository check/test asserting no `huggingface_token`-shaped variable exists in
  `infra/demo` or `infra/control`
- [x] T132 Run `terraform fmt -check` + `terraform validate` across `infra/shared`, `infra/control`,
  `infra/demo`; update `.github/workflows/infra.yml`'s matrix accordingly
- [x] T133 Remove `infra/azure/`, `infra/database/`, `infra/app-host/` once `infra/shared`/
  `infra/control`/`infra/demo` are validated as full replacements

### Orchestration & Jobs

- [x] T134 Scaffold the `functions/` Azure Durable Functions app (Python) with orchestrators for
  provision/deploy/evaluate-golden/evaluate-benchmark/performance-test/export/teardown, each
  creating/updating an `Orchestration Workflow` record via the internal callback API (FR-077,
  data-model.md)
- [x] T135 [P] Implement cancellation routing in the Functions app: propagate a cancel signal to the
  active Container Apps Job and acknowledge idempotently (FR-054, FR-077)
- [x] T136 Scaffold `jobs/` Container Apps Jobs workers: `terraform_runner`, `model_deployment`,
  `evaluation_worker`, `performance_worker`, `export_worker`, each a standalone container reporting
  progress/results to FastAPI's internal callback API (FR-078)
- [x] T137 Ensure `model_deployment` receives any Hugging Face credential only via its own job
  invocation input (never a shared/durable store) and holds it only in process memory (FR-082/FR-083)
- [x] T138 [P] Propagate an OpenTelemetry-compatible correlation ID (the `workflowId`) across FastAPI,
  Durable Functions, and every Container Apps Job invocation, into Application Insights/Log Analytics
  (FR-086)

### Backend (FastAPI)

- [x] T139 Implement the internal callback API (`backend/src/api/internal_workflows.py`):
  `POST /internal/workflows`, `PATCH /internal/workflows/{workflowId}`,
  `POST /internal/workflows/{workflowId}/complete`,
  `POST /internal/workflows/{workflowId}/cancel-ack` (contracts/api.md), authenticated via managed
  identity, distinct from the operator-facing SSO session. Backed by `orchestration_workflow.py`/
  `orchestration_workflow_service.py` and `api/internal_auth.py` (real Entra ID JWT validation, fails
  closed 503 if unconfigured). Along the way fixed a pre-existing Alembic two-head bug
  (`20260821_0002` was mischained off `20260819_0001` instead of `20260819_0002`).
- [x] T140 Update the Azure `ProviderAdapter` implementation (`backend/src/providers/azure/`) to
  acquire the environment lock, create an `Orchestration Workflow`, and start the corresponding
  Durable Functions workflow instead of invoking Terraform/engine deployment directly
  (contracts/provider-interface.md Azure Implementation Notes)
- [x] T141 [P] Reject any internal callback payload containing a Hugging Face credential or an
  interactive prompt/response body with `400`, per contracts/api.md's internal API contract rule
  (FR-082/FR-084). Implemented via `_guard_callback_payload` / `assert_no_interactive_prompt_payload`.
- [x] T142 [P] Add a concurrent-request test proving the single-writer lock rejects a second
  operation with `409` under concurrent (not just sequential) requests against the same environment
  (FR-052, SC-012, Phase 3 item 11 of the refactor prompt). No live Postgres is available anywhere in
  this repo's test infra, so `tests/integration/test_concurrent_workflow_lock.py` uses a
  `RowLockingMemorySession` with a real per-environment `threading.Lock` (held across the request the
  same way Postgres holds a `SELECT...FOR UPDATE` row lock) to exercise real OS thread interleaving
  against the actual route/service code - the most faithful test achievable without a live database.

### Tests

- [x] T143 [P] Contract tests for the internal callback API (`backend/tests/contract/
  test_internal_workflow_api.py`)
- [x] T144 [P] Integration test: Azure `ProviderAdapter.provisionEnvironment` creates an
  `Orchestration Workflow` and resolves to `ready`/`provisioning_failed` only via a callback, never
  by polling Terraform directly
- [x] T145 [P] Playwright end-to-end test for `quickstart.md` Scenario 8 (architecture topology
  validation) where feasible to automate (resource-group/network assertions may instead be a
  scripted Azure CLI check run alongside Playwright)

**Checkpoint**: The deployed topology matches `rg-llm-shared-{stage}` / `rg-llm-control-{stage}` /
`rg-llm-demo-{environmentId}`; Durable Functions and Container Apps Jobs handle orchestration/
execution; User Stories 1-9 continue to pass their existing tests unchanged.

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that span multiple user stories.

- [x] T118 [P] Write `README.md` setup/run instructions covering backend, frontend, and Terraform infra
  — done: root `README.md` plus `backend/README.md`, `frontend/README.md`, `infra/README.md`, each
  covering setup/run for its component
- [ ] T119 [P] Document structured logging and event-log/trace instrumentation conventions (`docs/observability.md`) per FR-062 — **gap**: `docs/observability.md` does not exist; no dedicated observability doc found
- [ ] T120 Run the full `quickstart.md` validation end-to-end (all eight scenarios plus the Cross-Cutting Checks section: concurrency/FR-052, no-auto-retry/FR-055, reference execution profile/FR-058, audit trail/FR-004) — **gap**: not run as a full formal pass; ad hoc hands-on testing has surfaced BUG-001 and BUG-002 (see Known Issues below), which a full run would also need to account for
- [x] T121 [P] Security hardening review: verify HF and Azure credentials are never persisted or displayed anywhere in logs, database rows, or API responses (FR-011)
  — done: enforced in code via `backend/src/domain/hf_credentials.py`'s `accept_hf_token`/
  `assert_hf_token_not_persisted`/`forwarded_hf_token`, called from `api/routes/deployments.py` and
  `api/internal_workflows.py` before any response/state write; Azure credentials use OIDC federated
  identity in CI (`.github/workflows/*.yml`), never a stored secret
- [ ] T122 [P] Performance review of the end-to-end demo workflow (provision -> deploy -> tune -> test -> redeploy -> compare) against the 60-minute reference-profile target (SC-002, FR-058) — **gap**: no recorded review; ties into T120's full quickstart run
- [x] T123 [P] Add a CI workflow running backend lint/tests, frontend lint/tests, and Terraform `validate`/`fmt -check` (`.github/workflows/ci.yml`)
  — done, but split into 3 component workflows rather than one file: `.github/workflows/backend.yml`
  (ruff + black --check + pytest), `frontend.yml` (lint + build + npm test), `infra.yml` (terraform
  fmt -check + validate per module). Note: GitHub Actions is currently disabled for this repo
  (operator preference — changes are pushed via CLI); the workflow files are in place and would run
  if Actions were re-enabled
- [x] T124 Re-verify the Constitution Check against the implemented code (all 5 principles) and update `plan.md`'s Post-Phase-1 re-check note if anything diverged
  — done: added a "Post-implementation re-check" note to `plan.md` correcting Principle V's
  now-stale "single provider interface"/"one inference engine" claims (superseded by the local
  provider and Ollama engine from User Story 7); all 5 principles re-verified and remain PASS
- [ ] T125 [P] Code cleanup and dead-code removal pass across `backend/` and `frontend/` — not yet done; no dedicated pass has been run

---

## Phase 12: User Story 8 - Navigate and Configure Without Memorizing IDs (Priority: P8) — remaining gaps

**Note**: User Story 8 was added to spec.md after this task list's initial authoring; it never received
a task breakdown until this pass. 4 of its 6 acceptance scenarios are already satisfied by existing
code (`EnvironmentPicker.tsx`, `ConfigVersionHistory.tsx`, and a clean hardcoded-ID-free nav in
`App.tsx`) and need no new tasks. The tasks below cover the 2 scenarios confirmed still failing.

- [ ] T146 [US8] Frontend: replace the golden-dataset free-text `Input` + HTML `<datalist>`
  (`frontend/src/pages/QualityRun.tsx`) with a searchable Fluent UI `Dropdown`-based
  `GoldenDatasetPicker` component (`frontend/src/components/GoldenDatasetPicker.tsx`) showing name,
  version, and provenance/review status per spec.md US8 Acceptance Scenario 2
- [ ] T147 [US8] Frontend: replace the performance-workload free-text `Input` + HTML `<datalist>`
  (`frontend/src/pages/PerformanceRun.tsx`) with a searchable Fluent UI `Dropdown`-based
  `PerformanceWorkloadPicker` component (`frontend/src/components/PerformanceWorkloadPicker.tsx`)
  showing name and description per spec.md US8 Acceptance Scenario 3
- [x] T148 [US8] Frontend: add a "Skip to main content" link as the first focusable element in
  `frontend/src/App.tsx`, targeting the existing `<main>` landmark, per spec.md US8 Acceptance
  Scenario 6 — **Done**: added a Griffel `skipLink` style (visually hidden until focused) and an
  `<a href="#main-content">` as the first child of the app shell; `<main>` now has
  `id="main-content" tabIndex={-1}`.
- [x] T149 [US8] Frontend: remove redundant `aria-label` attributes on inputs already labeled via a
  Fluent `<Field label=...>` wrapper (at least `Exercise.tsx`'s Prompt/Parameters JSON fields,
  `QualityRun.tsx`'s Run type/Golden dataset fields, and `Deploy.tsx`'s Catalog entry field) per
  spec.md US8 Acceptance Scenario 6 — **Done**: removed duplicate `aria-label`s across
  `Deploy.tsx` (9), `Exercise.tsx` (2), `QualityRun.tsx` (3), and `PerformanceRun.tsx` (1); the
  Fluent `Field` label now supplies the sole accessible name (verified via updated test
  selectors in `QualityRun.test.tsx`).

**Checkpoint**: All 6 acceptance scenarios of User Story 8 pass.

---

## Phase 13: User Story 9 - Diagnose and Recover from Failures Quickly (Priority: P9) — remaining gap

**Note**: User Story 9 was added to spec.md after this task list's initial authoring and never received
a task breakdown. 4 of its 5 acceptance scenarios already pass with existing code
(`backend/src/api/errors.py`, `correlation.py`, `frontend/src/services/apiClient.ts`, and per-page
error handling). The task below covers the one confirmed gap.

- [x] T150 [US9] Backend: include request method, path, and the request/correlation ID in the
  unhandled-exception log line (`LOGGER.exception(...)` in `backend/src/api/errors.py`) so a returned
  `requestId` can be cross-referenced against server logs without a separate lookup, per spec.md US9
  Acceptance Scenario 2 — **Done**: the log message now embeds `method=%s path=%s request_id=%s`
  directly (guaranteed visible regardless of formatter config) and still attaches the same fields via
  `extra=` for structured-logging consumers.

**Checkpoint**: All 5 acceptance scenarios of User Story 9 pass.

---

## Phase 14: User Story 11 - Configure Additional Runtime and Evaluation Settings (Priority: P11)

**Note**: User Story 11 was added to spec.md after this task list's initial authoring and never
received a task breakdown. Verification found it ~20% complete: only the read-path (`maxGenTokens`/
`useChatCompletions` defaults in `backend/src/evaluation/lm_eval_runner.py`) exists; there is no
update API, no UI, no validation, and `think_end_token` is hardcoded rather than configurable. All
tasks below are net-new.

**Goal**: An operator can change a benchmark's advanced runtime/evaluation settings (generation token
budget, chat-completions mode, reasoning-trace end marker) through configuration, with validation and
documented defaults, and without a backend code change or redeploy.

**Independent Test**: See spec.md User Story 11 Independent Test.

### Tests for User Story 11

- [ ] T151 [P] [US11] Contract test for a benchmark-definition settings update endpoint
  (`backend/tests/contract/test_benchmark_settings.py`) covering a successful update and a
  validation-rejected update
- [ ] T152 [P] [US11] Unit test: invalid/out-of-range setting values (e.g. negative or excessive
  `maxGenTokens`) are rejected at save time with an actionable message, never silently accepted
  (`backend/tests/unit/test_benchmark_settings_validation.py`) per spec.md US11 Acceptance Scenario 3

### Implementation for User Story 11

- [ ] T153 [US11] Add a Pydantic request/response model for benchmark advanced settings
  (`maxGenTokens: int` range-checked, `useChatCompletions: bool`, `thinkEndToken: str`, each with a
  documented default) (`backend/src/api/routes/runs.py` or a new `backend/src/api/schemas/
  benchmark_settings.py`) per spec.md US11 Acceptance Scenario 2
- [ ] T154 [US11] Implement `PATCH /benchmark-definitions/{benchmarkId}` validating and persisting the
  settings above into `BenchmarkDefinition.presentationSubset`, rejecting invalid values with `400` +
  actionable message (`backend/src/api/routes/runs.py`) per spec.md US11 Acceptance Scenario 1/3
- [ ] T155 [US11] Make `think_end_token` configurable: read it from
  `presentationSubset.thinkEndToken` with a fallback default of `"</think>"` instead of the current
  hardcoded value (`backend/src/evaluation/lm_eval_runner.py`) per spec.md US11 Acceptance Scenario 1/2
- [ ] T156 [US11] Frontend: add a benchmark advanced-settings form (e.g. within
  `frontend/src/pages/QualityRun.tsx` or a new settings page) letting an operator view current values
  and documented defaults, edit them, and see inline validation errors from the backend
- [ ] T157 [US11] Document `maxGenTokens`, `useChatCompletions`, and `thinkEndToken` and their defaults
  in `data-model.md`'s Benchmark Definition entity

**Checkpoint**: All 3 acceptance scenarios of User Story 11 pass; an operator can change these
settings and see them take effect on the next run without a code change or redeploy.

---

**Note on User Story 12 (Deploy Microsoft Phi Models, Priority: P12)**: also added to spec.md after
this task list's initial authoring. Unlike US8/US9/US11, it required no remaining-gap phase — it was
implemented and shipped as a single, complete, small PR (`ModelFamily.PHI` in
`backend/src/domain/enums.py`, three catalog entries in the seed data, `Deploy.tsx` catalog-context
notes, and `backend/tests/unit/test_seed_catalog_phi.py`; see spec.md User Story 12 Status). No new
tasks are needed for it here.

---

## Phase 14: Deployment Configuration Linkage (data model gap, user-reported)

**Note**: not part of the original task breakdown. A user-reported logic bug: environments and their
quality/performance runs exposed only bare deployment revision ids, with no resolved model/engine/
settings information, making it impossible to tell what configuration produced a given environment
state or run result without manually cross-referencing database rows.

- [x] T151 Backend + frontend: expose resolved deployment configuration (engine id, catalog entry
  id, resolved checkpoint ref, model/serving/generation settings) instead of bare config ids —
  **Done**: added to `GET /environments` (per-environment `activeDeploymentConfiguration`, plus the
  previously-missing `activeDeploymentRevisionId`, via one joined query to avoid N+1), `GET
  /environments/{id}` (`AzureEnvironmentStateService.getEnvironmentState`'s new
  `context.activeDeploymentConfiguration`), `GET /environments/{id}/deployments/{revisionId}` (new
  `configuration` sub-object), and `GET /environments/{id}/runs`, `GET
  /environments/{id}/runs/{runId}`, `GET /environments/{id}/runs/{runId}/report` (new
  `configuration` field, read from each run's immutable `environmentContextSnapshot` per FR-020
  rather than re-joining current, possibly since-changed config rows). Frontend: added
  `DeploymentConfigurationSummary` to `frontend/src/services/types.ts`, mapped it through
  `environmentsApi.ts`, and surfaced it in `EnvironmentDetail.tsx`, `Overview.tsx`,
  `RunHistory.tsx` (new "Model / engine" column so runs across configs are distinguishable),
  `QualityRun.tsx`, `PerformanceRun.tsx`, `QualityReport.tsx`, and `PerformanceReport.tsx`. Verified
  with the full backend pytest suite (121 passed) and `npm run build` plus targeted vitest runs
  (`EnvironmentDetail`, `QualityReport`, `QualityRun`, `Deploy`, `Exercise`, `Provision`, `App`).

---

## Known Issues (Bug Backlog — not yet triaged, do not fix without further investigation)

User-reported runtime issues observed in hands-on use. Recorded here for future investigation; not
yet root-caused, not scoped to a specific task, and explicitly not to be worked on until picked up
deliberately.

- [ ] BUG-001 Local/Ollama environment provisioning failed in a hands-on run (User Story 7). Not yet
  reproduced or root-caused — needs investigation into whether this is an Ollama-reachability issue,
  a `LocalProviderAdapter` bug, or an environment-specific (presenter machine) problem before any fix
  is attempted.
- [ ] BUG-002 Model deployment status updates are not clearly communicated in the UI while a
  deployment is in progress — unclear to an operator whether the deployment is actually progressing
  or stalled. Needs verification of whether the underlying deployment/polling mechanism is working
  correctly at all (possible overlap with User Story 9's per-step-diagnostics gap) before deciding
  between a backend fix and a frontend/copy fix. Proposed direction (not yet implemented): the
  environment overview should indicate, per environment, whether a job is currently in progress
  (i.e. the environment is not yet ready for the next action) and name the specific running
  operation (e.g. "Provisioning infrastructure", "Deploying model", "Tearing down") rather than
  leaving the operator to infer status from a single generic state.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories.
- **User Stories (Phase 3-9)**: All depend on Foundational phase completion.
  - Stories are listed in priority order (P1 -> P7) and are each independently testable, but US2 needs a provisioned environment from US1's provider adapter, US3/US4 need a ready deployment from US2, US5 needs completed runs from US3/US4 to have something to compare, and US7 reuses the same provider/engine contracts and lifecycle model as US1/US2 — so while each story's *code* is independent, running the *independent test* for a later story presupposes the earlier stories' happy path exists. Sequential delivery in priority order is recommended.
- **Baseline Pilot Architecture (Phase 10 / User Story 10)**: Depends on User Stories 1-9's provider/engine adapter interfaces already existing (it refactors their Azure implementation, not their contracts); BLOCKS any further real Azure deployment once started, since `infra/azure`/`infra/database`/`infra/app-host` are removed as part of it.
- **Polish (Phase 11)**: Depends on all desired user stories, including User Story 10, being complete.

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies on other stories. True MVP starting point.
- **User Story 2 (P2)**: Requires a provisioned `Demo Environment` (US1) to deploy into; the deployment/prompt code itself is independent.
- **User Story 3 (P3)**: Requires a ready `Deployment Revision` (US2) to evaluate against.
- **User Story 4 (P4)**: Requires a ready `Deployment Revision` (US2) to load-test; independent of US3.
- **User Story 5 (P5)**: Requires at least one completed `Experiment Run`/`Result Report` (US3 and/or US4) to compare against.
- **User Story 6 (P6)**: Requires a provisioned environment (US1) to tear down; independent of US2-US5's evaluation features.
- **User Story 7 (P7)**: Reuses the provider adapter interface (US1) and inference engine adapter interface (US2) for a local, non-Azure implementation; independent of US2-US6's specific features once those interfaces exist.
- **User Story 10 (P0 - Foundational, sequenced last)**: Reuses the provider/engine adapter interfaces (US1/US2) and every downstream story's behavior contracts; changes only how the Azure implementation of those interfaces executes (via Durable Functions + Container Apps Jobs instead of in-process) and where resources live (3-RG topology). All of User Stories 1-9's independent tests must still pass unchanged once this story is complete.

### Within Each User Story

- Tests are written first and MUST fail before implementation.
- Models/migrations (Foundational) before adapters before endpoints before frontend pages.
- Contract tests before integration tests before unit tests, per phase ordering above.
- Story implementation complete and its Playwright e2e scenario passing before moving to the next priority.

### Parallel Opportunities

- All Setup tasks marked `[P]` (T003-T009) can run in parallel.
- All Foundational entity-model tasks marked `[P]` (T013-T025) can run in parallel once T011/T012 (DB + migration framework) are done.
- T031-T034 (the two adapter interfaces and their contract-test scaffolding) can run in parallel.
- Once Foundational completes, US1 and US6 can be staffed in parallel (both only depend on the Azure provider adapter, not on each other); US3 and US4 can be staffed in parallel once US2 is done (both only depend on a ready deployment).
- All `[P]`-marked tests within a story's Tests subsection can run in parallel.

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Contract test for POST /environments/preview in backend/tests/contract/test_environments_preview.py"
Task: "Contract test for POST /environments in backend/tests/contract/test_environments_create.py"
Task: "Integration test for the full provision flow in backend/tests/integration/test_provision_flow.py"
```

## Parallel Example: Foundational Entity Models

```bash
# Launch all entity model + migration tasks together (after T011/T012):
Task: "Create the Cloud Deployment Profile model + migration in backend/src/domain/profile.py"
Task: "Create the Model Catalog Entry model + migration in backend/src/domain/catalog.py"
Task: "Create the Demo Environment model + migration in backend/src/domain/environment.py"
Task: "Create the Model Configuration model + migration in backend/src/domain/model_configuration.py"
Task: "Create the Inference Configuration model + migration in backend/src/domain/inference_configuration.py"
Task: "Create the Inference Engine model + migration in backend/src/domain/inference_engine.py"
Task: "Create the Deployment Revision model + migration in backend/src/domain/deployment_revision.py"
Task: "Create the Golden Dataset model + migration in backend/src/domain/golden_dataset.py"
Task: "Create the Benchmark Definition model + migration in backend/src/domain/benchmark_definition.py"
Task: "Create the Performance Workload model + migration in backend/src/domain/performance_workload.py"
Task: "Create the Experiment Run model + migration in backend/src/domain/experiment_run.py"
Task: "Create the Result Report model + migration in backend/src/domain/result_report.py"
Task: "Create the Comparison model + migration in backend/src/domain/comparison.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1 (Provision a Demo Environment).
4. **STOP and VALIDATE**: run `e2e/tests/provision.spec.ts` and quickstart.md Scenario 1 independently.
5. Demo the provisioning flow if ready.

### Incremental Delivery

1. Setup + Foundational -> foundation ready.
2. Add User Story 1 -> validate independently -> demo (MVP!).
3. Add User Story 2 -> validate independently -> demo (deploy + exercise a model).
4. Add User Story 3 -> validate independently -> demo (quality evaluation).
5. Add User Story 4 -> validate independently -> demo (performance measurement).
6. Add User Story 5 -> validate independently -> demo (retune/redeploy/compare narrative complete).
7. Add User Story 6 -> validate independently -> demo (safe teardown; full lifecycle complete).
8. Each story adds value without breaking previous stories, since prior deployment revisions and results are immutable (FR-019/020).

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together.
2. Once Foundational is done:
   - Developer A: User Story 1, then User Story 6 (both center on the Azure provider adapter).
   - Developer B: User Story 2, then User Story 3 (deployment, then quality evaluation on top of it).
   - Developer C: User Story 4, staffed once US2's deployment code lands; then User Story 5 once US3/US4 produce results to compare.
3. Stories complete and integrate independently, validated by each story's own Playwright e2e scenario.

---

## Notes

- `[P]` tasks touch different files with no dependency on an incomplete task.
- `[Story]` labels map every user-story-phase task to spec.md's US1-US6 for traceability.
- Every user story is independently completable and testable via its own quickstart.md scenario.
- Verify contract/integration tests fail before implementing the corresponding code.
- Commit after each task or logical group, following this repository's commit-trailer convention.
- Stop at any checkpoint to validate a story independently before continuing.
- Avoid: vague tasks, same-file conflicts inside a `[P]` batch, and cross-story dependencies that would break a story's independent testability.
