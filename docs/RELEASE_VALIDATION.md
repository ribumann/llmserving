# Public validation evidence and blocked gates

This is a pre-release evidence record, not full Azure acceptance. Source
baseline `d5b851647589dd7b05b08f225f327e527571dcd7` includes reviewed PRs
[1](https://github.com/ribumann/llmserving/pull/1) through
[7](https://github.com/ribumann/llmserving/pull/7). Feature-branch evidence below
is explicitly **not merged/released behavior** at this baseline.

## Passed gates

| Gate | Exact evidence | Boundary |
| --- | --- | --- |
| Signed API auth and external SSO inputs | Merged `ba505da1f2d6463ddd29dd8b0d89f25f79b25e9d`; [Runtime](https://github.com/ribumann/llmserving/actions/runs/41928480988) | Signed-token tests, not actual Entra browser consent/session |
| Effective-SKU quota and honest power states | Merged baseline; [Backend](https://github.com/ribumann/llmserving/actions/runs/41929501210), [Runtime](https://github.com/ribumann/llmserving/actions/runs/41929501372) | Quota/visibility is not physical capacity or warm inference |
| OIDC failure cleanup | Canary SHA `f52fcacffd8734de84cd4443744862982e8f9a71`; [deliberate failure](https://github.com/ribumann/llmserving/actions/runs/41922899569), [independent cleanup](https://github.com/ribumann/llmserving/actions/runs/41922982864) | Fixed managed identity absent; persistent group preserved |
| OIDC cancellation cleanup | Same canary SHA; [cancelled canary](https://github.com/ribumann/llmserving/actions/runs/41923092659), [independent cleanup](https://github.com/ribumann/llmserving/actions/runs/41923357529) | Not cleanup of billable resources |
| Genuine local-model API flow | Feature branch `test/real-local-model`, `2c2b65b95e5a39817c13cbb30d59099aaeb5dcba`; [Backend](https://github.com/ribumann/llmserving/actions/runs/41933197656), [Runtime/live evidence](https://github.com/ribumann/llmserving/actions/runs/41933201127) | Independently reviewed; CPU HTTP/PostgreSQL/Ollama, not browser/Azure/LLMPerf |
| Signed browser proxy transport | Feature branch `fix/browser-auth-transport`, `d7cf35253ad19e17ed3d94aa019508ac1ef00106`; [Frontend](https://github.com/ribumann/llmserving/actions/runs/41931903053), [Runtime nginx smoke](https://github.com/ribumann/llmserving/actions/runs/41931907502), [Terraform](https://github.com/ribumann/llmserving/actions/runs/41932598360) | Independently reviewed; synthetic signed-header transport, not real platform injection or Entra UX |
| Shared scoring foundation | Feature branch `refactor/shared-runner-semantics`, `7c28be8f6ab5e08a82db26accf34d1456f41ec9c`; [Backend](https://github.com/ribumann/llmserving/actions/runs/41934042604), [Runtime](https://github.com/ribumann/llmserving/actions/runs/41934046001) | Independently reviewed; 219 backend/77 worker tests, not complete durable parity |

The local flow exercised prompt, immutable versioned configuration/report
snapshots, two golden cases, single-stream and concurrency-10 performance,
missing-auth 401, a 50-case cancellation path, report retrieval and verified
local teardown. Golden quality was honestly **one passed, one failed**, with
zero errored/skipped cases; the tiny model answered `0+1` incorrectly. The
passing flow checks integration, not a model-quality threshold.

## Fresh CPU performance smoke

Exact model: `qwen2.5:0.5b-instruct`, GGUF Q4_K_M, 494.03M parameters,
397821319 bytes, manifest
`a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67`.
The manifest was checked before inference and after deployment.
Ollama 0.13.5 image:
`ollama/ollama@sha256:2c9595c555fd70a28363489ac03bd5bf9e7c5bdf2890373c3a830ffd7252ce6d`.
Disposable PostgreSQL image:
`postgres@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab`.

Same current-head Runtime run linked above; 2 CPU/2 GiB model container,
`OLLAMA_NUM_PARALLEL=2`, fixed prompt `Count from one to five.`, output budget
8 tokens, one warmup outside each measured workload, 120-second request safety
limit. Client concurrency 10 includes server queueing; it is **not ten GPU
streams**. Input-token distribution was not synthesized.

| Client concurrency | Measured requests | Failures | E2E p50 / p95 ms | TTFT p50 / p95 ms | ITL p50 / p95 ms | Aggregate tokens/s |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2 | 0 | 310.49 / 322.47 | 120.31 / 121.69 | 29.18 / 32.11 | 25.7394 |
| 10 | 10 | 0 | 2003.14 / 2691.71 | 1744.93 / 2437.55 | 39.08 / 52.41 | 29.3604 |

These are short API smoke observations, not statistically representative
performance claims or genuine ray LLMPerf results. TTFT is client-observed
first content; ITL is based on streamed content-chunk gaps (with the adapter's
per-token fallback), not independent tokenizer timestamps. Throughput uses
reported completion tokens over measured wall time. GPU utilization is
explicitly unavailable, not zero. No compatible lm-eval benchmark subset was
run in this flow.

## Blocked or not yet demonstrated

| Gate | Status and next prerequisite |
| --- | --- |
| Actual authenticated Azure browser/API | Blocked: approved isolated SSO app/credential/consent/assignments, final callbacks and real platform signed-token injection; no policy bypass/sign-in retries |
| Clean cloud bootstrap | Pending: remote state/locking, digest artifacts, all jobs/Functions deployment, existing-group parameterization, private network verification |
| Independent billable-resource cleanup | Pending: actual failure/cancellation cleanup plus fallback and absence checks before provisioning |
| Small-model Azure GPU acceptance | Not run; gated on auth, cleanup and bounded aggregate exposure |
| Complete durable run parity | Pending: proven golden/benchmark/genuine pinned LLMPerf/report semantics plus immutable snapshots, restart/duplicate/cancellation/stale/failure/owner-lock tests; routing remains disabled |
| Real browser full-stack and small benchmark subset | Not run; API-mocked browsers and real API smoke are distinct evidence |
| Immutable full release/optimized API image | Not complete; do not remove proven API runners or call commit tags immutable |

No new billable Azure resource was created by this validation execution.
This is not a subscription cost query or a claim that existing resources cost
zero; reconcile delayed billing and persistent exposure before any future spend.
The original deployment, resources, state and identities remain outside scope.
