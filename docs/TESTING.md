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

Without `TEST_DATABASE_URL`, the seven real database tests explicitly skip.

The live CPU workflow also runs `e2e/live` through the separate
`playwright.live.config.ts` against its actual deployed local model. No HTTP
routes are intercepted. The browser submits a prompt, verifies the rendered
response and revision, confirms history clears on reload, and checks anonymous
API access is rejected. It uses explicit loopback-only `local-demo` test auth
and dev-mode frontend configuration, not Azure SSO or the production proxy.
Browser failure propagates to the API test while its teardown still runs;
browser evidence and failure traces accompany `real-local-api-evidence`.
The existing nine API-mocked scenarios remain a separate regression suite.
Hosted Backend CI always sets it. An invalid configured URL, failed connection,
missing migration/seed, or unexpected SQLSTATE fails rather than falling back to
SQLite or an in-memory session.

## Functions and jobs

Use separate Python environments for backend and jobs: their current Azure
Compute SDK ranges differ. Runtime CI installs every worker's requirements in
the job-test environment, and Functions in its own job.

The worker suite includes `tests/test_gpu_bootstrap.py`, which executes the
shipped cloud-init Bash and Run Command wrapper with synthetic commands and
temporary filesystem roots. Bash is required (Git Bash on Windows); absence
fails coverage rather than silently skipping it. No package install, GPU,
network or cloud operation is performed. These tests cover lock-only retries,
retry exhaustion, terminal failures, idempotent readiness, startup gating and
Bash fail-fast. `tests/test_run_command_contract.py` covers SDK objects and classic
combined streams, unique/exact stdout markers, benign stderr and secret-safe
failures. Run the focused set or the full worker suite from `jobs/`:

```sh
python -m pytest -q tests/test_gpu_bootstrap.py tests/test_run_command_contract.py tests/test_azure_demo_vm.py tests/test_model_deployment.py tests/test_retained_vm_scope.py
python -m pytest -q tests
```

These are executable local contract tests, not authenticated Azure/GPU
acceptance or permission to replay cloud-init or deploy.

```sh
cd functions
python -m pip install pytest pytest-asyncio -r requirements.txt
python -m pytest -q tests
python -c 'import function_app; assert len(function_app.app.get_functions()) >= 8'
```

The Functions ZIP includes dependencies under `.python_packages/lib/site-packages`.
Packaging selects binary wheels for CPython 3.11, Linux AMD64 and a glibc 2.28
baseline (also accepting compatible manylinux2014 wheels), rather than using
the newer CI runner's native platform. After ZIP extraction, a network-isolated
Python 3.11 Debian Bullseye container imports the native cryptography/cffi and
Azure identity/Container Apps dependencies, then enumerates function registrations.
This catches ABI failures hidden by registration-only imports on the build host.
The ZIP is an ordinary CI artifact, not proof of Azure host deployment. It
expires after seven days.

Worker unit tests isolate the Terraform runner's managed-identity login from
Terraform command behavior; dedicated tests separately assert missing-identity
and denied-login failures stop before Terraform and that successful login uses
only `az login --identity`. Production authentication is not disabled for tests.

Saved-state ownership checks also accept the demo module's root
`terraform_data.region_guard` from Terraform's built-in provider, so later
apply/destroy operations can read the module's own state. Other managed
`terraform_data` names, nested modules, and foreign providers remain rejected.

Terraform state regressions also exercise rejected partial/cloud configuration,
denied identity/download/upload, malformed state, BlobNotFound versus missing
container, required destroy state, state-owner mismatch, partial apply failure/
timeout persistence, and output failures. State failure cannot become a completed
callback or silently start from empty state. Fixtures explicitly remove inherited
host markers for local-only cases; separate cloud-marker cases require state.
These are credential-free HTTP/CLI fixtures, **not** live blob locking or cloud
recovery certification. See [the state recovery boundary](TERRAFORM_STATE.md).

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

Manual main-only Runtime CI can additionally export checked release-candidate
archives (`package_release=true`). Ordinary CI keeps this off. The complete
manifest requires every runtime job to pass; a partial attempt is not a release.
Credential-free tests cover exact source/run/attempt binding, all eight required
components, corrupted/missing archives, path/symlink rejection and the opt-in
workflow guards. The archive SHA-256 and Docker config ID do not establish an
actual registry pull digest, signed provenance or Azure readiness. See
[candidate handling and limits](AZURE.md#credential-free-checked-artifact-candidates).

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
OLLAMA_EXPECTED_DIGEST=a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67 \
python -m pytest -q -s -o addopts="" tests/integration/test_live_ollama.py
```

The live API process must separately use `AUTH_MODE=local-demo APP_ENV=test`
and the same database/Ollama URLs. Required `OLLAMA_EXPECTED_DIGEST` rejects an unexpected
model version; `FULLSTACK_EVIDENCE_FILE` saves only this synthetic run's evidence.
The test covers real prompts, two golden cases, immutable versioned configuration,
single-stream (two requests) and concurrency-10 (ten requests) HTTP performance,
negative authentication, cancellation, reports and local environment teardown.
Golden failures are recorded honestly rather than requiring a tiny model to
achieve a predetermined quality score. One real warmup precedes each measured
performance workload and is excluded from throughput counts/timing.
Golden execution merges the accepted inference snapshot's generation settings
with each case's explicit overrides. Queued runs must not read later configuration
or dataset edits; `tests/integration/test_run_input_snapshots.py` covers precedence,
token limits, temperature and snapshot preservation.

These are fixed-prompt CPU smoke workloads, not standardized LLMPerf results,
benchmark acceptance or Azure release acceptance. The hosted workflow separately
exercises the real browser against the same live deployment as described above. The
Ollama runner does not synthesize a specified input-token distribution. API-mocked
Playwright tests remain a separate boundary. Cloud authentication, real Azure
GPU/networking and independently owned billable-resource cleanup require their
own evidence.

## Release evidence

The backend image gate also exercises its actual packaged `LmEvalRunner` on
one compatible GSM8K chat-generation sample and `LlmPerfRunner` using the exact
genuine pinned upstream tool, on the owned CPU Ollama model. It reuses the
already-built image and runs toolkit containers sequentially with two-CPU/four-GiB
limits, a separate two-GiB model server, bounded wall time, no GPU or cloud
credentials, and explicit cleanup. Model digest, actual effective sample/request
counts and normalized result shapes are required. Tiny-model benchmark quality
may fail; inference/network/tool failures may not be replaced by mock results.
Artifacts contain quantitative fresh synthetic evidence, not dataset questions,
private data or credentials. This gate does not enable durable routing or certify
Azure, statistically representative performance or a full benchmark suite.

Report exact commit/image/model versions, workload, counts/failures and measured
latency/throughput for fresh real-model tests. Historical metrics and mocked
outputs cannot replace a missing run. Record blocked capacity/consent/auth tests
as blocked. Passing CI alone is not release acceptance.

See [the canary runbook](AZURE_CANARY.md) for the independent failure/cancellation
cleanup gate and its deliberately narrow scope.

## Separate operator and deployment tenants

Signed-token regressions exercise a valid external operator tenant, rejection
of deployment-tenant operator tokens, unchanged domain/audience enforcement,
and internal managed-identity tokens that must still use the deployment issuer.
Keys are synthetic, but signature/issuer/audience/tenant checks are real.
Unset operator tenant preserves existing behavior; invalid explicit tenant
configuration fails rather than selecting a broader issuer.

Infra CI also runs five native `terraform test` **mocked-provider plans** in
`infra/control/tests/sso_tenant.tftest.hcl`. They inspect both actual Easy Auth
JSON bodies and actual backend environment fields, verify external mode creates
no application/password/SP, preserve managed defaults and reject an invalid
tenant or an explicit tenant without external app inputs. Every Azure/directory
provider is mocked and shared-state data is overridden; there is no live plan,
app/secret/redirect mutation or cloud credential. These tests do not establish
real Entra consent, platform injection or browser acceptance.
