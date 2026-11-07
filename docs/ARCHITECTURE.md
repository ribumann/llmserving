# Architecture map

This is the **implemented** architecture at public source baseline
`662f8b69a5c849e8b8d531f54965f7feaf27e805` (merged through PR #88), reviewed
2026-11-07. Diagrams describe source contracts, not a deployment attestation.
[Release evidence](RELEASE_VALIDATION.md) separately records observed execution.
The spec-kit artifacts retain broader design intent and are not a capability list.

## Choose a depth

| Depth | View | Questions answered |
| --- | --- | --- |
| 1: system context | [Context](architecture/CONTEXT.md#system-context) | Who uses the lab, which systems does it depend on, what stays public/private? |
| 2: runtime containers | [Containers](architecture/CONTEXT.md#runtime-containers) | Which processes run requests, jobs, inference and persistence? |
| 3: components | [UI, API and data lineage](architecture/COMPONENTS.md) | Where are auth, adapters, execution and immutable snapshots implemented? |
| Deployment and trust | [Azure topology and release path](architecture/DEPLOYMENT.md) | Which layers own resources, how do packages/state/identities cross boundaries? |
| Behavior over time | [Sequence flows](architecture/FLOWS.md) | What happens during public read, provisioning, deployment, inference, runs and cancellation? |
| Recovery detail | [State protocol](TERRAFORM_STATE.md), [data backup](DATA_AND_RECOVERY.md) | Which locks are distinct, when is retry unsafe, what must survive VM/API loss? |

Each diagram is intentionally small. Solid arrows are implemented interactions;
explicitly labeled optional/deferred paths are not live capabilities. The same
names are used throughout: **React UI / Nginx**, **FastAPI control plane**,
**PostgreSQL**, **Durable Functions**, **Terraform runner**, **Model job**,
**Private GPU VM / vLLM**, and **Local Ollama**.

## Non-negotiable boundaries

| Boundary | Implemented behavior |
| --- | --- |
| Anonymous browsing | Exact registered public GETs return allowlisted persisted projections. No provider calls, prompts, mutations or raw reports. |
| Operator access | Signed Entra user JWT and configured policy; frontend `/session` gating is UX, not server authorization. Local-demo is development-only. |
| Internal callback access | Separate managed-identity audience/tenant and exact allowed resource identities; no operator impersonation. |
| Long-running infrastructure | Durable Functions dispatches/monitors jobs; model job is pre-dispatched by the API to keep HF credentials out of Durable history. |
| Evaluation and performance | Backend thread-pool execution with saved snapshots/reports. Worker packaging is not API routing or durable lifecycle parity. |
| State ownership | DB environment lock and exclusive worker blob lease are distinct. Uncertain failed mutations retain the lease for private operator recovery. |
| GPU availability | Persisted READY is not VM allocation, model health or warmth. Spot is interruptible; policy denial cannot be bypassed. |
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
