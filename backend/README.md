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

## Authentication behavior in this foundational phase

The auth middleware expects an upstream organization SSO layer to inject one of these headers:

- `X-MS-CLIENT-PRINCIPAL-NAME`
- `X-Forwarded-Email`
- `X-User-Email`
- `X-Demo-User`

Requests to `/healthz`, `/docs`, `/redoc`, and `/openapi.json` are exempt so local bootstrapping
works before a real identity layer is wired in.

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
