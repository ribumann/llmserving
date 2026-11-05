# Contracts: Operator Web API

**Input**: FR-035, FR-048, FR-049, User Stories 1-11 in [spec.md](../spec.md); entities in
[data-model.md](../data-model.md)

This is the HTTP contract between the frontend operator web app and the backend. It is the single
external-facing interface for this feature (the Azure provider and inference engine are internal
adapter contracts, documented separately in `provider-interface.md` and `engine-interface.md`).
All endpoints require an authenticated organization SSO session (FR-001); any authenticated user
may call any endpoint in v1 (FR-003). Every mutating endpoint records the caller's SSO identity for
audit (FR-004) and enforces the single-writer lock on the target `Demo Environment` (FR-052).

## Conventions

- All responses include `requestId` for correlation with the captured event log (FR-062).
- Long-running operations return `202 Accepted` with an `operationId`/`runId` and current phase;
  clients poll or subscribe for progress (FR-008, FR-049).
- Conflicting mutating requests against a locked environment return `409 Conflict` with an
  actionable message (FR-052, SC-012), never silently queued.
- Failed operations return a terminal failure state plus at least one actionable diagnostic
  (SC-007); the system never auto-retries (FR-055).

## Endpoints

### Profiles & Catalog

- `GET /profiles` -> list `Cloud Deployment Profile` (FR-005, FR-006)
- `GET /catalog` -> list `Model Catalog Entry` (FR-010)

### Environment Lifecycle (User Story 1, User Story 6)

- `POST /environments/preview` -> region/quota/capacity recommendation preview given a
  `profileId` (FR-038, FR-039); does not acquire the write lock
- `POST /environments` -> provision a `Demo Environment` for a profile + region (may override the
  recommended region; revalidates quota/capacity/compatibility, FR-040)
- `GET /environments` -> list existing `Demo Environment` records (id, name, lifecycle state,
  region), backing the environment picker used across Deploy/Exercise/Quality/Performance (User
  Story 8) instead of requiring a typed environment ID
- `GET /environments/{environmentId}` -> current state, active revision, resource/cost/capacity
  context (FR-017)
- `POST /environments/{environmentId}/teardown/preview` -> resource preview and consequences
  (FR-033); rejected with `409` if an operation is active (FR-053)
- `POST /environments/{environmentId}/teardown` -> requires prior preview token + explicit
  confirmation; returns per-resource removed/retained/failed outcome (FR-034)

### Deployment (User Story 2, User Story 5)

- `POST /environments/{environmentId}/model-configurations` -> create a new `Model Configuration`
  version (FR-012, FR-019)
- `GET /environments/{environmentId}/model-configurations` -> list existing `Model Configuration`
  versions for the environment (version, checkpoint ref, created date), backing the configuration
  version picker (User Story 8 Acceptance Scenario 4)
- `POST /environments/{environmentId}/inference-configurations` -> create a new
  `Inference Configuration` version (FR-013, FR-019)
- `GET /environments/{environmentId}/inference-configurations` -> list existing
  `Inference Configuration` versions for the environment (version, engine, created date)
- `POST /environments/{environmentId}/deployments` -> validate + deploy a
  `Deployment Revision` from a model config + inference config (FR-016, FR-019); explicit action,
  never implicit on config save
- `GET /environments/{environmentId}/deployments/{revisionId}` -> lifecycle, readiness, errors,
  active period (FR-017)
- `POST /environments/{environmentId}/prompts` -> submit an interactive prompt to the active ready
  deployment; rejected with `409` while a quality/performance run is active (Clarification 1,
  FR-052); response, timing, and active revision are returned but not persisted beyond the session
  (FR-060)

### Evaluation (User Story 3, User Story 4)

- `GET /golden-datasets` -> list registered `Golden Dataset` records (name, version, provenance,
  review status), backing the golden-dataset picker (User Story 8 Acceptance Scenario 2). **Not
  yet a first-class Fluent picker on the frontend** — `QualityRun.tsx` currently renders this list
  via a free-text `Input` + HTML `<datalist>` rather than a searchable Dropdown component; see
  spec.md User Story 8 Status.
- `GET /benchmark-definitions` -> list seeded `Benchmark Definition` records (id, version,
  presentation subset, pass/fail threshold). Read-only in v1 — there is no endpoint to update a
  benchmark's settings yet; see spec.md User Story 11 Status for that gap.
- `GET /performance-workloads` -> list registered `Performance Workload` definitions (name,
  description, concurrency), backing the performance-workload picker (User Story 8 Acceptance
  Scenario 3). **Not yet a first-class Fluent picker on the frontend** — same gap as golden
  datasets above, in `PerformanceRun.tsx`.
- `POST /environments/{environmentId}/runs` -> start an `Experiment Run` of type
  `quality-golden`, `quality-benchmark`, or `performance` against a golden dataset, benchmark
  definition, or performance workload id (FR-021, FR-023, FR-025); rejected with `409` if another
  run or interactive prompt is active on the same environment (Clarification 1)
- `GET /environments/{environmentId}/runs` -> list `Experiment Run` records for the environment
  (run id, type, test definition ref, status, started/ended); has no lifecycle gate, so it remains
  usable after teardown to satisfy User Story 6's retained-record access requirement (FR-061)
- `GET /environments/{environmentId}/runs/{runId}` -> status, diagnostics, partial results while
  running (FR-028, FR-029)
- `POST /environments/{environmentId}/runs/{runId}/cancel` -> idempotent cancellation; repeat
  calls do not duplicate cancellation records (FR-054)
- `GET /environments/{environmentId}/runs/{runId}/report` -> full `Result Report` (FR-024, FR-026,
  FR-027)

### Comparison (User Story 5)

- `POST /comparisons` -> build a `Comparison` from 2+ `Result Report` ids; returns
  `comparabilityStatus` and reasons when conditions diverge (FR-031, FR-032, FR-059)
- `GET /comparisons/{comparisonId}` -> retained comparison view

### Internal Orchestration Callback API (User Story 10)

Not part of the operator-facing surface: called only by the Durable Functions orchestration app and
Container Apps Jobs running inside `rg-llm-control-{stage}`, authenticated via managed identity
(Entra ID token audience-restricted to this API), never by a browser session. Used to keep FastAPI
as the sole writer of domain state while orchestration/execution happen outside the FastAPI process
(FR-076-FR-078).

- `POST /internal/workflows` -> FastAPI creates an `Orchestration Workflow` record and returns its
  `workflowId`/correlation ID immediately after acquiring the environment's single-writer lock
  (FR-052); this is what a Durable Functions orchestrator instance is started with.
- `PATCH /internal/workflows/{workflowId}` -> Durable Functions/Container Apps Jobs report phase,
  elapsed time, and progress diagnostics for an in-flight workflow (FR-049, FR-086); body MUST NOT
  contain a Hugging Face credential or interactive prompt/response body (FR-082/FR-084) — rejected
  with `400` if it does.
- `POST /internal/workflows/{workflowId}/complete` -> reports the terminal result (`ready`/
  `provisioning_failed`/`deployment_failed`/`teardown_failed`/etc. per the relevant entity's state
  machine in data-model.md); FastAPI writes the corresponding domain record(s) and releases the
  environment lock atomically in the same transaction. Completion first checks the
  current database lock owner under a row lock. If the workflow's operation no longer
  owns the environment (including an already-cleared lock), it returns
  `409 environment_locked` without changing the workflow, environment/revision state,
  or current lock. A late callback must never force-release another operation's lock.
  Dispatch-failure recovery uses the same ownership gate before changing environment
  or revision state; a missing/terminal workflow does not authorize fallback cleanup.
- `POST /internal/workflows/{workflowId}/cancel-ack` -> a Container Apps Job acknowledges an
  idempotent cancellation request propagated from `POST /environments/{environmentId}/runs/{runId}/
  cancel` (FR-054); repeat acknowledgements are no-ops.

**Contract rule**: every internal callback carries the same `workflowId` correlation ID the
workflow was created with, propagated end-to-end through Application Insights/Log Analytics
(FR-086); FastAPI rejects a callback whose `workflowId` does not match a workflow it created and is
still tracking as non-terminal.

## Error Shape

```json
{
  "requestId": "string",
  "error": {
    "code": "string",
    "message": "human-readable, actionable",
    "details": {}
  }
}
```
