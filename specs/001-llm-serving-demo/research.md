# Phase 0 Research: Azure LLM Serving Demo

**Input**: Technical Context `NEEDS CLARIFICATION` markers in [plan.md](./plan.md); research gates
FR-038 through FR-045, FR-047, FR-051, FR-063, FR-064 in [spec.md](./spec.md).

**Date**: 2026-08-19

This document resolves every open technology decision required before Phase 1 design. Each
section follows the Decision / Rationale / Alternatives Considered format.

---

## 1. Inference Serving Engine (FR-041, FR-042)

### Decision
**vLLM** (Apache 2.0), served via the official `vllm/vllm-openai` Docker image, exposing the
OpenAI-compatible `/v1/chat/completions` and `/v1/completions` endpoints.

### Rationale
- Fully reproducible: serving config is declared via CLI flags/YAML and a pinned, versioned
  Docker image — no compiled per-model artifacts to manage (satisfies Constitution Principle I).
- Native `/metrics` Prometheus endpoint (TTFT, TPOT, KV-cache hit rate, queue depth, throughput)
  and a `/health` endpoint out of the box, with zero additional plumbing (Principle III).
- OpenAI-compatible HTTP surface makes the internal `EngineAdapter` interface
  (`contracts/engine-interface.md`) thin, and is a near-drop-in target for a second adapter later
  (Principle V — simplicity, without over-building).
- Broadest model support of the candidates evaluated (200+ HF architectures, explicit
  Gemma/Llama/Qwen/DeepSeek coverage) and native quantization support (AWQ, GPTQ, FP8, INT4,
  GGUF) needed for the 70B-class catalog slot on a single GPU.
- Best Azure ecosystem maturity of the candidates: official AKS (KAITO operator) and AzureML
  managed-endpoint guides, plus Azure Marketplace GPU VM images preconfigured with vLLM.
- Industry-leading adoption (~89k GitHub stars, PyTorch Foundation governance, weekly releases)
  reduces the risk of choosing an engine that stalls mid-project.

### Alternatives Considered
| Framework | Why not selected first |
|---|---|
| **SGLang** | Narrowly out-performs vLLM on raw throughput/TTFT and shares the same Apache 2.0 + OpenAI-compat shape, but has no official AzureML/AKS integration yet and carries governance uncertainty as a commercial (RadixArk) spinout. Best candidate for a **second** engine adapter later. |
| **Hugging Face TGI** | Entered maintenance mode in December 2025; HuggingFace's own docs now recommend vLLM/SGLang for new deployments. Selecting it would create immediate technical debt. |
| **NVIDIA Triton + TensorRT-LLM** | Best raw performance on NVIDIA hardware, but the mandatory model/GPU/batch-size-specific engine-build step violates the reproducibility and simplicity principles, and deployment complexity is 3-5x higher than vLLM. gRPC-first API also makes the adapter interface heavier. |
| **llama.cpp / Ollama** | Simplest possible single-VM setup, but lacks native Prometheus metrics (Ollama has none; llama.cpp's are recent/partial), has a materially lower throughput ceiling, and is not production-metrics-grade — conflicts with FR-026/FR-057's percentile reporting requirements. |

---

## 2. Model Catalog (FR-043, FR-044)

### Decision
A 9-checkpoint catalog spanning 3 families x 3 size classes, all Hugging Face hosted:

| Slot | Family | Size class | Hugging Face repo | License | Gated | Notes |
|---|---|---|---|---|---|---|
| S1 | Gemma 3 | Small (~4B) | `google/gemma-3-4b-it` | Gemma ToS | Yes | Instruction-tuned; multimodal (text+image) |
| S2 | Gemma 3 | Medium (~12B) | `google/gemma-3-12b-it` | Gemma ToS | Yes | Gemma 3 has no 7B checkpoint; 12B fills the medium slot |
| S3 | Gemma 3 | Large (~27B) | `google/gemma-3-27b-it` | Gemma ToS | Yes | Largest Gemma checkpoint (no Gemma 70B exists); quantize for demo stability |
| S4 | Llama 3.x | Small (~3B) | `meta-llama/Llama-3.2-3B-Instruct` | Llama Community License | Yes | Edge/on-device framing |
| S5 | Llama 3.x | Medium (~8B) | `meta-llama/Llama-3.1-8B-Instruct` | Llama Community License | Yes | Quality/cost workhorse |
| S6 | Llama 3.x | Large (~70B) | `meta-llama/Llama-3.3-70B-Instruct` | Llama Community License | Yes | Flagship demo slot; requires quantization on a single GPU |
| S7 | Qwen (Chinese-origin) | Small (~4B) | `Qwen/Qwen3-4B` | Apache 2.0 | No | Only ungated family in the catalog |
| S8 | Qwen (Chinese-origin) | Medium (~8B) | `Qwen/Qwen3-8B` | Apache 2.0 | No | Hybrid thinking mode; 119-language training |
| S9 | Qwen (Chinese-origin) | Large (~32B) | `Qwen/Qwen3-32B` | Apache 2.0 | No | Preferred over `Qwen/Qwen2.5-72B-Instruct` (gated, requires quantization) for operational simplicity; fits BF16 on an 80 GB GPU without quantization |

**Quantization for the large tier**: INT4 AWQ is the confirmed path for single-GPU hosting of the
70B-class slots that need it.

| Model | BF16 footprint | Quantized reference | Quantized footprint |
|---|---|---|---|
| Llama 3.3-70B-Instruct | ~140 GB | `casperhansen/llama-3.3-70b-instruct-awq` (or vLLM `--quantization awq` at serve time) | ~35-40 GB |
| Gemma 3-27B-it | ~54 GB | Google official QAT checkpoint (preferred) or `RedHatAI/gemma-3-27b-it-quantized.w4a16` | ~14-18 GB |
| Qwen2.5-72B-Instruct (deferred, see below) | ~144 GB | `Qwen/Qwen2.5-72B-Instruct-AWQ` | ~36-40 GB |

### Rationale
- Covers all three required model families (Gemma, Llama, Chinese-origin) across all three
  required size classes (FR-043), using officially published instruction-tuned checkpoints.
- Documents licensing and gating per FR-044: all Gemma and Llama checkpoints (plus the
  Qwen2.5-72B alternative) require Hugging Face gated-repo acceptance; only the Qwen3 small/medium
  checkpoints are fully open (Apache 2.0, ungated) — this is called out explicitly because it has
  operational implications for the provisioning workflow (HF token handling, FR-011).
- `Qwen/Qwen3-32B` is preferred over `Qwen/Qwen2.5-72B-Instruct` for the Qwen "large" slot because
  it needs no quantization on an 80 GB single-GPU SKU, is ungated, and is the more current model
  generation — trading raw parameter count for deployment simplicity, consistent with Constitution
  Principle V.

### Alternatives Considered
- **Qwen2.5-72B-Instruct** as the Qwen large slot: higher parameter count for narrative parity
  with the Llama 70B slot, but gated, requires INT4 quantization, and is an older model
  generation. Documented here as an available substitute if 70B-class parity is preferred over
  operational simplicity; not the v1 default.
- **Gemma at a "true 70B" tier**: no such checkpoint exists in the Gemma 3 family (ceiling is 27B);
  accepted as a structural gap rather than substituting an out-of-family checkpoint.

---

## 3. Quality Benchmarks & Evaluation/Test Framework (FR-045, FR-063, FR-064)

### Decision — Benchmarks
Three benchmarks, all with deterministic (non-LLM-judge) scoring:

1. **GSM8K** (primary reasoning benchmark) — grade-school math word problems, regex-extracted
   numeric answers, MIT license, excellent spread across all three size classes (3B ~55%, 7B
   ~75%, 70B ~92%) and all three model families.
2. **IFEval** (primary instruction-following benchmark) — programmatic/structural constraint
   checking (word count, format, language, keyword exclusion), Apache 2.0, low contamination
   risk, excellent differentiation between instruction-tuned variants.
3. **MMLU, 5-subject mini** (anchor benchmark) — the most widely recognized benchmark in vendor
   datasheets; included at reduced scope (50 questions across 5 subjects) purely for audience
   familiarity, explicitly labeled in-product as a reference benchmark rather than a primary
   quality signal given known contamination risk at this benchmark's scale.

Each benchmark uses a fixed, documented random sample (N=50-54) from its public test split with a
fixed seed, and a >5 percentage-point drop from a documented baseline is the default regression
flag threshold (tunable per FR-056).

### Decision — Evaluation/Test Framework
**`lm-evaluation-harness`** (EleutherAI, MIT license) for quality benchmark execution (GSM8K,
IFEval, MMLU, and custom golden-dataset YAML tasks), targeting the deployed engine's
OpenAI-compatible endpoint via its `local-completions` backend.

**`LLMPerf`** (Ray project, Apache 2.0) as the primary performance/load-testing tool, with the
**vLLM benchmark CLI** (`vllm bench serve`) available as a vLLM-native secondary tool for
authoritative TTFT/ITL numbers.

### Rationale
- `lm-evaluation-harness` has native, tested task implementations for all three selected
  benchmarks — zero bespoke scoring infrastructure required, directly satisfying FR-064's
  constraint that the chosen framework must not require building custom scoring infra.
- Its `local-completions` backend targets any OpenAI-compatible endpoint with no modification,
  which is exactly what the vLLM adapter exposes (FR-056/FR-057 satisfied without extra glue).
  Custom golden datasets (FR-021-024) are added as YAML task configs against local JSONL data,
  reusing the same harness rather than a second tool.
- Results are directly comparable to published baselines because `lm-evaluation-harness` is the
  engine behind the widely referenced HuggingFace Open LLM Leaderboard.
- `LLMPerf` is backend-agnostic (via LiteLLM), so it keeps working if the engine adapter is ever
  swapped, and natively reports the p50/p95 TTFT/inter-token/end-to-end/throughput metrics
  required by FR-026/FR-057. The vLLM CLI is kept available as a secondary, vLLM-authoritative
  cross-check since v1's engine choice is vLLM.

### Alternatives Considered
| Tool | Why not selected as primary |
|---|---|
| **promptfoo** | Excellent for custom golden-dataset regression, but has no built-in academic benchmark tasks (GSM8K/IFEval/MMLU); would require rebuilding what `lm-evaluation-harness` already ships. Could be revisited later for red-teaming/prompt-regression scenarios outside v1 scope. |
| **DeepEval** | Focused on RAG/chatbot LLM-as-judge metrics, not standard academic benchmarks; would add an LLM-judge dependency the deterministic-scoring requirement doesn't need. |
| **OpenAI Evals / Ragas** | OpenAI Evals is tightly coupled to the OpenAI API (poor fit for a self-hosted endpoint); Ragas is RAG-pipeline-specific and out of scope. |
| **NVIDIA AIPerf / GenAI-Perf** | GenAI-Perf is explicitly deprecated (superseded by AIPerf). AIPerf is a strong option if the engine were Triton/CUDA-based with a dashboard requirement, but adds setup overhead not justified given the vLLM engine decision above. |
| **k6 / Locust** | General-purpose HTTP load testers; would require building TTFT/ITL-aware instrumentation from scratch that LLMPerf already provides. |
| **HellaSwag, TruthfulQA, ARC-Challenge, HumanEval** (benchmarks) | HellaSwag/ARC-Challenge are approaching saturation at the 70B tier, reducing their ability to surface regressions. TruthfulQA is non-monotone (bigger models can score lower), which is confusing for a live non-expert audience. HumanEval requires a code-execution sandbox, adding infrastructure not justified for v1. All four remain viable future additions if a specific need arises (e.g., a developer-focused demo audience for HumanEval). |

---

## 4. Azure GPU Capacity & VM SKUs (FR-038, FR-039, FR-040)

### Decision — VM SKUs by size class
| Size class | Recommended SKU | GPU | VRAM | Notes |
|---|---|---|---|---|
| 3B / 7B tier | `Standard_NC16as_T4_v3` | 1x NVIDIA T4 | 16 GB | Budget alternative: `Standard_NC4as_T4_v3`; no quantization needed at these sizes |
| 27B tier (Gemma large slot) | `Standard_NC24ads_A100_v4` | 1x A100 PCIe | 80 GB | Fits Gemma 3-27B in BF16 with modest KV-cache headroom; quantized checkpoint recommended for demo stability at long context |
| 70B tier (Llama/Qwen large slots) | `Standard_NC80adis_H100_v5` | 2x H100 NVL | 188 GB aggregate | Microsoft's actively-invested current NC generation; fits a 70B model in FP16 across both GPUs, or INT4/AWQ on a single GPU for maximum throughput per dollar |

`Standard_NC_A100_v4` family is explicitly noted by Microsoft as no longer receiving net-new
capacity investment (superseded by `NCads_H100_v5`); it remains usable where already available
but is not the default recommendation for new deployments.

### Decision — Quota/capacity preflight
A three-step preflight sequence, since Azure exposes no API that reliably predicts whether a GPU
VM deployment will succeed before attempting it:

1. **Quota check** (fast, free): `GET .../providers/Microsoft.Compute/locations/{region}/usages`
   — confirms subscription-level vCPU allowance for the target GPU family; surface a
   quota-increase link and suggest an alternate region if `limit == 0`.
2. **SKU availability check** (fast, free): `GET .../providers/Microsoft.Compute/skus?$filter=location eq '{region}'`
   — confirms the target SKU is not restricted for the subscription in that region.
3. **Deployment attempt** (definitive capacity signal): an `AllocationFailed` error is the only
   ground-truth signal that physical capacity is unavailable; on failure, suggest retry in the
   same region, an alternate availability zone, an alternate region (from a documented fallback
   order: `eastus2` -> `southcentralus` -> `westus3` -> `westeurope` -> `northeurope`), a smaller
   SKU, or applying quantization to fit a smaller SKU.

### Rationale
This directly implements FR-038 through FR-040's requirement for automated preflight plus
actionable guidance on failure, while being explicit (FR-039 caveat) that quota and physical
capacity are independent and capacity cannot be predicted in advance. The recommended user-facing
language is: *"llmserving checks your quota before deploying, but Azure GPU capacity is
subscription- and time-dependent and cannot be guaranteed in advance. If deployment fails with
AllocationFailed, the tool will suggest alternate regions or SKUs."*

### Alternatives Considered
- **Azure On-Demand Capacity Reservation** as a pre-deployment capacity probe: technically
  possible but holds cost while active; not adopted as the default preflight step, documented as
  an optional escalation path for repeated allocation failures.
- **`Standard_ND96asr_A100_v4`** (8x A100 40 GB, HPC/InfiniBand-oriented): valid alternative for
  the 70B tier but designed for scale-out training, materially higher cost, and harder to obtain
  allocation for — rejected in favor of `NC80adis_H100_v5`.

---

## 5. Backend Language/Runtime, Storage Product, and Testing Tooling

These three Technical Context items are cross-cutting engineering decisions rather than
spec-mandated research gates, but must be resolved before Phase 1 design so the plan no longer
carries `NEEDS CLARIFICATION` markers.

### 5a. Language/Runtime — Decision: Python 3.11+ (backend), TypeScript/React (frontend)

**Rationale**: Every Phase 0 tooling decision above (`vllm`, `lm_eval`, `LLMPerf`) is a Python
library/CLI; a Python backend lets the API layer invoke these directly (in-process or via a job
queue) without a cross-language shim. Python 3.11+ is required by current `lm_eval[api]` and
`vllm` client dependencies. FastAPI is the specific web framework (async-first, OpenAPI schema
generation for `contracts/api.md`, first-class background-task support for the long-running
provisioning/evaluation operations described in FR-052/FR-053). The frontend uses TypeScript with
React, matching the "web UI framework for the operator application" dependency already noted in
Technical Context and keeping the presenter-facing flows (FR-035) in a widely supported,
strongly-typed stack.

**Alternatives considered**: A single-language Node/TypeScript stack was considered to avoid a
polyglot repo, but would require re-implementing or subprocess-wrapping every evaluation/serving
tool above, adding integration risk without a corresponding benefit.

### 5b. Storage — Decision: PostgreSQL (relational), not a document database

**Rationale**: Phase 1 data modeling (`data-model.md`) shows the domain entities (Cloud
Deployment Profile, Demo Environment, Model Catalog Entry, Model/Inference Configuration,
Deployment Revision, Golden Dataset, Benchmark Definition, Performance Workload, Experiment Run,
Result Report, Comparison) are naturally relational — they have clear foreign-key relationships,
state transitions, and audit/versioning requirements (FR-004, FR-012, FR-013, FR-019, FR-020) that
map cleanly to normalized tables with JSONB columns for the genuinely variable parts (model
config key/value pairs, per-operation event-log payloads per FR-062). This is why Technical
Context's original "portable document database" framing is revised to "portable relational
database" here. PostgreSQL satisfies the FR-047 portability constraint: it is available as a
first-party managed offering on Azure (Azure Database for PostgreSQL Flexible Server) and on at
least one other major cloud (Amazon RDS for PostgreSQL, Google Cloud SQL for PostgreSQL), plus it
runs identically in a self-hosted container for local development — so persistence is not
Azure-locked even though only the Azure provider is implemented in v1.

**Alternatives considered**: A document database (e.g., MongoDB / Azure Cosmos DB for MongoDB)
was the original placeholder assumption in Technical Context; rejected once the entity model
proved to be relationally shaped, since a document store would push referential-integrity and
join-like queries (e.g., "all experiment runs for a deployment revision") into application code
for no benefit here. SQLite was considered for local-only development simplicity but rejected as
the primary product because it cannot satisfy the FR-047 "reachable from a managed cloud offering"
portability requirement on its own.

### 5c. Testing Tooling — Decision: pytest + Playwright + Vitest/RTL

- **Backend unit/integration/contract tests**: `pytest`, with `pytest-asyncio` for the FastAPI
  async endpoints and contract tests that validate `contracts/api.md`, `contracts/provider-
  interface.md`, and `contracts/engine-interface.md` against fake/mock implementations.
- **Frontend unit tests**: `Vitest` + `React Testing Library`, matching the TypeScript/React
  frontend decision above.
- **End-to-end / quickstart validation**: `Playwright`, used to drive the six `quickstart.md`
  scenarios (and the cross-cutting single-writer/no-auto-retry/audit-trail checks) against a real
  or containerized backend, satisfying the constitution's Reliable and Observable Inference
  principle by exercising full request/response flows, not just unit boundaries.

**Rationale**: All three tools are the current de facto standard for their respective language
ecosystem, require no bespoke test-runner infrastructure, and directly support the contract-test
and end-to-end-flow requirements called out in Technical Context's original placeholder.

**Alternatives considered**: `unittest` (Python stdlib) was considered but rejected in favor of
`pytest`'s fixture/parametrization ergonomics, which reduce boilerplate for the many
configuration-validation test cases FR-019/FR-020 imply. `Cypress` was considered instead of
Playwright but Playwright's native multi-browser support and first-class Python/TypeScript client
parity (useful since the backend is Python and the frontend is TypeScript) was preferred.

---

## 6. Infrastructure-as-Code Language (FR-005, FR-051)

### Decision
**Terraform** (HashiCorp Configuration Language, using the `azurerm` provider), not Azure Bicep.

### Rationale
Per explicit user direction, the infrastructure deployment language must remain portable across
clouds even though only the Azure provider is implemented in v1 (mirroring the FR-037
single-provider-interface pattern, and the FR-047 portable-storage requirement above). Terraform's
HCL is cloud-agnostic — the same tool, state model, module structure, and CLI workflow apply
whether the provider block targets `azurerm`, `aws`, or `google`. Azure Bicep, by contrast,
compiles to ARM templates and only ever targets Azure; choosing it would tie the IaC *language*
itself to Azure, not just the current provider implementation. Terraform's `azurerm` provider is
mature and fully supports GPU VM provisioning (`azurerm_linux_virtual_machine` with the SKUs from
Section 4), custom script extensions for driver installation, and managed disk attachment. Neither
tool provides built-in quota/capacity pre-checks; those remain a separate preflight step (Section
4) implemented in the backend, invoked before the Terraform apply.

### Alternatives Considered
- **Azure Bicep**: simpler for an Azure-only shop (no state-file management, first-class Azure
  CLI integration), but the compiled ARM template output and toolchain are Azure-specific by
  design — rejected specifically because the user asked for infra language portability across
  clouds, and a future second-provider adapter (FR-037's stated extension point) would otherwise
  require a full IaC rewrite rather than a new Terraform module.
- **Pulumi**: also cross-cloud and would allow using the same Python language as the backend, but
  has a smaller community/adoption footprint for Azure GPU VM scenarios than Terraform's mature
  `azurerm` provider, and was not the user's stated preference; documented as a viable alternative
  if the team later prefers a single-language (Python) IaC story over Terraform's HCL.

---

## 7. Baseline Pilot Hosting & Orchestration Architecture (User Story 10, FR-074-FR-090)

### Decision — Application hosting: Azure Container Apps, not Azure App Service

Azure Container Apps replaces Azure App Service for Containers as the host for the React + FastAPI
operator application. Container Apps provides built-in HTTPS ingress and can be configured for
Microsoft Entra ID authentication directly, without a separately provisioned Application Gateway or
Front Door (FR-075). It also natively supports **Container Apps Jobs** in the same environment,
which removes the need for a second compute product just to run isolated, short-lived workloads
(Terraform applies, evaluation runs, performance runs, exports — FR-078).

### Decision — Long-running-workflow coordination: Azure Durable Functions, not ad hoc background
tasks in FastAPI

Provisioning, deployment, evaluation, performance testing, export, cancellation, and teardown are
all long-running, multi-step, resumable operations. Durable Functions' orchestrator-function model
gives replay-safe state, built-in status/terminal-state querying, and built-in cancellation
signaling, without building a bespoke saga/state-machine layer inside FastAPI. Keeping this
coordination in a separate Functions app — rather than a background-task mechanism inside the
FastAPI process — enforces the architectural boundary in FR-076/FR-077: FastAPI remains the sole
system-of-record for domain state and API contracts; Durable Functions never gains a public API or
domain database access of its own.

### Decision — Isolated execution: Azure Container Apps Jobs, not long-running processes inside
Durable Functions or FastAPI

Terraform applies, model deployment, `lm-evaluation-harness` runs, LLMPerf/vLLM benchmark runs, and
exports are resource-heavy, potentially long-running, and need process isolation (a stuck or crashed
job must not affect FastAPI or the orchestrator). Container Apps Jobs give each of these its own
container image, resource limits, and execution lifecycle, dispatched by the relevant Durable
Functions orchestrator and reporting results back to FastAPI's internal callback API (FR-078,
FR-086). This is also the isolation boundary that keeps a presenter-supplied Hugging Face credential
scoped to exactly the one job process that needs it, in memory only, for exactly the duration of
that operation (FR-082/FR-083) — it is never written to the orchestrator's replay history or any
durable store.

### Decision — Resource-group topology: three boundaries (shared/control/demo), not one flat
resource group per environment or per component

The three-resource-group split (`rg-llm-shared-{stage}`, `rg-llm-control-{stage}`,
`rg-llm-demo-{environmentId}`, FR-074) replaces the earlier layout that had grown to include a
separate resource group for the database, one for the app host, and one per demo environment. The
guiding principle: group resources by **retention lifecycle**, not by which team or component owns
them. Shared network/platform primitives (VNet, DNS, NAT, ACR, Key Vault, monitoring) rarely change
and are never destroyed except deliberately (`rg-llm-shared-{stage}`). The application control plane
(Container Apps, Durable Functions, PostgreSQL, Storage) is also retained but evolves with app
releases (`rg-llm-control-{stage}`). Only the GPU VM — the expensive, genuinely disposable resource —
lives in its own resource group per environment, so `terraform destroy` there can never reach into
shared or control-plane state (FR-090), and a teardown failure or partial apply in one environment
cannot affect another.

### Decision — GPU network exposure: private-only, reachable from the Container Apps subnet

The GPU VM's NIC lives on `snet-gpu` with no public IP; its NSG allows the vLLM port only from
`snet-containerapps` (FR-079). This removes the previous public-IP-plus-source-CIDR-allowlist model
and its `enable_bastion`/SSH jump-host path entirely — Container Apps Jobs (running inside the same
VNet as `snet-containerapps`, or with the equivalent private connectivity) reach the GPU VM over the
private network, and there is no operator SSH path required for normal operation (per the
requirement not to add Bastion unless proven necessary).

### Decision — Secret handling: Key Vault for platform secrets, in-memory-only for presenter
credentials

Key Vault (`rg-llm-shared-{stage}`) holds the PostgreSQL connection string/admin credentials and any
other durable application/platform secret, referenced by the Container App and Functions app via
managed identity — removing the earlier pattern of a plaintext `DATABASE_URL` app setting whose
loss forced a password reset to recover DB access. Presenter-supplied Hugging Face credentials are
explicitly **not** stored in Key Vault (or anywhere durable): they are passed directly into the one
Container Apps Job process that needs them and exist only in that process's memory for the
operation's duration (FR-082/FR-083).

### Alternatives Considered
- **Keep Azure App Service + a Service Bus/queue-based worker model** instead of Durable
  Functions + Container Apps Jobs: rejected because it would require hand-rolling the
  orchestration state machine (retries, cancellation, phase tracking) that Durable Functions
  provides out of the box, and still wouldn't give the same per-job process isolation Container
  Apps Jobs provide for credential scoping.
- **Azure Kubernetes Service (AKS)** for both hosting and job execution: rejected as disproportionate
  operational overhead for a pilot-scale demo (cluster lifecycle, node pool management) when
  Container Apps already provides the managed-ingress + Jobs combination needed.
  Application Gateway + Azure Firewall + Bastion perimeter: rejected per the explicit requirement
  not to add these unless an existing requirement proves them necessary — Container Apps' built-in
  HTTPS ingress + Entra ID satisfies FR-001/FR-075 without them, and the GPU VM's private-only
  design (FR-079) removes the need for a jump host.
- **One resource group per component (network/db/app-host/functions/jobs)**: rejected as the
  fragmentation this refactor is explicitly correcting — more resource groups to reason about and
  tear down in the right order, with no corresponding benefit once resources are grouped by
  retention lifecycle instead.

---

## Summary of Resolved Technical Context

| Item | Resolved value |
|---|---|
| Language/Version | Python 3.11+ (backend, FastAPI); TypeScript + React (frontend) |
| Inference engine | vLLM (`vllm/vllm-openai`), OpenAI-compatible API |
| Evaluation/test framework | `lm-evaluation-harness` (quality) + `LLMPerf` / vLLM benchmark CLI (performance) |
| Quality benchmarks | GSM8K, IFEval, MMLU (5-subject mini, anchor-only) |
| Model catalog | 9 checkpoints, see Section 2 table |
| Storage | PostgreSQL (portable relational database) |
| Testing | pytest + pytest-asyncio (backend), Vitest + React Testing Library (frontend), Playwright (E2E) |
| Target platform / VM SKUs | `Standard_NC16as_T4_v3` (3B/7B), `Standard_NC24ads_A100_v4` (27B), `Standard_NC80adis_H100_v5` (70B) |
| Infrastructure-as-code | Terraform (HCL, `azurerm` provider) |
| Application hosting | Azure Container Apps (built-in HTTPS ingress + Entra ID SSO) |
| Workflow orchestration | Azure Durable Functions (coordination only, no domain logic) |
| Isolated job execution | Azure Container Apps Jobs (Terraform, deploy, eval, perf, export) |
| Resource-group topology | `rg-llm-shared-{stage}`, `rg-llm-control-{stage}`, `rg-llm-demo-{environmentId}` |
| GPU network exposure | Private only (no public IP); vLLM port allowed only from `snet-containerapps` |
| Secret management | Azure Key Vault (platform secrets); in-memory-only for presenter HF credentials |

No open `NEEDS CLARIFICATION` markers remain in Technical Context after this document.
