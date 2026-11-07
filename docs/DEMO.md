# Demo and launch walkthrough

[Docs index](README.md) / [architecture](ARCHITECTURE.md) /
[results and limitations](RELEASE_VALIDATION.md)

## Public demo

Open [Serving Lab](https://servinglab.liberatetheinnerchild.net). No account is
needed to browse saved, sanitized data across Overview, Provision, Deploy,
Exercise, Retune, Quality/Performance, Compare, History and Teardown.
Choose an environment, inspect deployment/configuration lineage, follow a run to
its report, and reopen a saved comparison. A report ID is not a run ID; operator
Compare uses the **Result report ID**.

Public reports show aggregate counts/scores and finite performance metrics with
units and conditions, not raw cases, prompts, responses, private addresses or
infra identities. Empty means no published persisted record, not zero quality
or a fabricated result. Public reads do not wake a VM, test model health or run
provider checks. Disabled controls are intentional; there is no anonymous
inference playground.

Signing in uses the existing Microsoft flow and returns to the requested route.
Only verified operators receive action pages, and API authorization still checks
their identity/policy/ownership. A sign-in/identity-provider failure must not block
public data independently; database/public API failures have their own retry state.
Do not request raw tokens or paste credentials into a browser's storage.

## Local operator walkthrough

Complete [root local setup](../README.md#local-development) with a disposable
PostgreSQL database, local-demo/loopback auth, exact Vite CORS origin and a running
local Ollama model. Then use the same application workflow:

1. **Provision:** choose Local (Ollama). Azure preview/provision is a different,
   billable workflow requiring approved private operator setup.
2. **Deploy:** select the local model, save model/inference configuration versions
   and explicitly deploy. Wait for the revision result.
3. **Exercise:** send a small prompt and inspect its revision/timing. Browser
   prompt history clears on refresh/close; it is not an archival store.
4. **Quality / Performance:** choose an existing seeded definition and run a
   bounded small workload. Wait for a terminal status and inspect completeness,
   failures, workload and snapshot lineage before interpreting numbers.
5. **Retune / Compare / History:** create a new configuration and explicitly
   redeploy to change traffic; compare compatible saved result report IDs.
6. **Teardown:** preview the exact environment, then confirm only its intended
   resources. Local teardown does not imply cloud resource cleanup.

Standard benchmarks require `python -m pip install -e '.[evaluation]'` from
`backend`; the genuine vLLM performance toolkit is separately packaged by
[`backend/Dockerfile`](../backend/Dockerfile). Installing a random `llmperf` PyPI
package is not equivalent. Use [testing](TESTING.md) for actual local/toolkit gates.

## Before an Azure presentation

Use the existing authorized deployment, not a default Terraform apply.
Privately verify the exact target and ownership, database readiness, operator
session, active revision, actual VM power state and one small real prompt.
Quota/headroom is not physical capacity; persisted READY is not model warmth.
Plan a cold-start and interruption explanation for Spot; do not silently switch
to an expensive family or bypass the subscription's Regular-policy denial.

Confirm PostgreSQL stays available under the managing environment's external
shutdown policy; [database availability](DATA_AND_RECOVERY.md#database-availability)
distinguishes an explicit stop from idle auto-pause. Keep configurations/reports
and tested private backups outside the inference VM.

## Interpreting results

| Field | Interpretation / caveat |
| --- | --- |
| Quality counts and pass rate | Read passed, failed, errored, skipped and incomplete together. A completed test can honestly fail quality. Public pass rate is the persisted numeric aggregate, not a new score. |
| Benchmark score / baseline / delta | Interpret the exact accepted benchmark subset, version, scoring metric and configured threshold. A small subset is not full-suite calibration; a reference baseline is not necessarily a measured run. |
| TTFT | Client-observed time to first content, including transport and queueing. It is not a GPU kernel-only latency. |
| ITL | Toolkit/adapter-normalized inter-token latency. Ollama uses streamed content-chunk gaps with its fallback; this is not independent tokenizer timestamp telemetry. |
| E2E latency | Request completion latency; p95 is not an average or an SLA. Tiny samples produce unstable quantiles. |
| Throughput | Aggregate generated-token rate over measured wall time, not requests/sec or the sum of per-request token rates. Client concurrency includes server queueing. |
| Warm-up | Configured `warmup` alone is not evidence of execution. New vLLM operator reports have observed `warmupExecution`; public projections intentionally omit that internal detail. Do not retroactively certify old reports. |
| Failures / completeness | Include failure count and measured request total; interrupted/partial/cancelled reports are not complete successes. |
| GPU utilization | Public projections mark it unavailable. Operator samples must use physical utilization metrics, not KV-cache occupancy. Missing is not zero. |
| Comparability | Keep engine/model/config/tool/workload/subset/retention provenance aligned. Different CPU/GPU paths or tokenizer accounting are not an optimization comparison. |

The dated Qwen3-4B example in [release evidence](RELEASE_VALIDATION.md) is a demo
observation, not a performance promise. Do not publish raw operator reports to
explain a number; use their safe aggregate projection.
