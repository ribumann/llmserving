# Operations, cost and recovery

This runbook describes safety requirements and implemented signals. It is not
evidence that a fresh Azure bootstrap, private networking, browser SSO or GPU
acceptance has passed. See [release evidence](RELEASE_VALIDATION.md).

## Health is not readiness or warmth

| Signal | Meaning | Not a guarantee |
| --- | --- | --- |
| `/healthz` | API process can answer liveness | Database, identity provider, model or Azure availability |
| `/readyz` | Bounded database `SELECT 1`; failures return 503 | Migrations/seeds, model readiness or authenticated UX |
| Persisted environment `ready` | Last lifecycle operation completed | VM still allocated, endpoint warm or deployment healthy now |
| VM `resourceState` | Actual power state or explicit lookup unknown | Quota, model health or loaded weights |
| `inferenceState=unverified` | Running VM has not established current inference readiness | Successful prompt execution |
| SKU/quota preview | Compatibility and requested-vCPU headroom | Physical allocation or a capacity reservation |

A paused/stopped database should make readiness fail, not turn liveness into a
restart loop. Resume through an approved operator path and wait for readiness
before user traffic; do not recreate or overwrite the database. Azure can
automatically restart stopped PostgreSQL servers at the service's stop limit.
Storage/backups remain billable. Verify the current service limits for the
selected server rather than assuming permanent pause.

## GPU, quota and memory

### GPU VM bootstrap and model-start failures

Terraform provisioning success does not prove that the GPU runtime is ready.
`infra/demo/cloud-init.tftpl` installs prerequisites, Docker and the NVIDIA
Container Toolkit in one fail-fast `/opt/llmserving/bootstrap.sh`, rather than
the early cloud-init package module. It retries only native APT lock-acquisition
errors: at most 30 attempts per operation, with 10-second waits and a shared
60-wait budget (10 minutes) across all package stages. Package network requests
have 30-second transport timeouts and no automatic acquisition retries.
APT/dpkg transactions are never forcibly timed out or killed. An idle
`unattended-upgr` process alone is **not** evidence of contention. Never remove
lock files, terminate package/security processes, disable agents or globally
reset cloud-init to work around contention.

The script clears stale readiness before each invocation and writes
`/opt/llmserving/bootstrap.ready` only after runtime configuration and `docker info`
succeed. A failed stage writes `bootstrap.failed` and emits a stage/exit-code
diagnostic without dumping command output. Optional immutable-image cache warming
has a separate 120-second limit and is not required for readiness.

The model job waits up to 25 minutes for explicit bootstrap readiness, failing
immediately on `bootstrap.failed`. The launcher independently refuses startup
without readiness and requires a working GPU driver (up to 10 minutes) and Docker
daemon before starting vLLM. Readiness markers are not a substitute for subsequent
model health checks. Old VMs without this bootstrap contract fail closed; this
change does not automatically repair/replay cloud-init on existing machines.
Any recovery is a separately approved operator action, not a PR deployment.

Classic Azure RunShellScript can report `ProvisioningState/succeeded` for a failed
shell command. The shared job helper now requires an exact fresh per-invocation
stdout completion marker, emitted only after explicit fail-fast Bash succeeds.
Benign stderr is allowed; missing, truncated, stale or stderr-only markers fail
before model health polling. SDK failures and unconfirmed completion produce a
fixed output-free error. Do not copy Run Command inputs, raw SDK exceptions or
stdout/stderr into logs, callbacks or reports: transient model credentials may
appear there. This is a credential-free tested contract, not live GPU acceptance.

GPU deallocation stops VM compute billing, not disk, snapshot, network/NAT,
registry, database or monitoring charges. A stopped-but-allocated VM may still
incur compute charges. Deallocation releases physical capacity: later startup
can fail despite quota, and weights/cache may need reloading. Report cold start
separately from steady-state inference.

Quota arithmetic uses the **effective requested SKU's vCPU count**. Regular
requires family and regional quota; Spot uses its applicable low-priority quota.
Missing SKU/quota metadata stays unknown. Visibility and sufficient quota never
establish physical capacity. Bound region/SKU retries; do not silently substitute
an expensive GPU family or change the requested deployment.

Spot can be evicted without warning and is not durable compute. Preserve
immutable model/configuration/report provenance outside the VM and make failure
visible. Do not call an interrupted report complete.

VRAM is not system RAM. Approximate weight memory starts with
`parameter_count * bits_per_weight / 8`, then adds runtime/quantization overhead,
KV cache, context length, concurrency and temporary buffers. A model fitting
its weights does not prove a concurrency-10 workload fits. Validate the exact
quantization/revision/context on the chosen GPU; use one small T4-class GPU
first only after all auth/cleanup/budget gates pass.

## Exposure ledger

For the authorized validation effort the aggregate Azure estimate cap is
**US$500**, with a conservative **US$100 contingency** reserved before new
commitments. This is not a guarantee or hard billing stop.

Track committed resources and delayed billing together: region/SKU, hourly
rates, quantity, maximum runtime including retries, persistent daily storage/
network/database charges and cleanup deadlines. Reconcile resource inventory
and actual cost when available. Budget alerts can lag and do not stop compute.
Stop provisioning when remaining exposure cannot be bounded.

Use exact ownership tags, a run owner and expiry, bounded retry/runtime limits,
and independent cleanup. No reserved capacity, unbounded scale or automatic
SKU/region escalation. Canary identity tests do not authorize GPU expenditure.

## Cleanup and cancellation

Independent server-side cleanup must survive failed/cancelled provisioning and
an offline operator. A workflow `finally`/`always()` step alone is insufficient:
use a separately triggered completion workflow and scheduled fallback, then
actually exercise failure **and cancellation**.

The [OIDC canary](AZURE_CANARY.md) proves only cleanup of its fixed nonbillable
managed identity. Independent cleanup of billable app/VM/network/database
resources has **not** been demonstrated and must be implemented/tested before
creating them.

Before each create/delete, check the exact subscription and live group
ownership tags; before deletion also verify the exact resource ID, type,
name, tags and run owner against trusted protected-main configuration.
Never derive privileged targets from untrusted artifacts. Delete only the
specifically owned resources; preserve persistent test groups, role grants,
original applications and other runs' resources. Verify absence and inventory
residual disks, network resources, images, secrets and database/storage costs.
Never use broad group deletion, wildcard deletion or subscription-wide cleanup.

## Rollback and incidents

Record a deployment manifest before changes: reviewed source SHA, image digests,
Functions ZIP checksum, Terraform/provider versions and protected state keys,
database migration level, exact model revision/digest, configuration version
and approved identity/network inputs. Do not include secrets.

Rollback app revisions to known-good image digests through the normal protected
deployment path. Check database compatibility first: an app rollback is not a
database downgrade or a recovery of deleted data. Preserve encrypted backups/
state versions and test restore in isolation. Never force-unlock another
operation without identifying its owner and proving it is stale.

On auth/policy denial, unexpected ownership, suspected secrets or an unbounded
cost risk: stop mutations, preserve safe evidence and continue only nonblocked
read-only/local work. Do not compensate by weakening auth or expanding roles.
