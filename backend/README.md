# Backend foundation

This backend implements the Setup + Foundational layers for the spec-kit feature:
FastAPI app bootstrap, PostgreSQL/SQLAlchemy persistence, Alembic migrations, auth/audit/
telemetry scaffolding, provider/engine adapter contracts, and reference-data seeding.

## Prerequisites

- Python 3.11+
- A reachable PostgreSQL instance
- PowerShell or another shell that can set environment variables

## Local setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

Optional research-driven tooling for later phases:

```powershell
pip install -e .[evaluation]
```

Copy the sample environment file and update the PostgreSQL connection string:

```powershell
Copy-Item .env.example .env
```

## Database migrations

Apply the foundational schema:

```powershell
cd backend
alembic upgrade head
```

Seed the deployment profiles, vLLM engine record, and the 9-entry model catalog:

```powershell
cd backend
python -m src.persistence.seed_catalog
```

Seed the standard-benchmark definitions (GSM8K/IFEval/MMLU), a curated golden
dataset, and the pre-defined industry-standard performance workloads (all
required before the corresponding run types have anything to select in the UI):

```powershell
python -m src.evaluation.seed_benchmarks
python -m src.evaluation.seed_golden_datasets
python -m src.performance.seed_workloads
```

Each seed script upserts by primary key (`session.merge`), so it is safe to
re-run. `backend/docker-entrypoint.sh` runs all four automatically on every
container startup, so a deployed environment never needs this done by hand.

## Local Ollama demo mode

Presenters without Azure access can run the same provision → deploy → prompt → quality →
performance flow against a local Ollama runtime.

1. Install and start [Ollama](https://ollama.com/).
2. Pull a supported small Qwen checkpoint:

   ```powershell
   ollama pull qwen2.5:0.5b-instruct
   ```

3. If Ollama is not listening on the default port, set `OLLAMA_BASE_URL` before starting the
   backend:

   ```powershell
   $env:OLLAMA_BASE_URL = "http://localhost:11434"
   ```

4. In the UI, choose **Local (Ollama)** during provisioning.

## Run the dev server

```powershell
cd backend
uvicorn src.api.app:app --reload
```

Health route:

- `GET /healthz`
- `GET /readyz` - bounded real PostgreSQL probe; 503 when unavailable, paused, or timed out

`/healthz` is process liveness and never queries the database. `/readyz` checks
`SELECT 1` through an independent, nonpooled connection with connect/statement
timeouts and at most one DB probe in flight. Its response deadline defaults to
three seconds (`DATABASE_READINESS_TIMEOUT_SECONDS`, greater than zero and at
most ten). A timeout returns 503 even if a driver/DNS call is still completing;
it never reports a database as ready from cached state. Responses do not expose
connection strings or claim to distinguish a paused database from an unreachable
one. Container Apps and rollout checks use readiness; Docker's liveness check
remains `/healthz`. Existing custom `AUTH_BYPASS_PATHS` must include `/readyz`
before using it as an unauthenticated platform probe.

## Configuration cleanup

`DELETE /environments/{environmentId}/model-configurations/{configurationId}`
and the equivalent `inference-configurations/{configurationId}` remove only an
unreferenced configuration created by the authenticated operator. Success is 204;
missing/wrong-environment IDs return 404, a different creator 403, and a busy
environment or any deployment revision reference 409. Active, failed and historical
revision references are all protected; no cascade or Azure resource deletion occurs.
Deletion and deployment coordinate through the existing environment single-writer
lock, with deployment rereading configurations after acquiring it.

Existing configuration IDs remain valid. Newly created model/inference configurations
use UUIDs instead of row counts, so deleting scratch records cannot cause later ID
reuse or collisions. The main-cloud acceptance harness deletes its exact scratch IDs
in a finally cleanup, verifies absence, and retains separate intended deployment
configurations. See [the executable contract](../e2e/live/cloud/README.md).

## Explicit local versus cloud authentication

The safe default is `AUTH_MODE=entra-jwt`. Configure `AZURE_TENANT_ID` and
`AUTH_AUDIENCE`; an unconfigured cloud API returns 503, not a demo identity.
Operator tokens must have a valid RS256 signature, tenant issuer, audience,
expiry, issued-at, tenant claim and user identity. Supply a bearer token or the
real Easy Auth `X-MS-TOKEN-AAD-ID-TOKEN`; unsigned identity-name headers are
ignored. Internal managed-identity callback authentication remains separate.

For local development only, explicitly use `AUTH_MODE=local-demo` (included in
`.env.example`). This preserves the existing demo/forwarded identity headers and
allowed-email-domain checks. Production or Azure Container Apps/App Service
hosting refuses local-demo mode, even if a cloud deployment labels itself
development. Never set `VITE_DEMO_USER` as cloud authentication.

Requests to `/healthz`, `/readyz`, `/docs`, `/redoc`, and `/openapi.json` are exempt so local bootstrapping
works before a real identity layer is wired in.

See [the authentication bootstrap guide](../docs/AUTHENTICATION.md) for external
SSO prerequisites when the deployment identity cannot create Graph applications.

## Validation commands

```powershell
cd backend
ruff check .
pytest
```

Integration tests are skipped by default via `pytest.ini`:

```powershell
cd backend
pytest -m integration
```

Use the `integration` marker for tests that require a live PostgreSQL instance or other external
infrastructure.

## Azure environment provisioning authentication

The current backend dispatches provisioning through Durable Functions to the
`terraform_runner` Container Apps Job. Configure managed identities and scoped
RBAC through `infra/control`; do not copy local Azure credentials into the backend
or create subscription-wide service-principal secrets for this flow.
See [`infra/README.md`](../infra/README.md) and
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) for the current topology.
Local state, generated SSH keys, Terraform plans, and credentials must remain
untracked and must not be uploaded as CI artifacts.

## What is intentionally not implemented yet

This phase does **not** include any user-story business logic (T037+): environment preview,
provisioning orchestration, deployment workflows, prompt submission, evaluation runs,
comparisons, or teardown APIs still belong to the next phase.
