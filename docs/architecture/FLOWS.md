# Runtime sequence flows

[Architecture map](../ARCHITECTURE.md) / **behavior depth** /
[containers](CONTEXT.md#runtime-containers) / [components](COMPONENTS.md) /
[deployment and recovery](DEPLOYMENT.md)

## Public read versus operator action

```mermaid
sequenceDiagram
    actor Visitor
    participant UI as React UI / Nginx
    participant API as FastAPI control plane
    participant DB as PostgreSQL
    participant Entra as Operator Entra tenant
    Visitor->>UI: Open any screen
    UI->>API: Protected GET /session
    API-->>UI: Unauthenticated or unavailable
    UI->>API: GET /public persisted projection
    Note over UI,API: Public proxy is GET-only and strips identity tokens
    API->>DB: Read persisted safe fields
    DB-->>API: Saved rows
    API-->>UI: Allowlisted summary without provider calls
    Visitor->>UI: Explicit sign-in
    UI->>Entra: Easy Auth sign-in under tenant policy
    Entra-->>UI: Approved session and actual signed ID token
    UI->>API: Protected request with verified-token transport
    API->>API: Validate signature, issuer, audience, time, user policy
    API-->>UI: Authorized result or explicit 401 / 403 / 503
```

A platform token header is transport, not proof of identity. Backend validation
and route/owner checks remain mandatory. Internal callbacks instead use their
own managed-identity allowlist. Actual token injection/callbacks/consent must
be verified for each target; local signed-token tests cannot establish it.
See [the complete contract](../AUTHENTICATION.md).

## Provision and teardown

```mermaid
sequenceDiagram
    actor Operator
    participant API as FastAPI control plane
    participant DB as PostgreSQL
    participant Func as Durable Functions
    participant Job as Terraform runner
    participant Blob as Private state storage
    participant ARM as Azure Resource Manager
    Operator->>API: Preview exact profile, region, SKU, priority
    API-->>Operator: Quota and compatibility, capacity unknown
    Operator->>API: Create environment
    API->>DB: Save environment, operation and accepted provider scope
    API->>Func: Start provision workflow
    Func->>Job: Dispatch and monitor Terraform execution
    Job->>Blob: Private attempt record, owned lease, state download
    Job->>ARM: Apply reviewed demo module
    Job->>Blob: Persist state, validate outputs, release lease
    Job->>API: Authenticated terminal callback
    API->>DB: Reconcile environment state and owned lock
    Operator->>API: Poll environment
    API-->>Operator: Persisted lifecycle and operator context
    Note over Job,ARM: Teardown reuses saved scope and state, retains group
```

VM provisioning includes fail-fast cloud-init, a bootstrap gate waiting for
cloud-init completion, then the managed NVIDIA extension. A successful Terraform
VM creation is not a ready model. Failed/uncertain mutations retain state/lease
for recovery, not a success callback. Cancellation/timeout in the versioned
Functions monitor waits for SDK stop before terminal finalization; unexpected
callback/stop/ownership errors remain visible.

## Deploy a model

```mermaid
sequenceDiagram
    actor Operator
    participant API as FastAPI control plane
    participant DB as PostgreSQL
    participant Job as Model job
    participant Func as Durable Functions
    participant VM as Private GPU VM / vLLM
    Operator->>API: Save model and inference configuration versions
    API->>DB: Persist versions
    Operator->>API: Deploy selected versions
    API->>DB: Create revision and acquire operation lock
    API->>Job: Pre-dispatch exact model repo, revision, settings and transient credential
    API->>Func: Monitor pre-dispatched execution name
    Note over API,Func: HF token never enters Durable history
    Job->>VM: Wait for bootstrap then start vLLM via Run Command
    VM-->>Job: Fresh completion marker
    Job->>VM: Poll model health
    Job->>API: Authenticated completion or failure
    API->>DB: Reconcile revision, active pointer and lock
    Operator->>API: Poll revision and health
```

Dispatch itself starts in an API thread pool before Durable monitoring. That
handoff is not demonstrated exactly-once/restart recovery. HF credentials must
not enter DB, Terraform, logs, public evidence or Durable history; cloud job/Run
Command execution-metadata retention still needs private review. Never dump raw
SDK output to diagnose credential-bearing requests.

## Interactive inference

```mermaid
sequenceDiagram
    actor Operator
    participant UI as React UI
    participant API as FastAPI control plane
    participant DB as PostgreSQL
    participant Engine as vLLM or Ollama adapter
    participant Model as Active inference endpoint
    Operator->>UI: Submit prompt with generation parameters
    UI->>API: Authenticated POST environment prompts
    API->>DB: Resolve active revision and environment lock
    API->>Engine: Submit using accepted revision and parameters
    Engine->>Model: OpenAI-compatible inference request
    Model-->>Engine: Text, usage and timing
    Engine-->>API: Normalized prompt result
    API-->>UI: Response, revision and metrics
    Note over UI,DB: Session-only UI history, no public inference
```

Busy, unavailable or unready environments fail explicitly. Persisted READY is
not a live health guarantee; operators must distinguish stopped/deallocated VM,
running-but-unverified model and successful real inference.

## Quality, performance and report persistence

```mermaid
sequenceDiagram
    actor Operator
    participant API as FastAPI control plane
    participant DB as PostgreSQL
    participant Run as In-process run executor
    participant Tools as Engine / lm-eval / LLMPerf
    participant Model as Active inference endpoint
    Operator->>API: POST run with test definition reference
    API->>DB: Lock and persist run, inputs and partial report
    API->>Run: Submit thread-pool future
    API-->>Operator: Accepted run ID
    Run->>DB: Mark running and load accepted snapshot
    alt Golden or benchmark
        Run->>Tools: Frozen cases or benchmark subset and model config
        Tools->>Model: Real model requests
        Tools-->>Run: Case scores or benchmark summaries
        Run->>DB: Persist progress and quality report
    else Performance
        Run->>Tools: Frozen workload, separately verified warm-up
        Tools->>Model: Measured concurrent requests
        Tools-->>Run: Latency, throughput, failures and conditions
        Run->>DB: Persist normalized performance report
    end
    Run->>DB: Terminal status, completeness and owned lock release
    Operator->>API: Read run or report
    API->>DB: Load saved report and snapshot
    API-->>Operator: Saved report, public route sanitizes aggregates
```

For vLLM, genuine pinned ray-project LLMPerf performs a separately verified
warm-up before measurement; failures/incomplete warm-up stop the run. Ollama
uses its native streaming measurement path. lm-eval and workload toolkits do not
make small samples representative. [Metric interpretation](../DEMO.md#interpreting-results)
and [evidence](../RELEASE_VALIDATION.md) explain the limits.

Cancellation is cooperative: persist the request, signal the local executor and
let the owning worker acknowledge before releasing the lock. Another replica
must not mark an untracked future cancelled. A directly tracked queued future
may be cancelled before start; running evaluators are not forcibly interrupted.
After process loss, persisted inputs/reports remain but automatic orphan recovery
is not certified. Deferred worker definitions are not this execution path.

Sources: [`provision`](../../backend/src/providers/azure/provision.py),
[`deploy`](../../backend/src/providers/azure/deploy.py),
[`prompts`](../../backend/src/api/routes/prompts.py),
[`runs`](../../backend/src/api/routes/runs.py),
[`executor`](../../backend/src/evaluation/run_quality.py),
[`Functions monitor`](../../functions/orchestrators/generic_orchestrator.py),
[`model job`](../../jobs/model_deployment/entrypoint.py).
