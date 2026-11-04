# Testing and evidence boundaries

Pull-request CI is read-only and requires no Azure/GitHub deployment credentials.
It does not deploy, push container images, or run Terraform plan/apply/destroy.
The separately protected Azure canary and opt-in application deployments are not
pull-request jobs.

| Surface | CI coverage | What it does not prove |
| --- | --- | --- |
| Backend | Ruff, Black, migrations/seeds on disposable PostgreSQL 16, full `python -m pytest -q -o addopts=""` | Live Azure services or an actual inference model |
| Real PostgreSQL tests | Seeded API reads, JSONB roundtrip, owner-safe lock release, bounded concurrent row-lock contention | Production database capacity, pause/resume, or private networking |
| Functions | Every test; dependency-inclusive ZIP extraction, import and eight-function registration smoke | Azure Functions host startup, Durable storage, or cloud replay behavior |
| Jobs | Every shared/worker test with all workers' declared dependencies | Genuine quality/performance parity or live job execution |
| Frontend | Existing lint, type-check/build, unit tests | Backend availability or authenticated cloud UX |
| Browser | Existing Playwright Chromium API-mocked suite | Full-stack E2E; these tests intercept API responses |
| Containers | Build all seven real Dockerfiles; API/worker imports, pinned genuine LLMPerf metadata, frontend HTTP, Terraform/CLI binaries | Image deployment, GPU inference, or application readiness |
| Terraform | Format and validate every current module (`shared`, `control`, `demo`), backend-disabled init | A usable cloud plan, quota, allocation or deployment |
| Canary | Credential-free guard tests and workflow syntax validation | OIDC/cleanup until separate real protected runs are recorded |

## Backend and real PostgreSQL

Install the existing backend dev extra, then run static checks:

```sh
cd backend
python -m pip install -e '.[dev]'
ruff check src tests
black --check src tests
```

Default `pytest -q` deliberately excludes integration tests. To include every
test, run the exact command below. The existing integration-marked flows mostly
use in-memory sessions/mocked providers; only the explicitly named PostgreSQL
tests assert a real database.

Use **only a disposable database**, not an original deployment or production
connection. Database tests create and remove uniquely named test environments;
the seed commands update reference catalog data. CI creates a fresh PostgreSQL
service for each run. Keep credentials and database data out of artifacts.

```sh
export DATABASE_URL='postgresql+psycopg://postgres:ci-only-test@127.0.0.1:5432/llmserving_ci'
export TEST_DATABASE_URL="$DATABASE_URL"
python -m alembic upgrade head
python -m src.persistence.seed_catalog
python -m src.evaluation.seed_benchmarks
python -m src.evaluation.seed_golden_datasets
python -m src.performance.seed_workloads
python -m pytest -q -o addopts=""
```

Without `TEST_DATABASE_URL`, the three real database tests explicitly skip.
Hosted Backend CI always sets it. An invalid configured URL, failed connection,
missing migration/seed, or unexpected SQLSTATE fails rather than falling back to
SQLite or an in-memory session.

## Functions and jobs

Use separate Python environments for backend and jobs: their current Azure
Compute SDK ranges differ. Runtime CI installs every worker's requirements in
the job-test environment, and Functions in its own job.

```sh
cd functions
python -m pip install pytest pytest-asyncio -r requirements.txt
python -m pytest -q tests
python -c 'import function_app; assert len(function_app.app.get_functions()) >= 8'
```

The Functions ZIP includes dependencies under `.python_packages/lib/site-packages`
and is smoke-tested after extraction. It is an ordinary CI artifact, not proof
of Azure host deployment. It expires after seven days.

Worker unit tests isolate the Terraform runner's managed-identity login from
Terraform command behavior; dedicated tests separately assert missing-identity
and denied-login failures stop before Terraform and that successful login uses
only `az login --identity`. Production authentication is not disabled for tests.

## Browser and image validation

Install frontend and E2E lockfiles with `npm ci`; from `e2e`, install Chromium
with `npx playwright install --with-deps chromium` and run `npm test`.
Playwright starts the frontend automatically. These are **API-mocked browser
tests**, not genuine local-model or Azure E2E.

Runtime CI builds images from the repository root without registry credentials.
The API image retains the real ray-project LLMPerf commit
`f1d6bed47e4501b0e371082b41601b59ab55269f`; metadata smoke must verify this
commit, not install a different PyPI package named `llmperf`.
Runtime smoke containers use no network and receive no cloud credentials.

## Real local API and small-model validation

The read-only `Real local API` workflow uses actual loopback HTTP services:
PostgreSQL 16, the backend in explicit `local-demo` mode, and a digest-pinned
Ollama container capped at two CPUs/two GiB. It downloads the genuine
`qwen2.5:0.5b-instruct` model and records its manifest digest. No Azure credentials,
GPU or remote inference service is used. Network/model-download failure is a
failed gate, never replaced with an inference mock.

`tests/integration/test_live_ollama.py` is intentionally skipped unless
`LIVE_API_URL`, `OLLAMA_BASE_URL` and `TEST_DATABASE_URL` point to explicitly
started disposable loopback services. The database must be `llmserving_ci`;
run migrations and `python -m src.persistence.seed_catalog` first. From `backend`:

```bash
LIVE_API_URL=http://127.0.0.1:8000 \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
TEST_DATABASE_URL="$DATABASE_URL" \
python -m pytest -q -s -o addopts="" tests/integration/test_live_ollama.py
```

The live API process must separately use `AUTH_MODE=local-demo APP_ENV=test`
and the same database/Ollama URLs. `OLLAMA_EXPECTED_DIGEST` rejects an unexpected
model version; `FULLSTACK_EVIDENCE_FILE` saves only this synthetic run's evidence.
The test covers real prompts, two golden cases, immutable versioned configuration,
single-stream (two requests) and concurrency-10 (ten requests) HTTP performance,
negative authentication, cancellation, reports and local environment teardown.
Golden failures are recorded honestly rather than requiring a tiny model to
achieve a predetermined quality score. One real warmup precedes each measured
performance workload and is excluded from throughput counts/timing.

These are fixed-prompt CPU smoke workloads, not standardized LLMPerf results,
benchmark acceptance, real-browser testing or Azure release acceptance. The
Ollama runner does not synthesize a specified input-token distribution. API-mocked
Playwright tests remain a separate boundary. Cloud authentication, real Azure
GPU/networking and independently owned billable-resource cleanup require their
own evidence.

## Release evidence

Report exact commit/image/model versions, workload, counts/failures and measured
latency/throughput for fresh real-model tests. Historical metrics and mocked
outputs cannot replace a missing run. Record blocked capacity/consent/auth tests
as blocked. Passing CI alone is not release acceptance.

See [the canary runbook](AZURE_CANARY.md) for the independent failure/cancellation
cleanup gate and its deliberately narrow scope.
