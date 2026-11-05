# Public validation evidence and blocked gates

This is a pre-release evidence record, not full Azure acceptance. Source
baseline `e30d0e043947a66d023ec3236f476d44d3d5f627` includes reviewed PRs
[1](https://github.com/ribumann/llmserving/pull/1) through
[16](https://github.com/ribumann/llmserving/pull/16). Each implementation PR
received independent agentic review and passing checks before merge.
Named test runs below retain their exact original source SHA; merged code is
not a claim that an earlier measurement came from a newer combined revision.
This includes privileged action/log masking hardening in
[PR 14](https://github.com/ribumann/llmserving/pull/14) and the separate genuine
browser gate in [PR 15](https://github.com/ribumann/llmserving/pull/15).

## Passed gates

| Gate | Exact evidence | Boundary |
| --- | --- | --- |
| Signed API auth and external SSO inputs | Merged `ba505da1f2d6463ddd29dd8b0d89f25f79b25e9d`; [Runtime](https://github.com/ribumann/llmserving/actions/runs/41928480988) | Signed-token tests, not actual Entra browser consent/session |
| Effective-SKU quota and honest power states | Merged `d5b851647589dd7b05b08f225f327e527571dcd7`; [Backend](https://github.com/ribumann/llmserving/actions/runs/41929501210), [Runtime](https://github.com/ribumann/llmserving/actions/runs/41929501372) | Quota/visibility is not physical capacity or warm inference |
| OIDC failure cleanup | Canary SHA `f52fcacffd8734de84cd4443744862982e8f9a71`; [deliberate failure](https://github.com/ribumann/llmserving/actions/runs/41922899569), [independent cleanup](https://github.com/ribumann/llmserving/actions/runs/41922982864) | Fixed managed identity absent; persistent group preserved |
| OIDC cancellation cleanup | Same canary SHA; [cancelled canary](https://github.com/ribumann/llmserving/actions/runs/41923092659), [independent cleanup](https://github.com/ribumann/llmserving/actions/runs/41923357529) | Not cleanup of billable resources |
| Genuine local-model API flow | [Merged PR 13](https://github.com/ribumann/llmserving/pull/13), `bca486590e5168a91f7bcd79e0bda5276f4ab964`; original measured SHA `2c2b65b95e5a39817c13cbb30d59099aaeb5dcba`, [Backend](https://github.com/ribumann/llmserving/actions/runs/41933197656), [Runtime/live evidence](https://github.com/ribumann/llmserving/actions/runs/41933201127) | CPU HTTP/PostgreSQL/Ollama, not browser/Azure/LLMPerf |
| Signed browser proxy transport | [Merged PR 10](https://github.com/ribumann/llmserving/pull/10), `119b39d03c87814cbbe9e78d6a261d75a14c0341`; tested SHA `d7cf35253ad19e17ed3d94aa019508ac1ef00106`, [Frontend](https://github.com/ribumann/llmserving/actions/runs/41931903053), [Runtime nginx smoke](https://github.com/ribumann/llmserving/actions/runs/41931907502), [Terraform](https://github.com/ribumann/llmserving/actions/runs/41932598360) | Synthetic signed-header transport, not real platform injection or Entra UX |
| Shared scoring foundation | [Merged PR 11](https://github.com/ribumann/llmserving/pull/11), `ec70fcd1c27638d0c36f93adc044035e98edc93b`; tested SHA `61183e9b97140729abec87293454aa3d1ff0293e`, [Backend](https://github.com/ribumann/llmserving/actions/runs/41935634541), [Runtime](https://github.com/ribumann/llmserving/actions/runs/41935637966) | 219 backend/77 worker tests and changed-worker Ruff, not complete durable parity |
| Fail-closed Terraform state persistence | [Merged PR 8](https://github.com/ribumann/llmserving/pull/8), `ab68d71b235c0a1bed3225356b656f60ed34c363`; tested SHA `a931e2238bdbb061358bb7809c70e7129f4dcc8a`, [Runtime](https://github.com/ribumann/llmserving/actions/runs/41974553102), [Terraform](https://github.com/ribumann/llmserving/actions/runs/41974555984) | 110 worker tests; manual transfer is not distributed locking or independent cancel recovery |
| Separate operator SSO tenant | [Merged PR 9](https://github.com/ribumann/llmserving/pull/9), `0acbe3d330b1a11fe2b6f79dc60d80fe9a0fe50f`; tested SHA `593b56331878d882cd5ed0084f6db94df2a7e669`, [Backend](https://github.com/ribumann/llmserving/actions/runs/41975399550), [Terraform](https://github.com/ribumann/llmserving/actions/runs/41975402414), [Runtime](https://github.com/ribumann/llmserving/actions/runs/41975405361) | 226 PostgreSQL tests, five native mocked plans; not live cross-tenant browser consent/injection |
| Real local browser/API inference | Merged `c165562db0b1a57a5dd96597727d048b3b54c679`; [fresh combined-main Runtime](https://github.com/ribumann/llmserving/actions/runs/41978810510), downloadable `real-local-api-evidence` | Actual Chromium renders a real CPU Ollama response/revision/timing; anonymous 401 and reload-history behavior verified, plus API golden/perf/cancel/teardown; local-demo/dev, not production proxy, Azure SSO or every UI journey |
| Ownership-safe worker state lease | Merged PR 16, `e30d0e043947a66d023ec3236f476d44d3d5f627`; reviewed source `0593a15987506463e6cb4b0e7dd2816ec8c3a03b`, [Runtime](https://github.com/ribumann/llmserving/actions/runs/41980021433) | 151 worker tests, private recovery capability before acquisition, concurrent/failure/owner-release checks; not actual Azure lease acceptance or all-layer native backend recovery |
| Genuine packaged CPU toolkit smoke | PR 17 source `bba9d867c0b26b8722b53822901065dfe8960c90`, tested synthetic merge `17a005336c0c817ad5301135ece105c9bedc902a`; [Runtime/evidence](https://github.com/ribumann/llmserving/actions/runs/41981822309), `genuine-local-toolkit-evidence` | Real lm-eval 0.4.13, one GSM8K document; real pinned ray-project LLMPerf two-request run; not durable routing, every benchmark/API journey or Azure acceptance |

The local flow exercised prompt, immutable versioned configuration/report
snapshots, two golden cases, single-stream and concurrency-10 performance,
missing-auth 401, a 50-case cancellation path, report retrieval and verified
local teardown. In the original measured run, golden quality was honestly
**one passed, one failed**, with
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

The table below retains original run
[`41933201127`](https://github.com/ribumann/llmserving/actions/runs/41933201127)
at `2c2b65b95e5a39817c13cbb30d59099aaeb5dcba`, not newer combined-main/browser
measurements: 2 CPU/2 GiB model container,
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

The vLLM adapter's optional exporter sample accepts finite physical GPU
utilization metrics, not KV-cache occupancy (`vllm:gpu_cache_usage_perc` or
`vllm:kv_cache_usage_perc`). Cache-only, missing or nonfinite samples leave GPU
utilization unavailable; cache samples cannot shadow a physical utilization
metric. Mocked exporter regressions validate selection and JSON-safe reporting,
not actual GPU telemetry or Azure hardware acceptance.

## Genuine CPU toolkit smoke

The separate packaged-runner gate above uses the same model manifest in an
owned two-CPU/two-GiB Ollama container. Evaluators run sequentially in separate
two-CPU/four-GiB containers. The compatible GSM8K chat-generation subset has
one effective document, zero few-shot examples, seed 42 and an eight-token
output cap. The two scoring-filter log records refer to that one document.
The actual output is nonempty; its strict score is **0/100**, honestly flagged
as a regression against a configured 75-point reference. That reference is
not a measured tiny-model baseline or a new calibration.

Actual ray-project LLMPerf commit
`f1d6bed47e4501b0e371082b41601b59ab55269f` completed two concurrency-one requests
with zero errors. Requested mean input/output lengths are 128/8 with zero
standard deviation and no explicit warmup. The model was already used by the
preceding benchmark. Its upstream sonnet prompt builder and
`hf-internal-testing/llama-tokenizer` accounting differ from the earlier native
Ollama smoke; these numbers are **not** an optimization comparison.

| Requests / errors | E2E p50 / p95 ms | TTFT p50 / p95 ms | ITL p50 / p95 ms | Upstream tokens/s |
| --- | --- | --- | --- | --- |
| 2 / 0 | 1038.63 / 1081.98 | 790.96 / 833.39 | 115.39 / 120.20 | 6.5582 |

These values belong only to source/run `17a0053...` / `41981822309`, not a
later combined revision. They establish genuine tool execution/result mapping,
not representative performance, model-quality success, production memory sizing,
GPU streams or authenticated Azure acceptance.

## Blocked or not yet demonstrated

### Performance-worker packaging boundary

The performance image now packages the **same canonical API runner source**
and genuine pinned LLMPerf commit/CLI/prompt data, following the evaluation
worker's source-copy pattern. Its CI job invokes the existing real CPU validator
inside that built image with `/app` explicitly on the Python import path,
checks the exact model manifest/tool provenance and requires two successful
concurrency-one requests with finite positive normalized metrics. Separate
`genuine-performance-worker-toolkit-evidence` artifacts identify their own
source/run; the historical backend numbers above are not new worker results.
Unlike the backend gate, the worker gate has no preceding benchmark, so its
first request may include model loading. Do not compare these short tests as
an API optimization measurement.

This is **packaging and canonical-runner execution**, not performance-worker
entrypoint, report, snapshot, cancellation/restart or ownership parity.
The existing worker entrypoint still uses its HTTP-only measurement path;
TTFT/ITL remain unavailable there. API execution/routing and its image are
unchanged. Complete lifecycle/report parity is required before switching
durable routing or removing proven API runners.

### Accepted run inputs

The API deep-copies accepted environment/configuration/definition data, and its
in-process golden, benchmark and performance execution reads the persisted
definition snapshot rather than reopening the mutable catalog. Benchmark model
selection also uses the accepted model snapshot. New snapshots retain the catalog
repository ID separately from its checkpoint revision. vLLM benchmarks select that
frozen served repository ID, matching prompt and performance behavior; Ollama
retains its local tag instead of sending a Hugging
Face repository ID. Older snapshots without the repository field retain their
accepted checkpoint fallback, not a fresh catalog lookup.

Editing or deleting a catalog definition after acceptance must not change that
run's inputs or report identity; missing/mismatched snapshots fail explicitly
rather than silently using today's
definition. Deferred API tests cover this selection boundary with mocked
execution, not genuine tool performance, process-restart recovery or durable
worker/report parity. Durable routing remains unchanged.

### Versioned workflow monitor

New Functions instances use `generic_orchestrator_v2`; the original named
orchestrator and activity sequence remain registered for existing history replay.
The new monitor finalizes terminal jobs through the authenticated API rather than
assuming a successful container exit produced a report. A worker's already-terminal
outcome is preserved only on the exact structured terminal-conflict response.
Cancellation/timeout wait for the SDK stop operation before finalization; stop,
authorization, stale-owner and unexpected callback failures remain visible rather
than forcibly releasing a lock. Existing v1 instances require drain/recovery
assessment before upgrading; versioning does not repair their stored outcomes.

Generator/HTTP-mocked tests and actual SDK registration/starter tests are source
and package evidence, not a live Durable task-hub/replay, Azure stop/cleanup,
exactly-once dispatch or complete durable-runner parity claim.

### Azure target boundary

Both original primary canary/cleanup workflows remain disabled. The user
selected the isolated fallback subscription as the future deployment target;
its operator-provisioned scoped identity/federation/main-only environment is
separate from historical primary proof. Reviewed fallback-only workflows are
available in [PR 23](https://github.com/ribumann/llmserving/pull/23); actual
failure/cancellation exchange and independent cleanup evidence must be recorded
by their operator, not inferred from source or credential-free CI.

The approved SSO registration is in that selected tenant, but still has no
bootstrapped credential/callback configuration or deployed platform acceptance.
The code keeps operator-auth and ARM/internal tenants separate even when their
configured values coincide. T4/H100 quota and subscription SKU restrictions in
checked fallback regions remain hardware gates; unrelated generic NC/NV quota
does not establish a compatible allocatable GPU. No quota request, additional
resources or GPU provisioning follows from these validations.

| Gate | Status and next prerequisite |
| --- | --- |
| Actual authenticated Azure browser/API | Blocked: isolated SSO app exists; private credential/approved consent/assignments, test-only vault, final callbacks and real platform signed-token injection still required; no policy bypass/sign-in retries |
| Clean cloud bootstrap | Pending: all-layer native remote state/locking/recovery, digest artifacts, all jobs/Functions deployment, existing-group parameterization, private network verification |
| Independent billable-resource cleanup | Pending: actual failure/cancellation cleanup plus fallback and absence checks before provisioning |
| Small-model Azure GPU acceptance | Not run; gated on auth, cleanup and bounded aggregate exposure |
| Complete durable run parity | Pending: proven golden/benchmark/genuine pinned LLMPerf/report semantics plus immutable snapshots, restart/duplicate/cancellation/stale/failure/owner-lock tests; routing remains disabled |
| Additional real browser/API benchmark journeys and calibration | Real local inference UI and one compatible packaged benchmark subset passed above; remaining real UI/API benchmark journeys and representative benchmark/LLMPerf calibration are pending; mocks remain distinct |
| Immutable full release/optimized API image | Not complete; do not remove proven API runners or call commit tags immutable |

No new billable Azure resource was created by this validation execution.
This is not a subscription cost query or a claim that existing resources cost
zero; reconcile delayed billing and persistent exposure before any future spend.
The original deployment, resources, state and identities remain outside scope.
