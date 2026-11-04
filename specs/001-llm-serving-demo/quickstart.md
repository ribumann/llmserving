# Quickstart: Validating the Azure LLM Serving Demo

**Input**: [spec.md](./spec.md) User Stories 1-6; [contracts/api.md](./contracts/api.md);
[data-model.md](./data-model.md)

This guide describes how to prove the feature works end-to-end. It is a validation/run guide, not
an implementation guide — implementation steps live in `tasks.md` (Phase 2, not yet generated).

## Prerequisites

- An Azure subscription with GPU quota in at least one eligible region (see `research.md` Section 4
  for recommended VM SKUs and regions: `Standard_NC16as_T4_v3`, `Standard_NC24ads_A100_v4`,
  `Standard_NC80adis_H100_v5`)
- Organization SSO configured for the web application via Microsoft Entra ID on Azure Container Apps
  (FR-001, FR-075)
- Hugging Face access token for any gated catalog entries the presenter intends to deploy
  (FR-011); never persisted beyond the active operation (FR-082/FR-083)
- Backend and frontend deployed as a single Container App in `rg-llm-control-{stage}` (shared
  `infra/shared/` + `infra/control/` control plane — see `plan.md` Target Platform), reachable at its
  HTTPS ingress URL; or running locally for iterative development, pointed at PostgreSQL
  (`research.md` Section 5b)
- The Azure Durable Functions app and Container Apps Job definitions deployed in
  `rg-llm-control-{stage}` (FR-077/FR-078), required for any Scenario below that provisions,
  deploys, evaluates, or tears down against the Azure provider (Scenario 7's local/Ollama path does
  not require them)

## Scenario 1: Provision a Demo Environment (User Story 1)

1. Sign in to the operator web app via organization SSO.
2. Select a validated profile (3B, 7B, or 70B class).
3. Call/click "Preview" — expect a recommended region with evidence, timestamp, and an
   uncertainty note (FR-039).
4. Confirm provisioning — expect visible progress, then a final `ready` state or an actionable
   failure (FR-008).
5. **Expected outcome**: `GET /environments/{id}` shows profile, resource state, deployment
   history (initially empty), and capacity context (FR-017).

## Scenario 2: Deploy and Exercise One Model (User Story 2)

1. From the ready environment, select a catalog entry compatible with the provisioned profile.
2. Create a model configuration and an inference configuration (defaults visible per FR-013).
3. Trigger deployment — expect progress, then `ready` only once the engine's health check passes.
4. Submit a prompt — expect a response, timing summary, and the active deployment revision id
   (FR-018).
5. **Expected outcome**: changing the model or inference configuration creates a new version and
   requires an explicit redeploy before it takes effect (FR-019).

## Scenario 3: Evaluate Quality (User Story 3)

1. Start a golden-dataset run against the ready deployment.
2. Start a standard-benchmark run (GSM8K, IFEval, or the MMLU 5-subject mini anchor benchmark —
   `research.md` Section 3).
3. **Expected outcome**: every declared case resolves to passed/failed/errored/skipped/incomplete,
   each judged against its documented pass/fail threshold (FR-024, FR-056), with an aggregate
   summary and any AI-generated golden cases showing provenance and review status (FR-022).

## Scenario 4: Measure Serving Performance (User Story 4)

1. Start a performance run using a defined workload (warm-up, concurrency, duration/request
   count, safety limits).
2. **Expected outcome**: the report includes TTFT, inter-token latency, end-to-end latency, and
   throughput, each with p50 and p95 (FR-057), plus failures and accelerator utilization when
   available, all with units and test conditions (FR-026, FR-027).
3. Cancel a run mid-flight, then cancel it again immediately — expect idempotent handling with no
   duplicate cancellation record (FR-054).

## Scenario 5: Retune, Redeploy, and Compare (User Story 5)

1. Change the inference configuration and redeploy.
2. Re-run the same golden dataset, benchmark, and performance workload used in Scenarios 3-4.
3. Build a comparison from both sets of results.
4. **Expected outcome**: the prior deployment revision and its results remain immutable and
   linked (FR-030); the comparison shows configuration/quality/performance/failure/utilization
   deltas (FR-031); if conditions materially differ, the comparison is labeled
   "not directly comparable" with reasons, while still showing underlying metrics (FR-032,
   FR-059).

## Scenario 6: Tear Down Safely (User Story 6)

1. Request teardown — expect a resource preview and consequences before any destructive action
   (FR-033).
2. Confirm teardown — expect a report of every resource as removed, retained, or failed (FR-034).
3. **Expected outcome**: persisted experiment records (golden/benchmark/performance runs, per
   FR-061) remain accessible or exportable after the environment is gone; any ad hoc interactive
   prompts from the session are not present, per FR-060.

## Scenario 7: Test and Demo Locally Without Cloud GPU (User Story 7)

1. Install Ollama locally and select the "Local (Ollama)" provider when provisioning — expect the
   environment to become ready with no Azure credentials, quota check, or region selection
   (FR-065).
2. Deploy the small Qwen checkpoint marked compatible with the local profile — expect Ollama to
   pull the checkpoint automatically if it is not already present, with progress/failure reported
   through the same deployment states as the Azure path (FR-066, FR-068).
3. Submit a prompt, run a quality check, and run a performance workload against the local
   deployment — expect the same report shapes as the Azure path.
4. **Expected outcome**: results are labeled "not directly comparable" to any Azure-hosted result
   (FR-070, FR-059); if Ollama is not installed/reachable or the checkpoint pull fails, the system
   reports the specific blocking condition and remediation guidance instead of marking the
   environment or deployment ready (FR-069).

## Scenario 8: Validate the Baseline Pilot Architecture Topology (User Story 10)

1. Sign in to the operator web app; confirm the request reaches the app through Azure Container
   Apps' built-in HTTPS ingress with Entra ID SSO and that no Application Gateway, Azure Front Door,
   or Azure Firewall exists in the deployed topology (FR-075, SC-018).
2. Start a provisioning operation, then immediately attempt a second conflicting operation (e.g. a
   teardown) against the same environment — expect an immediate `409 Conflict`, not a queued request
   (FR-052, FR-083, User Story 10 Acceptance Scenario 2).
3. Inspect the running provisioning workflow — expect FastAPI to show phase/elapsed time sourced from
   an Azure Durable Functions orchestrator, and confirm (via Azure Portal/CLI, non-normative) that the
   Terraform apply itself executed inside a Container Apps Job, not inside FastAPI or the Functions
   host process (FR-077, FR-078).
4. Inspect the resource groups created — expect exactly `rg-llm-shared-{stage}`,
   `rg-llm-control-{stage}`, and one `rg-llm-demo-{environmentId}` per provisioned environment, with
   no per-component resource groups beyond these three (FR-074).
5. Inspect the deployed GPU VM's networking — expect no public IP, and confirm the vLLM port is
   reachable only from `snet-containerapps` (FR-079, SC-018).
6. Deploy a gated checkpoint using a presenter-supplied Hugging Face token, then search PostgreSQL,
   Terraform state/plan output, Durable Functions history, application logs, and traces for that
   token value — expect zero matches (FR-082, SC-019).
7. Tear down the demo environment — expect only `rg-llm-demo-{environmentId}` to be removed; confirm
   `rg-llm-shared-{stage}` and `rg-llm-control-{stage}` remain intact and that previously persisted
   experiment records for that environment are still retrievable (FR-080, FR-090, SC-017).
8. **Expected outcome**: every check above passes without any deviation requiring a documented
   exception; if Application Gateway/Front Door/Firewall/Bastion/public GPU IP are found, or a
   teardown removes more than the disposable resource group, the architecture validation fails and
   must be corrected before the pilot is considered complete.

> Automated coverage: items 2 and 3 (conflict handling and orchestration phase/elapsed reporting)
> are covered by `e2e/tests/architecture-topology.spec.ts`. Items 1, 4, 5, 6, and 7 (ingress
> topology, resource-group boundaries, GPU VM networking, HF-token leakage, and teardown scope)
> require inspecting real deployed Azure resources and are covered by
> `scripts/validate-architecture-topology.ps1`, which should be run against a live demo environment
> after deployment.

## Cross-Cutting Checks

- **Concurrency (FR-052, SC-012)**: attempt two conflicting operations (e.g., a performance run
  and an interactive prompt) against the same environment at once — the second MUST be rejected
  with an actionable `409`, not queued or silently dropped.
- **No auto-retry (FR-055)**: force a provisioning failure — confirm the environment stays in
  `provisioning_failed` until a user explicitly retries.
- **Reference execution profile (FR-058, SC-002)**: run the full workflow (Scenarios 1-6) under
  the documented reference profile and confirm total elapsed time and per-phase durations are
  visible, whether or not the 60-minute target is met.
- **Audit trail (FR-004)**: confirm every configuration-changing or destructive action in the
  scenarios above recorded the acting SSO identity.
