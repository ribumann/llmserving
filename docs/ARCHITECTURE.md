# Architecture map

This is the **implemented** architecture at public main baseline
`b59f8d45218babd98d63f1b75b062957de957e51` (merged through PR #89), reviewed
2026-11-08. Diagrams describe source contracts, not a deployment attestation.
[Release evidence](RELEASE_VALIDATION.md) separately records observed execution.
The spec-kit artifacts retain broader design intent and are not a capability list.

## Learn the system, one level at a time

| --- | --- | --- |
Read this as a map, not a sequence of implementation tasks:

1. **C4 L1 — Context:** [who uses the lab, what it depends on, and where the
   system boundary ends](architecture/CONTEXT.md#c4-level-1-system-context).
2. **C4 L2 — Containers:** [which independently running applications and data
   stores collaborate](architecture/CONTEXT.md#c4-level-2-runtime-containers).
3. **C4 L3 — Components:** [what the UI, API and Functions containers contain
   and how their responsibilities fit together](architecture/COMPONENTS.md).
4. **C4 L4 — Code:** [a few source-level compositions worth tracing in detail:
   composition, identity, lifecycle, reconciliation and run persistence](architecture/CODE.md).

Then follow the [runtime storyboards](architecture/FLOWS.md) and
[deployment/trust model](architecture/DEPLOYMENT.md). Those are **dynamic and
deployment views**, respectively—not extra C4 levels. The
[data/recovery runbook](DATA_AND_RECOVERY.md) and
[Terraform state protocol](TERRAFORM_STATE.md) explain the dangerous edges in
more depth than one diagram can.

## How to read these diagrams

- **A boundary answers “what do we own?”** L1 draws one application as one box.
  At L2, expand only that system into running applications/stores. At L3, pick
  one container and expand its logical components. L4 zooms in only on a few
  real source modules/classes; it is not every file, and it is not a class
  diagram of the whole repository.
- **Names stay stable across levels.** A browser visitor uses the system; at
  L2, the visitor reaches **React UI / Nginx** and
  **FastAPI control plane**. At L3/L4 those are refined, not renamed. The
  operator, service identity, data store and external platform remain distinct.
- **An arrow means a relationship, not decoration.** Read its label for intent
  and its direction for the caller/dependency. A solid arrow denotes an
  implemented source path. A dashed arrow marks an alternative, cross-cutting,
  monitored or deliberately deferred relationship; its label says which. Labels
  such as “private” and “public” describe the intended trust path, not
  independently measured live network reachability.
- **Time is a different question.** A component diagram says who can call whom.
  A sequence diagram says what happens first, next and on failure. A deployment
  diagram says where something runs and how it is connected. Do not mix them up
  to infer durability, availability or rollout success.
- **Source links are the authority for implementation.** A diagram summarizes
  selected code; Terraform modules describe desired topology, not a resource
  inventory. See [dated release evidence](RELEASE_VALIDATION.md) before making
  claims about a deployed target.

### A guided trace

For a concrete first reading, start at
[Provision](architecture/FLOWS.md#provision-and-teardown), follow its route into
[`create_environment`](../backend/src/api/routes/environments.py) and the
[`AzureProviderAdapter`](../backend/src/providers/azure/adapter.py), then compare
the durable monitor and final database update in
[`generic_orchestrator_v2`](../functions/orchestrators/generic_orchestrator.py)
and [`WorkflowReconciliationService`](../backend/src/domain/workflow_reconciliation.py).
This trace teaches a useful distinction: **the job mutates Azure, the callback
reconciles persisted application state**. A VM existing in ARM does not by itself
mean the saved environment is ready.

## Non-negotiable boundaries

| Boundary | Implemented behavior |
| --- | --- |
| Anonymous browsing | Exact registered public GETs return allowlisted persisted projections. No provider calls, prompts, mutations or raw reports. |
| Operator access | Signed Entra user JWT and configured policy; frontend `/session` gating is UX, not server authorization. Local-demo is development-only. |
| Internal callback access | Separate managed-identity audience/tenant and exact allowed resource identities; no operator impersonation. |
| Long-running infrastructure | Durable Functions dispatches/monitors jobs; model job is pre-dispatched by the API to keep HF credentials out of Durable history. |
| Evaluation and performance | Backend thread-pool execution with saved snapshots/reports. Worker packaging is not API routing or durable lifecycle parity. |
| State ownership | DB environment lock and exclusive worker blob lease are distinct. Uncertain failed mutations retain the lease for private operator recovery. |
| GPU availability | Persisted READY is not VM allocation, model health or warmth. Spot is interruptible; Regular allocation was denied by subscription policy; no policy bypass is supported. |
| Provenance | Git SHA tags are mutable; registry manifest digests, Functions ZIP hash and exact model/config/test snapshots are separate evidence. |
| Resource lifetime | Shared/control persist. Retained demo groups are data-only and not teardown targets; child resources remain environment-scoped. |

## Source map

| Concern | Entry points |
| --- | --- |
| UI routing and public/operator split | [`App.tsx`](../frontend/src/App.tsx), [`PublicWorkspace.tsx`](../frontend/src/pages/PublicWorkspace.tsx), [`useOperatorSession.ts`](../frontend/src/services/useOperatorSession.ts) |
| HTTP composition and redaction | [`app.py`](../backend/src/api/app.py), [`auth.py`](../backend/src/api/auth.py), [`public.py`](../backend/src/api/routes/public.py), [`internal_auth.py`](../backend/src/api/internal_auth.py) |
| Azure orchestration | [`provision.py`](../backend/src/providers/azure/provision.py), [`deploy.py`](../backend/src/providers/azure/deploy.py), [`function_app.py`](../functions/function_app.py), [`workflow_reconciliation.py`](../backend/src/domain/workflow_reconciliation.py) |
| Execution and reports | [`runs.py`](../backend/src/api/routes/runs.py), [`run_quality.py`](../backend/src/evaluation/run_quality.py), [`llm_eval runner`](../backend/src/evaluation/lm_eval_runner.py), [`LLMPerf runner`](../backend/src/performance/llmperf_runner.py), [`result_report_repo.py`](../backend/src/domain/result_report_repo.py) |
| Inference | [`vLLM adapter`](../backend/src/engines/vllm/adapter.py), [`Ollama adapter`](../backend/src/engines/ollama/adapter.py), [`model job`](../jobs/model_deployment/entrypoint.py), [`cloud-init`](../infra/demo/cloud-init.tftpl) |
| Infrastructure and locking | [`infra guide`](../infra/README.md), [`environment_lock.py`](../backend/src/domain/environment_lock.py), [`terraform_runner`](../jobs/terraform_runner/entrypoint.py) |

For setup use [the docs index](README.md); for deliberate limitations use
[providers](PROVIDERS.md), [release evidence](RELEASE_VALIDATION.md) and
[operations](OPERATIONS.md). No diagram authorizes a cloud mutation.

## Glossary

| Term | Meaning here |
| --- | --- |
| **System** | The LLM Serving Demo application boundary and the behavior it owns. |
| **Container** | A separately running application or store (not necessarily a Docker image): SPA/web proxy, API process, Functions host, job execution, PostgreSQL, or storage. |
| **Component** | A logical responsibility inside one container, such as a route group, provider adapter or report repository. |
| **Code view** | A selective module/class/function relationship that helps follow one important implementation path. |
| **Environment** | Persisted application record and accepted provider scope for one local/cloud workload; not a synonym for a live VM. |
| **Revision** | One deployment configuration and its lifecycle/health record. |
| **Run** | One accepted golden, benchmark or performance execution, with frozen inputs and a result report. |
| **Workflow** | Durable Functions' monitor plus a job execution for supported infrastructure/model lifecycle work; distinct from an in-process quality/performance run. |
| **DB lock / Blob lease** | Separate single-writer mechanisms: the former protects an environment's API operation; the latter serializes cooperating Terraform worker state changes. |
