# Extending the lab to AWS or GCP

[Docs index](README.md) / [current capabilities](PROVIDERS.md) /
[architecture](ARCHITECTURE.md)

**Roadmap, not implemented support.** The source registers only Azure and local
Ollama. Typed contracts and historical portability intent are extension seams,
not working AWS/GCP infrastructure. Implement one provider first; preserve
Azure/local behavior and keep unsupported choices explicit.

## High-level steps

1. **Define the target and contract.** Decide whether inference alone runs in the
   new cloud while the control plane remains Azure, or whether the full control
   plane moves. Implement `ProviderAdapter` lifecycle/state/teardown behavior and
   the actual route-facing methods used by `CompositeProviderAdapter`. Keep
   persisted environment, revision, run and report contracts compatible.
   Engine routing is a separate constraint: `get_engine_adapter()` currently
   sends `vllm` to Azure and `ollama` to local without resolving the environment's
   provider. Make that dispatch provider-aware (or deliberately map it) before
   a new cloud provider can serve vLLM; adding its lifecycle adapter alone is
   insufficient.
2. **Build honest preflight and ownership.** Map profiles to exact GPU instances,
   region/zone, quotas, Spot/preemptible vs on-demand policy and VRAM limits.
   Distinguish quota from allocation and power state from model warmth. Persist
   accepted target/scope and preview-token teardown consequences; never silently
   change cloud, SKU, region or cost.
3. **Provide identity and private infrastructure.** Add provider-specific
   Terraform modules for retained control/shared services and environment-scoped
   GPU resources. Use least-privilege workload federation, private inference/DB/
   secrets networking and exact ownership guards. Decide approved operator SSO
   separately from workload identity; do not translate Entra managed-identity
   claims into trust for arbitrary AWS/GCP tokens.
4. **Replace Azure-specific orchestration deliberately.** Implement job dispatch,
   monitor/stop, authenticated callbacks and artifact publication for the target.
   Choose to retain an Azure coordinator or use a cloud-native coordinator.
   Preserve bounded failures, duplicate/stale-owner handling and cooperative
   cancellation; keep model credentials out of workflow history/logs.
5. **Preserve durable state and runtime provenance.** Use private encrypted
   Terraform state with provider-appropriate locking, owned recovery capabilities
   and tested backup/restore. Azure Blob leases are not portable by renaming an
   endpoint. Deploy verified vLLM image/model digests on private GPU compute,
   with driver/bootstrap readiness and real health checks; replace Azure VM Run
   Command with the target's approved execution mechanism.
6. **Wire UI, configuration and evidence.** Register capabilities only after the
   implementation works; add provider profiles/config validation, catalog
   compatibility, public redaction and clear unsupported/error states. Preserve
   immutable snapshots and genuine golden/lm-eval/LLMPerf semantics. Quality/
   performance remain in-process unless durable worker lifecycle/report parity
   is separately completed.
7. **Test and release incrementally.** Add contract/mock-provider plan, identity
   negative, ownership/state recovery, cancellation, private-network and
   real-model API/browser tests. Obtain explicit target/budget approval before
   live cloud acceptance and demonstrate independent scoped cleanup.
   Deliver small reviewed PRs without weakening existing Azure/local gates.

## Platform decisions to resolve

These are candidate building blocks, **not chosen architectures or drop-in
equivalents**. Validate current provider behavior/limits during implementation.

| Concern | AWS candidates | GCP candidates |
| --- | --- | --- |
| GPU lifecycle and preflight | EC2 GPU instances, regional service quotas, Spot/on-demand capacity | Compute Engine GPU/machine/zone compatibility, quotas, Spot capacity |
| Jobs / orchestration | ECS tasks or another bounded executor; Step Functions if replacing Durable | Cloud Run Jobs or another bounded executor; Workflows if replacing Durable |
| Artifacts, secrets, state | ECR, Secrets Manager, private S3 state and supported locking | Artifact Registry, Secret Manager, private GCS state and supported locking |
| Workload auth and private access | IAM role federation and scoped VPC/endpoints | Workload Identity Federation and scoped VPC/private service access |
| Full control-plane migration | Select app hosting and managed PostgreSQL, then reverify auth, startup and persistence | Select app hosting and managed PostgreSQL, then reverify auth, startup and persistence |

Keeping PostgreSQL/FastAPI/React contracts is useful; service IAM, networking,
GPU bootstrapping, quotas and remote state are not generic adapters for free.
Public views must remain sanitized persisted GETs, never anonymous cloud actions.

## Coding-agent starter prompt

Copy this prompt and replace the bracketed target/scope. Do not include private
identities, endpoints, tokens or state. The first deliverable is a bounded plan,
not live resource creation.

```text
Extend ribumann/llmserving to [AWS or GCP], starting with [inference-only with
the existing control plane, or a full control-plane deployment].

Read CONTRIBUTING.md, docs/ARCHITECTURE.md, docs/PROVIDERS.md and
docs/PROVIDER_EXTENSION.md. Trace backend/src/providers/base.py, registry.py,
api/app.py and the route-facing Azure/local methods; inspect engine contracts,
infra modules, Functions/job dispatch and authenticated callback reconciliation.
Address get_engine_adapter's hardwired Azure-vLLM/local-Ollama dispatch as well
as lifecycle routing; adding a provider adapter alone does not make inference
provider-aware.

Produce a high-level implementation plan with small independently reviewed PRs.
Identify target-specific lifecycle/quota/capacity, ownership, workload identity,
operator auth, private networking/secrets, Terraform state/locking/backup/recovery,
artifact provenance, orchestration/stop/callbacks, GPU/vLLM bootstrap, profiles/UI
and contract/real-model tests. Preserve existing Azure/local APIs, immutable
configuration/report snapshots, public redaction and explicit unsupported errors.
Do not turn on durable evaluation or claim parity from worker packaging alone.

Keep new provider capabilities disabled until implemented and verified. Do not
provision resources, change cloud permissions, copy private config/state, bypass
policy or enable deployment workflows without explicit operator approval.
State unresolved platform choices and acceptance gates, then wait for plan
approval before implementation.
```

Source seams: [`ProviderAdapter`](../backend/src/providers/base.py),
[`registry`](../backend/src/providers/registry.py),
[`engine contract`](../backend/src/engines/base.py),
[`API composition`](../backend/src/api/app.py),
[`workflow reconciliation`](../backend/src/domain/workflow_reconciliation.py).
