# Implementation Plan: Azure LLM Serving Demo

**Branch**: `001-llm-serving-demo` | **Date**: 2026-08-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-llm-serving-demo/spec.md`

## Summary

A web application lets a presenter provision a single Azure GPU server, deploy one curated
Hugging Face model checkpoint (3B/7B/70B class) behind a pluggable inference-engine interface,
tune its serving configuration, run curated golden-dataset and standard-benchmark quality checks
plus load-driven performance tests, redeploy, and compare experiment revisions side by side, then
tear down explicitly while preserving experiment history. Provisioning, deployment, and teardown
sit behind a single internal provider interface (Azure plus a local/Ollama provider added for
User Story 7) so the domain model does not depend on Azure-specific APIs. Technology choices for
the inference engine, model catalog, quality benchmarks, and evaluation/test framework are
resolved through comparative research in Phase 0 below, per FR-041 through FR-045 and
FR-063/FR-064. Per User Story 10 (Baseline Azure Pilot Architecture), the Azure implementation is a
PaaS-first control plane (Azure Container Apps + Durable Functions + Container Apps Jobs) with a
disposable, private GPU-serving environment, organized into exactly three resource-group boundaries
(FR-074-FR-090); this supersedes the earlier single-VM-plus-App-Service topology without changing
any of User Stories 1-9's functional requirements.

## Technical Context

**Language/Version**: Python 3.11+ (backend, FastAPI) — chosen because every Phase 0 tooling
decision (vLLM, `lm-evaluation-harness`, LLMPerf) is a Python library/CLI, letting the API layer
invoke them directly; TypeScript + React (frontend). See [research.md](./research.md) Section 5a.

**Primary Dependencies**: vLLM (`vllm/vllm-openai`, Apache 2.0) as the implemented Azure inference
engine (FR-041/FR-042, research.md Section 1); Ollama as the local inference runtime for User
Story 7's non-Azure demo path (FR-066), served through its OpenAI-compatible endpoint so the same
`lm-evaluation-harness`/`LLMPerf` integration patterns apply; `lm-evaluation-harness` for quality
benchmark execution and `LLMPerf`/vLLM benchmark CLI for performance testing (FR-063/FR-064,
research.md Section 3); Terraform (`azurerm` provider) for infrastructure-as-code (FR-051,
research.md Section 6); FastAPI + React for the operator web application (FR-048), deployed as an
Azure Container App (FR-075); the `azure-functions-durable` Python SDK for the Durable Functions
orchestration app (FR-077); Azure Container Apps Jobs as the isolated execution surface for
Terraform, model deployment, evaluation, and performance workloads (FR-078).

**Storage**: PostgreSQL — a portable relational database reachable from a first-party Azure
managed offering (Azure Database for PostgreSQL Flexible Server) and at least one other major
cloud's managed offering (Amazon RDS, Google Cloud SQL), so persistence is not Azure-locked even
though only Azure is implemented now (FR-047). JSONB columns hold the genuinely variable parts
(model config key/value pairs, per-operation event-log payloads per FR-062). See
[research.md](./research.md) Section 5b for why relational was chosen over a document database.

**Testing**: `pytest` + `pytest-asyncio` for backend unit/integration/contract tests (validating
`contracts/api.md`, `contracts/provider-interface.md`, `contracts/engine-interface.md`);
`Vitest` + `React Testing Library` for frontend unit tests; `Playwright` for end-to-end validation
of the `quickstart.md` scenarios and cross-cutting checks (single-writer, no-auto-retry, audit
trail). See [research.md](./research.md) Section 5c.

**Target Platform** (User Story 10 — Baseline Azure Pilot Architecture, supersedes the original
single-VM-plus-App-Service topology described below the line): a PaaS-first control plane with a
disposable GPU-serving environment, organized into exactly three resource-group boundaries per
FR-074:

- **`rg-llm-shared-{stage}`** (retained, singleton): VNet `vnet-llm-{stage}` (`10.20.0.0/16`) with
  `snet-containerapps` (`10.20.1.0/24`), `snet-private-endpoints` (`10.20.2.0/24`),
  `snet-functions` (`10.20.3.0/24`), `snet-data` (`10.20.4.0/26`, delegated to PostgreSQL Flexible
  Server VNet Integration), `snet-gpu` (`10.20.10.0/24`); private DNS zones/links; NSGs;
  a NAT Gateway for stable outbound egress; the shared Azure Container Registry; Key Vault for
  application/platform secrets (never presenter-supplied Hugging Face credentials, FR-082); Log
  Analytics + Application Insights.
- **`rg-llm-control-{stage}`** (retained, singleton): the Azure Container Apps environment hosting
  the React + FastAPI app behind built-in HTTPS ingress and Microsoft Entra ID SSO (FR-075);
  Container Apps Job *definitions* for the Terraform runner, model-deployment worker,
  `lm-evaluation-harness` worker, LLMPerf/vLLM-benchmark worker, and export worker (FR-078); the
  Azure Durable Functions app that coordinates only long-running-workflow orchestration — never
  domain logic or a web API (FR-076/FR-077); Azure Database for PostgreSQL Flexible Server (private
  access); Storage accounts/containers separated for Durable Functions task-hub state, Terraform
  remote state, and experiment artifacts/exports; managed identities, least-privilege RBAC per
  component, diagnostic settings, and alerts (FR-081/FR-087).
- **`rg-llm-demo-{environmentId}`** (disposable, per environment): only the Azure GPU VM selected by
  the validated deployment profile — `Standard_NC16as_T4_v3` (3B/7B tier), `Standard_NC24ads_A100_v4`
  (27B tier), `Standard_NC80adis_H100_v5` (70B tier) — its private NIC on `snet-gpu` (no public IP,
  FR-079), OS/model-cache data disks, VM extensions, and environment-specific monitoring config.
  Terraform destroy here MUST remove only this resource group (FR-090); retained control-plane
  services and experiment records survive (FR-080).

The vLLM serving port is allowed only from `snet-containerapps` or another explicitly authorized
source (FR-079/FR-082 of the network security group). User Story 7 additionally supports the
presenter's own machine (CPU or a single consumer GPU) as a local, non-Azure target running Ollama,
with no Terraform/quota/resource-group involvement at all.

> **Superseded topology** (kept here for historical context only — no longer implemented): the
> operator web app was previously hosted on Azure App Service for Containers with regional VNet
> Integration + a NAT Gateway giving the backend a single stable outbound IP allowlisted into each
> demo environment's GPU VM NSG and the PostgreSQL firewall by source IP, and each demo environment
> was a single flat resource group (VNet/subnet/NSG/public IP/NIC/VM, optionally with Bastion). This
> was replaced because it fragmented into too many resource groups, coupled orchestration into the
> API process, and exposed a public IP path to the GPU VM that the new architecture avoids by
> keeping all inference traffic on `snet-gpu`, reachable only from `snet-containerapps`.

**Project Type**: web application (backend API + operator web UI, per FR-048) plus an Azure
provisioning/deployment layer behind a pluggable provider interface (FR-037), with a second local
provider implementation added for User Story 7 (FR-065)

**Performance Goals**: End-to-end demo workflow (provision -> deploy -> tune -> test -> redeploy
-> compare) completes within 60 minutes under a documented reference execution profile (SC-002,
FR-058); performance reports include TTFT, inter-token latency, end-to-end latency, and throughput
with p50/p95 percentiles (FR-026, FR-057)

**Constraints**: Single active model deployment per demo environment (FR-009); single-writer
semantics per environment across provisioning/deployment/teardown/evaluation/prompt-submission
(FR-052); teardown blocked while operations are active (FR-053); no auto-retry of failed
operations (FR-055); checkpoint identity may be a mutable tag, so reproducibility is best-effort
(FR-012)

**Scale/Scope**: One presenter-driven demo environment at a time per deployment; small curated
model catalog (3 families x 3 size classes); 2-3 standard benchmarks plus a curated golden
dataset; small FDE-team usage anticipated later but not required for v1 (out of scope: multi-
tenant isolation, autoscaling, production SLAs)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|-----------|-------|--------|
| I. Reproducible Configuration | Every model/inference config is versioned (FR-012, FR-013, FR-019, FR-020); defaults must be visible (FR-013). Checkpoint pinning is best-effort per Clarification 5 — documented, not hidden. | PASS |
| II. Evidence-Driven Optimization | Quality and performance are both required per run (User Stories 3-4); pass/fail thresholds and percentiles are mandatory (FR-056, FR-057); baseline vs candidate comparison is a first-class feature (User Story 5, FR-031/032). | PASS |
| III. Reliable and Observable Inference | Health/error/latency/throughput/resource info required (FR-017, FR-026, SC-007); per-operation event logs captured even though only summary metrics surface in v1 UI (FR-062) — instrumentation exists, just not fully exposed yet; documented as a deliberate v1 scope choice, not a hidden failure. | PASS |
| IV. Secure Best-Practice Defaults | SSO-gated access (FR-001); no operator-password bypass (removed per review); credentials for gated HF checkpoints are accepted but never persisted/displayed (FR-011); audit trail of acting identity (FR-004). | PASS |
| V. Simplicity and Learning Value | Single provider interface, no speculative multi-cloud adapters (FR-037 trimmed per rubber-duck review); one inference engine implemented behind a pluggable contract (FR-014); web app is a thin orchestration layer over provisioning/inference/evaluation interfaces (FR-035, FR-048). | PASS |

No violations requiring Complexity Tracking justification at this stage. Re-evaluate after Phase 1
data model and contracts are drafted, since technology selections from Phase 0 could introduce new
tradeoffs (e.g., an inference engine with a heavier operational footprint than justified).

### Post-Phase-1 re-check

Re-evaluated after `research.md`, `data-model.md`, `contracts/*.md`, and `quickstart.md` were
drafted. The selected stack (vLLM, `lm-evaluation-harness`, LLMPerf, PostgreSQL, Terraform) adds
no new operational footprint beyond what the constitution anticipates: vLLM's own `/metrics` and
`/health` endpoints satisfy Principle III without extra instrumentation; PostgreSQL is a single
well-understood dependency (not a bespoke storage layer); Terraform requires state management but
that is standard IaC practice, not project-specific complexity. All 5 principles remain PASS with
no Complexity Tracking entries required.

### Post-implementation re-check (tasks.md T124)

Re-verified against the implemented code once User Stories 7-11 landed. Principle V's original
wording above ("single provider interface", "one inference engine") is now stale and superseded by
this note rather than rewritten in place, to preserve the historical Phase-1 record:

- **Provider interface**: two implementations now exist — `AzureProviderAdapter` (original) and
  `LocalProviderAdapter` (`backend/src/providers/local/adapter.py`, User Story 7), both behind the
  same `ProviderAdapter` contract (`contracts/provider-interface.md`). This is not a speculative
  multi-cloud expansion (the concern Principle V originally guarded against) — it's a single
  no-cloud fallback added for local/offline demo capability, still behind one interface with no
  branching business logic outside the adapter boundary.
- **Inference engine**: two engines now exist — vLLM (original) and Ollama
  (`backend/src/providers/local/ollama_adapter.py`, User Story 7), both behind the same
  `EngineAdapter` contract (`contracts/engine-interface.md`). Same reasoning: added to support the
  local/offline path, not speculative extensibility.
- All other Principle V claims (thin web-app orchestration layer, FR-035/048) still hold as
  written; no new violations or Complexity Tracking entries are required. **Status remains PASS.**
- Principles I-IV: re-checked against `backend/src/domain/hf_credentials.py`'s
  `assert_hf_token_not_persisted`/`accept_hf_token` guards (Principle IV, FR-011),
  `backend/src/api/errors.py` + `correlation.py` (Principle III observability), and the versioned
  catalog/config entities including the new `phi` model family and `presentationSubset` fields
  (Principle I) — no divergence found; all remain **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── domain/               # provider-agnostic entities: environment, model config,
│   │                          # inference config, deployment revision, experiment run,
│   │                          # result report, comparison (data-model.md)
│   ├── providers/
│   │   ├── azure/            # Azure provider adapter implementing the provider
│   │   │                      # interface (FR-037): builds workflow inputs; the actual
│   │   │                      # provisioning/deployment/teardown execution is dispatched
│   │   │                      # to Durable Functions -> Container Apps Jobs (FR-076-078)
│   │   └── local/            # local (non-Azure) provider adapter for User Story 7
│   │                          # (FR-065): no quota/region checks, Ollama readiness check,
│   │                          # runs in-process (no orchestration/job dispatch)
│   ├── engines/
│   │   ├── vllm/              # pluggable inference-engine adapter (FR-014) for vLLM,
│   │   │                      # selected in research.md Section 1
│   │   └── ollama/            # local inference-engine adapter for User Story 7 (FR-066),
│   │                          # against Ollama's OpenAI-compatible endpoint
│   ├── evaluation/            # golden dataset + standard benchmark execution (FR-021-024)
│   ├── performance/           # load/performance workload execution (FR-025-027)
│   ├── api/                   # HTTP API consumed by the operator web app, plus internal
│   │                          # callback/status-update endpoints Container Apps Jobs and
│   │                          # Durable Functions report progress/results through
│   │                          # (FR-076, User Story 10 Acceptance Scenario 6)
│   └── persistence/           # PostgreSQL repository layer (portable relational DB, FR-047)
└── tests/
    ├── contract/              # provider interface, engine interface, API contract tests
    ├── integration/           # config-to-inference and provisioning-to-deployment boundaries
    └── unit/

functions/
└── src/                       # Azure Durable Functions app (Python): orchestrators for
                                # provision/deploy/evaluate/perf-test/export/cancel/teardown
                                # workflows (FR-077). Owns only workflow coordination, phase/
                                # elapsed time, cancellation routing, terminal failure handling
                                # — no domain data, no web API. Correlation IDs shared with
                                # FastAPI and dispatched Container Apps Jobs (FR-086).

jobs/
└── src/                       # Container Apps Jobs entrypoints (FR-078), one per isolated
    ├── terraform_runner/      # workload: runs infra/demo Terraform apply/destroy
    ├── model_deployment/      # deploys the selected checkpoint via the engine adapter;
    │                          # holds any Hugging Face credential only in process memory
    │                          # (FR-082/FR-083)
    ├── evaluation_worker/     # runs lm-evaluation-harness golden/benchmark suites
    ├── performance_worker/    # runs LLMPerf/vLLM benchmark workloads
    └── export_worker/         # produces experiment exports before teardown
                                # Each worker reports progress/results back to FastAPI's
                                # internal callback API using the shared operation/
                                # correlation ID (FR-086).

frontend/
├── src/
│   ├── components/
│   ├── pages/                 # provision, deploy/exercise, quality, performance, compare,
│   │                          # teardown flows guiding the presenter end-to-end (FR-035)
│   └── services/               # API client
└── tests/

infra/
├── shared/                    # Terraform (HCL, azurerm provider) for rg-llm-shared-{stage}
│                               # (singleton, retained): VNet/subnets, NSGs, NAT Gateway,
│                               # private DNS, ACR, Key Vault, Log Analytics/App Insights
│                               # (FR-074, User Story 10)
├── control/                   # Terraform for rg-llm-control-{stage} (singleton, retained):
│                               # Container Apps environment + app, Container Apps Job
│                               # definitions, Durable Functions app, PostgreSQL Flexible
│                               # Server, Storage accounts, managed identities/RBAC,
│                               # diagnostics/alerts (FR-074, User Story 10)
└── demo/                      # Terraform for rg-llm-demo-{environmentId} (disposable, one
                                # per demo environment): only the private GPU VM + NIC + disks
                                # + extensions (FR-005, FR-051, FR-074, FR-079, FR-090,
                                # research.md Section 6). Applied/destroyed once PER demo
                                # environment; cannot touch shared/control resources.

.github/
└── workflows/                 # CI/CD (see "CI/CD" section below): backend.yml, frontend.yml,
                                # functions.yml, jobs.yml, infra.yml
```

**Structure Decision**: Web application (Option 2: separate `backend/` and `frontend/`), plus a
`functions/` Durable Functions orchestration app, a `jobs/` set of Container Apps Jobs workers, and
top-level `infra/shared/`, `infra/control/`, `infra/demo/` for Terraform-based Azure IaC — two
singleton modules (`shared/`, `control/`) applied once for the life of the deployment, and one
per-environment module (`demo/`) applied/destroyed independently per demo environment (User Story
10, FR-074, FR-090). The backend isolates each provider adapter (Azure, and local/Ollama for User
Story 7) and each pluggable inference-engine adapter (vLLM, Ollama) behind their own interfaces so
the domain, evaluation, and comparison logic never depend on Azure-specific or engine-specific APIs
(FR-037, FR-014); the Azure provider adapter itself now depends only on dispatching Durable Functions
workflows, not on directly invoking Terraform or engine deployment, keeping FastAPI as the sole
system-of-record owner (FR-076) while Durable Functions and Container Apps Jobs handle orchestration
and execution respectively (FR-077/FR-078).

## CI/CD

GitHub Actions (`.github/workflows/`) provides consistent CI + CD for every part of the repo, so
none of `backend`, `frontend`, `functions`, `jobs`, or `infra` relies on manual `az`/`terraform`
commands run by hand from an operator's machine for routine changes:

| Workflow | Trigger | `test` job | `deploy` job |
|----------|---------|------------|--------------|
| `backend.yml` | push/PR touching `backend/**` | `ruff check`, `black --check`, `pytest` (unit only, per `backend/pytest.ini`'s default `-m "not integration"`) | `az acr build` (tag: git SHA + `latest`) → update the Container App's image revision → poll `/healthz` |
| `frontend.yml` | push/PR touching `frontend/**` | `eslint`, `tsc --noEmit` + `vite build`, `vitest run` | `az acr build` with `VITE_API_BASE_URL` baked in as a build arg → update the Container App's image revision → poll `/` |
| `functions.yml` | push/PR touching `functions/**` | `ruff check`, `black --check`, `pytest` (unit only) | publish the Durable Functions app via `func azure functionapp publish` or an OIDC-authenticated zip deploy |
| `jobs.yml` | push/PR touching `jobs/**` | `ruff check`, `black --check`, `pytest` (unit only) | `az acr build` per job image (tag: git SHA + `latest`) → update each Container Apps Job's image reference |
| `infra.yml` | push/PR touching `infra/**` | `terraform fmt -check` + `terraform validate` (matrix over `shared`, `control`, `demo`) | none — see below |

Design decisions:

- **`deploy` only runs after `test` passes, and only on push to `main`** (never on pull requests) —
  `needs: test` plus an `if: github.event_name == 'push' ...` guard in each workflow with a `deploy`
  job.
- **Images are tagged with the git SHA**, not just `:latest` — every deploy is traceable to an exact
  commit, and a bad deploy can be rolled back by re-pointing the Container App/Job at a prior SHA tag
  without rebuilding.
- **Auth is OIDC** (`azure/login@v2` with a federated credential on a dedicated
  `llmserving-github-actions` app registration; no client secret is stored). The service principal
  is scoped to exactly the roles it needs in `rg-llm-shared-{stage}` (`AcrPush`) and
  `rg-llm-control-{stage}` (`Container Apps Contributor`, `Website Contributor` equivalent for
  Functions), so a compromised workflow cannot touch per-environment GPU infrastructure
  (`infra/demo`) or the database directly.
- **`infra.yml` never runs `terraform apply`.** `infra/shared` and `infra/control` are singleton,
  single-applier modules run by hand from the operator's machine or a controlled pipeline;
  `infra/demo` is applied/destroyed repeatedly, per-environment, by the Container Apps Job that a
  Durable Functions workflow dispatches at runtime (FR-078). None of the three are meant to be
  applied from CI — `infra.yml` only catches formatting drift and structural/syntax errors
  (`fmt`/`validate`) before merge, consistent with that existing single-applier design rather than
  introducing a second, competing apply path.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
