# Data Model: Azure LLM Serving Demo

**Input**: Key Entities section of [spec.md](./spec.md); Phase 0 [research.md](./research.md)

All entities are provider-agnostic domain objects persisted in PostgreSQL, the portable relational
database selected in `research.md` Section 5b (FR-047); genuinely variable payloads (config
key/value pairs, event-log entries) use JSONB columns. None of these types reference Azure-specific fields directly;
Azure-specific details live inside the `Cloud Deployment Profile.providerConfig` and
`Demo Environment.providerState` payloads, which are opaque to the domain layer (FR-037).

## Entity Overview

```text
Cloud Deployment Profile ---- describes ---> Demo Environment
Model Catalog Entry ---- selected into ---> Model Configuration
Model Configuration --+
                       +--> Deployment Revision <--+-- Inference Configuration
Demo Environment ------+                           |
                                                    +-- Inference Engine (fixed in v1)
Deployment Revision ---- tested by ---> Experiment Run ---- produces ---> Result Report
Golden Dataset / Benchmark Definition / Performance Workload ---- define ---> Experiment Run
Experiment Run (x2, compatible) ---- forms ---> Comparison
```

## Entities

### Cloud Deployment Profile

A validated, provider-specific description of infrastructure for a model size class (FR-005,
FR-006).

| Field | Type | Notes |
|-------|------|-------|
| `profileId` | string (immutable) | Stable identifier, e.g. `azure-single-gpu-3b` |
| `provider` | enum | `azure` \| `local` (FR-037, FR-065) |
| `modelSizeClass` | enum | `3b` \| `7b` \| `70b` |
| `eligibleRegions` | string[] | Candidate Azure regions for quota/capacity evaluation (FR-038) |
| `vmSku` | string | e.g. `Standard_NC16as_T4_v3` (3B/7B), `Standard_NC24ads_A100_v4` (27B), `Standard_NC80adis_H100_v5` (70B) — research.md Section 4 (FR-038-040) |
| `capacityAssumptions` | object | GPU count, GPU memory, quantization requirement flag |
| `configurableInputs` | object | Presenter-adjustable provisioning inputs and their defaults |
| `knownLimitations` | string[] | e.g. "70B requires quantization on this SKU" |
| `version` | int | Bumped when the profile definition changes |

**Validation**: `modelSizeClass` MUST match at least one `Model Catalog Entry.sizeClass` to be
selectable (FR-005, FR-016). A `provider: local` profile (User Story 7) has no meaningful
`eligibleRegions`/`vmSku` and skips quota/capacity evaluation entirely (FR-065); it MUST still
resolve a compatible `modelSizeClass` and set `capacityAssumptions` to reflect commodity presenter
hardware (CPU or a single consumer GPU) rather than an Azure accelerator SKU.

### Demo Environment

A provisioned cloud environment (FR-007, FR-017).

| Field | Type | Notes |
|-------|------|-------|
| `environmentId` | string (immutable) | Primary key |
| `profileId` | ref -> Cloud Deployment Profile | Selected profile |
| `provider` | enum | `azure` \| `local` |
| `region` | string | Actual region used; may differ from the recommended default (FR-040) |
| `regionRecommendation` | object | `{ recommendedRegion, evidence, evaluatedAt, uncertaintyNote }` (FR-039) |
| `lifecycleState` | enum | `not_provisioned` \| `provisioning` \| `ready` \| `provisioning_failed` \| `tearing_down` \| `torn_down` \| `teardown_failed` (FR-055 finite transitions) |
| `activeDeploymentRevisionId` | ref -> Deployment Revision, nullable | At most one active revision (FR-009) |
| `activeOperationId` | ref -> operation lock, nullable | Enforces single-writer semantics (FR-052) |
| `providerState` | object (opaque) | Provider-specific resource identifiers/state |
| `createdBy` / `lastModifiedBy` | string (SSO identity) | Audit trail (FR-004) |
| `createdAt` / `updatedAt` | timestamp | |

**State transitions** (FR-055): `not_provisioned -> provisioning -> {ready, provisioning_failed}`;
`ready -> tearing_down -> {torn_down, teardown_failed}`; `provisioning_failed` and
`teardown_failed` are terminal until a user explicitly retries (FR-055 clarification), which
re-enters `provisioning`/`tearing_down` respectively. Any transition attempt while
`activeOperationId` is set to a different operation MUST be rejected (FR-052, FR-053).

### Model Catalog Entry

An approved model available for deployment (FR-010).

| Field | Type | Notes |
|-------|------|-------|
| `catalogEntryId` | string (immutable) | |
| `family` | enum | `gemma` \| `llama` \| `chinese-origin` \| `phi` (catalog of 9 checkpoints in research.md Section 2, e.g. `google/gemma-3-27b-it`, `meta-llama/Llama-3.3-70B-Instruct`, `Qwen/Qwen3-32B`; `phi` added by User Story 12 — `phi-3.5-mini-instruct`, `phi-4`, `phi-3.5-moe-instruct`) |
| `sizeClass` | enum | `3b` \| `7b` \| `70b` |
| `huggingFaceRepoId` | string | e.g. `org/model-name` |
| `checkpointRef` | string | Tag/branch reference; MAY be mutable (FR-012, Clarification 5) |
| `isGated` | bool | Whether HF access approval/token is required (FR-011) |
| `license` | string | License identifier/URL |
| `compatibleProfileIds` | ref[] -> Cloud Deployment Profile | |
| `quantizationRequired` | bool | True for 70B tier on the resolved single-server SKU |
| `notes` | string | Evaluation limitations, demo-value notes (FR-044) |

### Model Configuration

A versioned selection of checkpoint and model-specific settings (FR-012).

| Field | Type | Notes |
|-------|------|-------|
| `modelConfigId` | string (immutable) | |
| `catalogEntryId` | ref -> Model Catalog Entry | |
| `resolvedCheckpointRef` | string | Snapshot of `checkpointRef` at creation time (best-effort) |
| `modelSettings` | object | e.g. max context, sampling defaults exposed to the presenter |
| `version` | int | New version on every change (FR-019) |
| `createdBy` / `createdAt` | | Audit (FR-004) |

### Inference Configuration

A versioned set of serving/generation settings for the selected engine (FR-013).

| Field | Type | Notes |
|-------|------|-------|
| `inferenceConfigId` | string (immutable) | |
| `engineId` | ref -> Inference Engine | Fixed single value in v1 (FR-014) |
| `servingSettings` | object | Batching/concurrency/quantization runtime flags, with visible defaults (FR-013) |
| `generationSettings` | object | Sampling/temperature/max-tokens defaults |
| `version` | int | New version on every change (FR-019) |
| `createdBy` / `createdAt` | | Audit (FR-004) |

### Inference Engine

The pluggable engine implementation selected in research.md Section 1 (FR-014, FR-041/042):
vLLM, served via the official `vllm/vllm-openai` Docker image, for Azure deployments. User Story 7
adds a second, local-only engine: Ollama, serving small Qwen checkpoints on the presenter's own
machine (FR-066).

| Field | Type | Notes |
|-------|------|-------|
| `engineId` | string (immutable) | `vllm` (Azure) or `ollama` (local, User Story 7) |
| `adapterContractVersion` | string | Version of the internal pluggable interface it implements |
| `capabilities` | object | Declares supported quantization modes, max model size, metrics endpoints exposed. `ollama` does not expose an accelerator-utilization metrics endpoint (FR-026 "available accelerator utilization" reports unavailable). |

### Deployment Revision

An immutable record connecting environment + configs + engine (FR-019, FR-020).

| Field | Type | Notes |
|-------|------|-------|
| `deploymentRevisionId` | string (immutable) | |
| `environmentId` | ref -> Demo Environment | |
| `modelConfigId` | ref -> Model Configuration (immutable snapshot) | |
| `inferenceConfigId` | ref -> Inference Configuration (immutable snapshot) | |
| `engineId` | ref -> Inference Engine | |
| `lifecycleState` | enum | `pending` \| `deploying` \| `ready` \| `deployment_failed` \| `superseded` (FR-055) |
| `activePeriod` | object | `{ activatedAt, deactivatedAt (nullable) }` |
| `createdBy` / `createdAt` | | Audit (FR-004) |

**State transitions**: `pending -> deploying -> {ready, deployment_failed}`; `ready -> superseded`
when a new revision is activated (FR-019); prior ready/superseded revisions and their results
remain immutable and linked (User Story 5, FR-030).

### Golden Dataset

A versioned curated prompt set (FR-021, FR-022).

| Field | Type | Notes |
|-------|------|-------|
| `goldenDatasetId` | string (immutable) | |
| `version` | int | |
| `cases[]` | object[] | `{ caseId, prompt, deterministicCheck, provenance: 'curated'\|'ai-generated', reviewStatus }` |
| `duplicateCheckState` | enum | Surfaces duplicate-case edge case from spec Edge Cases |

**Validation**: an `ai-generated` case MUST carry a `reviewStatus` other than `unreviewed` before
it can be included in a run that is presented as final (Edge Cases: "unreviewed AI-generated
content").

### Benchmark Definition

A selected, versioned standard benchmark and its presentation subset (FR-023; benchmark set
resolved in research.md Section 3 — GSM8K, IFEval, and MMLU 5-subject mini).

| Field | Type | Notes |
|-------|------|-------|
| `benchmarkId` | string (immutable) | `gsm8k` \| `ifeval` \| `mmlu-mini` (research.md Section 3) |
| `version` | string | Upstream dataset/version reference |
| `presentationSubset` | object | `{ sampleSize, samplingMethod, useChatCompletions?, maxGenTokens? }` — keeps runtime presentation-sized. `useChatCompletions` (bool, default `false`) routes the run through the chat-completions endpoint with the chat template applied, required for instruction-following-style benchmarks like `ifeval` (`backend/src/evaluation/lm_eval_runner.py`); `maxGenTokens` (int, default `2048`) is the generation token budget applied only when `useChatCompletions` is set, giving hybrid-reasoning models (e.g. Qwen3) enough headroom to emit a `<think>...</think>` trace and still answer. **Known gap (User Story 11, not yet implemented)**: there is no update endpoint, UI, or validation for these fields today — they can only be changed by editing seed data directly; a reasoning end-of-thinking marker (currently hardcoded to `"</think>"` in `lm_eval_runner.py` as `think_end_token`) is not yet modeled as a field here at all. |
| `passFailThreshold` | object | Documented threshold/regression rule (FR-056) |

### Performance Workload

A versioned load/performance test definition (FR-025).

| Field | Type | Notes |
|-------|------|-------|
| `workloadId` | string (immutable) | |
| `version` | int | |
| `warmup` | object | Warm-up request count/duration |
| `inputProfile` | object | Prompt length/distribution |
| `concurrency` | int | |
| `durationOrRequestCount` | object | One of duration or fixed request count |
| `safetyLimits` | object | Max concurrency/duration/requests (Edge Cases: workload safety limits) |
| `completionCriteria` | object | |

### Experiment Run

Execution record connecting a deployment revision and a test definition (FR-020, FR-028).

| Field | Type | Notes |
|-------|------|-------|
| `runId` | string (immutable) | |
| `deploymentRevisionId` | ref -> Deployment Revision | |
| `runType` | enum | `quality-golden` \| `quality-benchmark` \| `performance` \| `interactive-prompt` |
| `testDefinitionRef` | ref -> Golden Dataset \| Benchmark Definition \| Performance Workload, nullable for `interactive-prompt` | |
| `status` | enum | `queued` \| `running` \| `completed` \| `cancelled` \| `failed` \| `incomplete` (FR-028) |
| `environmentContextSnapshot` | object | Immutable snapshot per FR-020 |
| `startedAt` / `endedAt` | timestamp | |
| `diagnostics[]` | object[] | Actionable diagnostic entries (SC-007) |
| `eventLogRef` | ref -> per-operation event log | Captured per FR-062 even though only summary metrics surface in v1 UI |
| `cancellationRequests[]` | object[] | Tracks idempotent cancellation attempts (FR-054) |
| `retentionClass` | enum | `persisted` (golden/benchmark/performance, FR-061) \| `session-ephemeral` (interactive prompt, FR-060) |

**State transitions** (FR-055): `queued -> running -> {completed, cancelled, failed, incomplete}`.
A `running` run conflicting with another active run/operation on the same environment MUST be
rejected at admission time (FR-052, SC-012), not queued.

**Retention rule** (FR-060/FR-061): `interactive-prompt` runs and their captured response text
MUST be purged at end of user session or environment teardown, whichever is first, and MUST NOT
be copied into `Result Report`/`Comparison` records that persist beyond that point.

### Result Report

Outcomes with units and completeness (FR-024, FR-026, FR-027).

| Field | Type | Notes |
|-------|------|-------|
| `resultReportId` | string (immutable) | |
| `runId` | ref -> Experiment Run | |
| `quality` | object, nullable | Per-case pass/fail/errored/skipped/incomplete plus aggregate (FR-024, FR-056) |
| `performance` | object, nullable | TTFT, inter-token latency, end-to-end latency (each with p50/p95), throughput, failures, accelerator utilization, units (FR-026, FR-057) |
| `completenessIndicator` | enum | `complete` \| `partial` \| `unavailable-monitoring-data` |
| `referenceExecutionProfileRef` | ref, nullable | Present when this run is measured against the 60-minute target (FR-058) |

### Comparison

A retained view of differences across selected runs (FR-031, FR-032, FR-059).

| Field | Type | Notes |
|-------|------|-------|
| `comparisonId` | string (immutable) | |
| `resultReportIds` | ref[] -> Result Report (2+) | |
| `configurationDiff` | object | Model/inference/profile differences |
| `qualityDiff` / `performanceDiff` / `failureDiff` / `utilizationDiff` | object | Side-by-side deltas (FR-031) |
| `comparabilityStatus` | enum | `comparable` \| `not-directly-comparable` |
| `comparabilityReasons[]` | string[] | Populated when checkpoint, dataset, workload, infrastructure profile, or region differ (FR-059) |

### Orchestration Workflow

A Durable Functions workflow instance coordinating one long-running operation for a Demo
Environment (User Story 10, FR-077). Provider-agnostic at the domain layer: for the Azure provider
this maps 1:1 to a Durable Functions orchestrator instance; the local/Ollama provider (User Story 7)
runs the equivalent steps in-process and does not create one of these records, since it involves no
Azure orchestration.

| Field | Type | Notes |
|-------|------|-------|
| `workflowId` | string (immutable) | Also used as the OpenTelemetry-compatible correlation ID propagated to FastAPI, the Durable Functions orchestrator, and any dispatched Container Apps Job (FR-086) |
| `environmentId` | ref -> Demo Environment | |
| `operationId` | ref -> the lock value held in `Demo Environment.activeOperationId` while this workflow runs | Ties the workflow to the single-writer lock (FR-052) |
| `workflowType` | enum | `provision` \| `deploy` \| `evaluate-golden` \| `evaluate-benchmark` \| `performance-test` \| `export` \| `teardown` |
| `dispatchedJobRef` | ref, nullable -> Container Apps Job execution identifier | Set once the orchestrator dispatches isolated execution (FR-078) |
| `phase` | string | Current human-readable phase, surfaced to the operator UI (FR-049) |
| `status` | enum | `running` \| `completed` \| `failed` \| `cancelled` (FR-055 terminal states) |
| `cancellationRequested` | bool | Set by an idempotent cancellation request; propagated to the dispatched job (FR-054) |
| `startedAt` / `endedAt` | timestamp | |

**Validation**: A workflow MUST NOT be created unless FastAPI has already acquired
`Demo Environment.activeOperationId` for the same `operationId` (FR-052/FR-083 of the pilot
architecture addendum below). The workflow itself carries no domain state (model config, inference
config, results) — it only tracks orchestration progress; domain records are written by FastAPI
when a Container Apps Job reports back through the internal callback API.

## Cross-Cutting Rules

- **Immutability**: `Deployment Revision`, `Model Configuration` (once activated), `Inference
  Configuration` (once activated), `Experiment Run`, and `Result Report` are never mutated in
  place after creation; changes always create a new version/revision (FR-019, FR-020, FR-030).
- **Audit**: every entity created or transitioned by a configuration-changing or destructive
  action carries the acting SSO identity (FR-004).
- **Single-writer lock**: `Demo Environment.activeOperationId` is the enforcement point for
  FR-052/FR-053; any provisioning, deployment, teardown, evaluation run, performance run, or
  interactive prompt submission acquires this lock before starting and releases it on terminal
  state.
- **Credential non-persistence** (User Story 10, FR-082/FR-083): a presenter-supplied Hugging Face
  credential MUST NOT appear as a field on any entity in this data model, in any JSONB payload
  (including `Demo Environment.providerState`, `Orchestration Workflow`, or any event-log entry
  captured per FR-062), or in any Terraform state/plan output. It is passed directly to the
  Container Apps Job process that needs it and exists only in that process's memory.
- **Interactive-prompt non-persistence** (FR-060, FR-084): interactive prompt/response bodies MUST
  NOT be written to any table, JSONB payload, or event-log entry that outlives the user session or
  environment teardown; only automated golden/benchmark/performance run data is persisted per
  FR-061.
