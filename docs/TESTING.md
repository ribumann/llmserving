# Testing and evidence boundaries

Pull-request CI is read-only and requires no Azure/GitHub deployment credentials.
It does not deploy, push container images, or run Terraform plan/apply/destroy.
The separately protected Azure canary and opt-in application deployments are not
pull-request jobs.

Deployment workflow guard tests execute the actual embedded pre-login masking
Python with synthetic environment values, including every missing field and
escaped multiline/percent values. They also verify protected manual-main deploy
gates, absence of deployment credentials in PR checks and fixed privileged
checkout/login commits. These credential-free tests never invoke Azure login,
push images, enable deployment or establish current target authorization.
Protected resource names must also use environment secrets so GitHub masks
runner-generated environment headers before the masking script starts; direct
Python snippet execution alone cannot prove runner log redaction.

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

## Release evidence

Report exact commit/image/model versions, workload, counts/failures and measured
latency/throughput for fresh real-model tests. Historical metrics and mocked
outputs cannot replace a missing run. Record blocked capacity/consent/auth tests
as blocked. Passing CI alone is not release acceptance.

See [the canary runbook](AZURE_CANARY.md) for the independent failure/cancellation
cleanup gate and its deliberately narrow scope.
