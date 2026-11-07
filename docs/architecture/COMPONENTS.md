# Components and data lineage

[Architecture map](../ARCHITECTURE.md) / **depth 3** /
[containers](CONTEXT.md#runtime-containers) / [deployment](DEPLOYMENT.md) /
[flows](FLOWS.md)

## Frontend

```mermaid
flowchart TB
    Shell["Router, navigation, theme"]
    Session["Operator session check"]
    Public["PublicWorkspace"]
    Operator["Operator pages"]
    Shared["Pickers, histories, metric panels"]
    PublicAPI["publicApi"]
    OperatorAPI["Typed operator services"]
    Transport["apiClient"]
    Proxy["Nginx proxy or local Vite API URL"]
    Shell --> Session
    Session -->|Signed out or unavailable| Public
    Session -->|Authenticated| Operator
    Public --> Shared
    Operator --> Shared
    Public --> PublicAPI
    Operator --> OperatorAPI
    PublicAPI --> Transport
    OperatorAPI --> Transport
    Transport --> Proxy
```

[`App.tsx`](../../frontend/src/App.tsx) mounts public projections for all routed
screens while signed out, and existing operator pages only after `/session`
verification. [`PublicWorkspace`](../../frontend/src/pages/PublicWorkspace.tsx)
reads profiles/catalog, environments, configurations, definitions, runs, reports
and saved comparisons. It has no submission forms. The server remains the
authorization/redaction boundary, even if a client bypasses disabled controls.

Operator pages are implemented, not scaffolds: Provision, Deploy, Exercise,
Retune, Quality/Performance Run and Report, Compare, Experiment History,
Environment Detail and Teardown. Saving a tuning version does not itself change
traffic; deployment creates a new revision. Exercise history is session-only.
Public data failures and sign-in unavailability have separate retry/error states.

## API and execution

```mermaid
flowchart TB
    HTTP["FastAPI app"]
    Middleware["Errors, audit, telemetry, auth, correlation"]
    Public["Public GET projection router"]
    Operator["Operator routes and owner checks"]
    Internal["Managed-identity callbacks"]
    Domain["Workflow service and environment lock"]
    Provider["Azure / local provider adapters"]
    Engine["vLLM / Ollama engine adapters"]
    Runs["QualityRunOrchestrator"]
    Tools["Golden scorer, lm-eval, LLMPerf"]
    DB[("SQLAlchemy / PostgreSQL")]
    HTTP --> Middleware
    Middleware --> Public
    Middleware --> Operator
    Middleware --> Internal
    Public --> DB
    Operator --> Domain
    Internal --> Domain
    Domain --> DB
    Operator --> Provider
    Provider --> Engine
    Operator --> Runs
    Runs --> Tools
    Runs --> Engine
    Runs --> DB
```

API routes cover catalog, environments, configurations, deployments, prompts,
runs, comparisons, system/session, public projections and internal workflows.
Azure preflight checks the exact effective SKU/region/priority without claiming
physical capacity. Azure provider dispatch and local provider behavior share
contracts, not infrastructure implementations.

`public.py` allowlists finite metrics/tuning fields and removes raw text,
checkpoints, arbitrary arguments, URLs, diagnostics and infrastructure identities.
It never enters the provider/engine layer. `internal_auth.py` validates exact
managed-identity resources separately from `auth.py`'s operator user tokens.

## Persistent lineage

```mermaid
flowchart LR
    Catalog["Catalog and test definitions"]
    Config["Versioned model and inference configs"]
    Environment["Environment and saved provider scope"]
    Revision["Deployment revision"]
    Snapshot["Run and frozen input snapshot"]
    Executor["In-process runner"]
    Report["Persisted result report"]
    Comparison["Saved comparison"]
    Public["Sanitized public projection"]
    Catalog --> Config
    Config --> Revision
    Environment --> Revision
    Revision --> Snapshot
    Catalog -->|Accepted definition copied| Snapshot
    Snapshot --> Executor
    Executor --> Report
    Snapshot -->|Provenance| Report
    Report --> Comparison
    Report --> Public
    Comparison --> Public
```

Run acceptance deep-copies environment, revision, model/inference settings and
test definition. Later edits to catalog/definitions must not change accepted
inputs. Model repository ID and checkpoint revision are distinct; serving a
repository literally named `main` is not valid checkpoint resolution.
Report reads use saved lineage rather than today's catalog. Comparisons retain
report/revision/environment relationships and comparability, not a fresh rerun.

Configurations referenced by any deployment revision cannot be deleted;
unreferenced scratch deletion is creator-scoped and lock-coordinated. Keeping a
configuration/report is not backing it up. See [data and recovery](../DATA_AND_RECOVERY.md).

Sources: [`routes`](../../backend/src/api/routes),
[`run acceptance`](../../backend/src/api/routes/runs.py),
[`configurations`](../../backend/src/api/routes/configurations.py),
[`report repository`](../../backend/src/domain/result_report_repo.py),
[`comparison builder`](../../backend/src/domain/comparison_builder.py),
[`domain entities`](../../backend/src/domain),
[`migrations`](../../backend/migrations/versions).
