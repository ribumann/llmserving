# Main cloud acceptance

This is an opt-in **real deployed HTTPS** suite, not a local server or a fixture
suite. The existing `e2e/tests` interception tests remain UI contract tests;
`playwright.live.config.ts` remains the genuine **local CPU/Ollama** test. Neither
is evidence for main Azure. Historical golden **12/12** and older-environment
performance numbers are not main acceptance.

## Inputs and permissions

Use Python 3.11+ for the headless API harness. Copy `config.example.json` to an
ignored `config.json` here and replace every placeholder. Supply the actual main
API URL (including `/api` when using the frontend proxy), an already provisioned
**dedicated** Azure ItalyNorth environment, a real ungated model/catalog entry,
its immutable 40-character Hugging Face model commit, the deployed full source
SHA and a deployment run URL/release digest. Source provenance is operator-supplied:
the current `/healthz` API does **not** independently expose the deployed commit.
Verify that provenance against the release before running.

Set `LIVE_OPERATOR_TOKEN` to a short-lived, authorized Entra **operator user**
bearer token using your approved credential mechanism. Do not put credentials in
the configuration, shell history, source, PR, or evidence. The harness does not
accept demo headers, acquire credentials, provision resources, modify DNS, or
run Azure commands. Redirects are rejected rather than forwarding bearer tokens.

Set `allowConfigWrites=true` only after authorizing append-only configuration
writes. Set `allowDeploy=true` only after authorizing model deployment into that
environment; this replaces its active deployment. No existing environment is
created, torn down or deleted. Gated model credentials are deliberately outside
this slice.

Choose **explicit** `maxP95LatencyMs` and `minTokensPerSecond` for both performance
policies; the example leaves these `null` to prevent invented acceptance limits.
Golden defaults to the existing reviewed `demo-factual-qa-v1`, version 1, exactly
12 actual outcomes, pass rate 1.0, no errors/skips/incomplete cases. Performance
defaults to zero failures. These are prospective policies, not prior results.

Before setting `seededWorkloadsVerified=true`, verify the deployed DB contains
the unmodified definitions from `backend/src/performance/seed_workloads.py` at
the supplied deployed commit:

| Workload | Concurrency | Warmup | Requests | Safety limits |
|---|---:|---:|---:|---|
| `llmperf-single-stream-v1` | 1 | 3 | 25 | 40 requests, concurrency 1, 600 seconds |
| `chatbot-concurrent-10-v1` | 10 | 5 | 50 | 80 requests, concurrency 10, 600 seconds |

Both use the existing LLMPerf 550 +/- 150 input / 150 +/- 10 output token profile.
The public workload API exposes version and concurrency, **not all safety fields**;
the flag records an operator attestation, not an independently verified API fact.
Do not run against unverified/mutated definitions. Runs reuse the actual backend
golden evaluator and LLMPerf runners, not fabricated client-side metrics.
Completed performance reports are also checked for actual runner, concurrency,
request/safety bounds and metric units; golden aggregates must match the actual
unique case outcomes, not merely a reported pass-rate number.

## Execute independently staged checks

From the repository root, with the credential already in the environment:

```sh
python3 e2e/live/cloud/acceptance.py \
  --config e2e/live/cloud/config.json --stage control \
  --evidence e2e/live/cloud/control.evidence.json

python3 e2e/live/cloud/acceptance.py \
  --config e2e/live/cloud/config.json --stage gpu \
  --evidence e2e/live/cloud/gpu.evidence.json
```

`control` checks anonymous health, DB readiness, rejection of anonymous protected
requests, actual operator authentication, Azure environment/catalog identity,
then writes and exactly rereads model/inference configurations. It does not need
a GPU or performance thresholds. `gpu` repeats those checks, validates all
thresholds **before writes**, deploys a real model revision, polls readiness,
submits a real prompt, runs golden and sequential single/concurrent workloads,
then rereads stored run history, run detail and exact reports. Every operation
has request/poll deadlines. A timed-out run receives a cancellation request; that
request is recorded and is **not** claimed as confirmed cancellation. Deployment
has no cancellation endpoint: a timed-out deployment needs operator follow-up.

Exit codes: **0** all requested checks passed, **1** a check failed, **2** blocked.
Missing required inputs never produce success. Evidence is written on failures,
including actual HTTP status/body/request IDs, elapsed times, resources created,
report/case/metric payloads, configured thresholds, model pin, source and harness
hash. Bearer tokens are redacted; evidence is atomically written owner-only. Treat
evidence as sensitive application data and review it before sharing.

### Browser (actual deployed frontend, no request interception)

Reuse the existing Playwright dependency and the genuine local browser test's
exercise selectors/assertions, but target the deployed frontend with no dev
server, route mocks or substituted identity headers. Obtain an authorized SSO
browser storage state through the real login flow. Keep it outside source control.
Set `LIVE_BROWSER_URL` (actual HTTPS frontend), `LIVE_STORAGE_STATE` (state path),
`LIVE_CLOUD_CONFIG` (config path), `LIVE_API_EVIDENCE` (GPU evidence path), and
`LIVE_BROWSER_EVIDENCE_FILE` (output path). The API token alone does not log the
browser in; expired/missing SSO or incompatible auth wiring fails the test.

```sh
cd e2e
npm ci
npx playwright install chromium
npx playwright test --config live/cloud/playwright.config.ts
```

Browser assertions cover rendered real response, exact revision, TTFT, no page
errors, reload retaining deployment but clearing ephemeral prompt history.
Authenticated tracing/video/screenshots are disabled to avoid credential capture.
Browser success is its own evidence, not a claim that the entire deployment passed.

## Cleanup and restart: current API gaps, never silently green

Configuration history is append-only: **no DELETE endpoint exists**. Therefore the
cleanup check is explicitly **blocked**, even when write/read passed. Created IDs
are recorded immediately; an authorized operator must arrange scoped DB cleanup
of these test records. Do not run generic environment teardown as a substitute:
it can delete Azure resources and does not prove configuration cleanup.

No application restart API exists. After an independently authorized application
restart, retain the actual restart operation evidence and rerun:

```sh
python3 e2e/live/cloud/acceptance.py \
  --config e2e/live/cloud/config.json --stage verify-persistence \
  --prior e2e/live/cloud/gpu.evidence.json \
  --evidence e2e/live/cloud/after-restart.evidence.json
```

This verifies exact persisted configurations, runs, history and reports through
fresh HTTP reads. **It does not itself prove a restart occurred.** Associate the
operator's actual restart evidence with this result. A browser reload is also
not an application restart. `fullAcceptance` deliberately remains `false`: current
cleanup/restart gaps, separate browser evidence, independently verified deployment
provenance and safety attestation must be resolved/reviewed before declaring main
accepted. GPU failure never erases successful control-plane evidence.

## Offline harness checks (not cloud evidence)

```sh
python3 -m unittest discover -s e2e/live/cloud -p 'test_*.py'
```

These use explicit offline stubs to verify the harness contract, failure handling,
threshold boundaries, cancellation and evidence. They never claim a live run.
Runtime CI runs these contracts in its existing `jobs` job on every pull request
and push to main, without credentials or path filters. Live cloud/browser checks
remain opt-in and are not represented by that CI success.
