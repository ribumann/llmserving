# Context and containers

[Architecture map](../ARCHITECTURE.md) / **depths 1 and 2** /
[components](COMPONENTS.md) / [deployment](DEPLOYMENT.md) / [flows](FLOWS.md)

## System context

The serving lab separates anonymous evidence browsing from authorized operator
actions. Azure runs the persistent control plane and private disposable inference
environments; local development can use an operator-managed Ollama runtime.

```mermaid
flowchart TB
    Visitor["Public visitor"]
    Operator["Verified operator"]
    Lab["LLM Serving Demo"]
    Entra["Microsoft Entra ID"]
    Azure["Azure Resource Manager"]
    Artifacts["Registry and package storage"]
    Models["Model and benchmark sources"]
    Local["Local Ollama"]
    CI["GitHub Actions"]
    Visitor -->|Sanitized persisted GETs| Lab
    Operator -->|Configure, deploy, run, compare| Lab
    Entra -->|Signed users and managed identities| Lab
    Lab -->|Scoped infrastructure operations| Azure
    Lab -->|Pull verified artifacts| Artifacts
    Lab -->|Download under source licenses| Models
    Lab -->|Local adapter| Local
    CI -->|Read-only PR checks| Lab
    CI -->|Protected opt-in publication| Artifacts
```

The [public demo](https://servinglab.liberatetheinnerchild.net) is not an
anonymous inference endpoint. Azure public ingress is for the UI/control API,
not database, SSH or vLLM ports. Exact public fields and policy are defined in
[authentication](../AUTHENTICATION.md#public-read-only-api).

## Runtime containers

```mermaid
flowchart LR
    Browser["Browser"]
    Headless["Approved headless user client"]
    UI["React UI / Nginx"]
    API["FastAPI control plane"]
    DB[("PostgreSQL")]
    Runs["In-process run executor"]
    Functions["Durable Functions"]
    Terraform["Terraform runner"]
    Model["Model job"]
    State[("Private state and packages")]
    GPU["Private GPU VM / vLLM"]
    Ollama["Local Ollama"]
    Deferred["Deferred evaluation, performance, export jobs"]
    Browser --> UI
    Headless -->|Signed user token| API
    UI -->|Same-origin API proxy| API
    API --> DB
    API --> Runs
    Runs --> DB
    API --> Functions
    Functions -->|Provision or teardown| Terraform
    API -->|Credential-carrying pre-dispatch| Model
    Functions -->|Monitor existing execution| Model
    Terraform --> State
    Functions --> State
    Terraform --> GPU
    Model --> GPU
    API -->|Prompt adapter| GPU
    Runs -->|Golden, benchmark, performance| GPU
    API --> Ollama
    Runs --> Ollama
    Functions -.->|Mappings exist; API runs not routed| Deferred
```

The backend's `QualityRunOrchestrator` runs **both** quality and performance in
its thread pool. Reports survive in PostgreSQL; thread futures do not survive a
backend restart. There is no demonstrated automatic orphan recovery/exactly-once
execution. Do not route to the deferred jobs until report, snapshot, cancellation
and restart/ownership parity is proven.

Local Vite calls an explicit loopback API with exact CORS configuration instead
of the production Nginx transport. Local-demo headers are rejected on cloud hosts.
Ollama is presenter-managed; local “provision” does not allocate cloud resources.

Sources: [`API composition`](../../backend/src/api/app.py),
[`provider registry`](../../backend/src/providers/registry.py),
[`run executor`](../../backend/src/evaluation/run_quality.py),
[`workflow mappings`](../../functions/orchestration_lib/workflow_jobs.py),
[`frontend transport`](../../frontend/nginx.conf).
