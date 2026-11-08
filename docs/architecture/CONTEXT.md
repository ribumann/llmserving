# C4 L1 and L2 — Context and containers

[Architecture map](../ARCHITECTURE.md) / **depths 1 and 2** /
[components](COMPONENTS.md) / [deployment](DEPLOYMENT.md) / [flows](FLOWS.md)

This is the top-down entry point. L1 answers **who needs the system and what
does it connect to?** L2 opens the single system box to show its independently
running applications and stores. Neither view shows request order; use the
[sequence storyboards](FLOWS.md) for that.

## C4 Level 1: System context

**System of interest: LLM Serving Demo.** The system is the reusable serving
lab—not Azure itself, a model vendor, a particular demo environment, or the
repository. People in this view are roles. A “verified operator” is a person
whose user token and application policy were accepted; an Azure workload
identity is a separate machine principal.

The serving lab separates anonymous evidence browsing from authorized operator
actions. Azure runs the persistent control plane and private disposable inference
environments; local development can use an operator-managed Ollama runtime.

```mermaid
flowchart TB
    Visitor["Public visitor"]
    Operator["Verified operator"]
    subgraph System["System of interest"]
        Lab["LLM Serving Demo<br/>operator UI, control API and serving workflow"]
    end
    OperatorIdP["Operator identity provider<br/>Microsoft Entra ID"]
    WorkloadIdP["Azure managed-identity issuer<br/>deployment directory"]
    Azure["Azure Resource Manager"]
    Artifacts["Registry and package storage"]
    Models["Model and benchmark sources"]
    Local["Local Ollama"]
    CI["GitHub Actions"]
    Visitor -->|Sanitized persisted GETs| Lab
    Operator -->|Configure, deploy, run, compare| Lab
    Operator -->|Sign in| OperatorIdP
    OperatorIdP -->|User token| Lab
    WorkloadIdP -->|Job callback identity| Lab
    Lab -->|Scoped infrastructure operations| Azure
    Lab -->|Pull verified artifacts| Artifacts
    Lab -->|Download under source licenses| Models
    Lab -->|Local adapter| Local
    CI -->|Protected opt-in publication| Artifacts
```

**How to read it:** a visitor can read safe saved evidence. An operator can also
request actions through the same application after authentication. Entra supplies
identity through distinct operator and workload principals; the operator tenant
may differ from the deployment directory. ARM performs infrastructure
control-plane actions. Artifact/model
sources supply bytes but do not become trusted merely because a repository names
them. The system uses them only under its package/model handling path.

The [public demo](https://servinglab.liberatetheinnerchild.net) is not an
anonymous inference endpoint. Azure public ingress is for the UI/control API,
not database, SSH or vLLM ports. Exact public fields and policy are defined in
[authentication](../AUTHENTICATION.md#public-read-only-api).

CI appears only as a delivery-side system: ordinary PR checks do not call the
running application. The local Ollama relationship is an **alternative local
execution mode**, not an additional cloud inference service. The diagram does
not claim that every deployment has one or that GitHub Actions executes
production traffic.

## C4 Level 2: Runtime containers

Here, “container” means an independently running software application or data
store in C4; it does not necessarily mean a Docker image. Runtime instances,
network placement, identities and persistent stores are refined in the separate
[deployment view](DEPLOYMENT.md).

```mermaid
flowchart LR
    Visitor["Public visitor"]
    User["Verified operator"]
    Browser["Browser"]
    Client["Headless user client"]
    subgraph Lab["LLM Serving Demo"]
        UI["Web application<br/>React SPA served by Nginx"]
        API["Control-plane API<br/>FastAPI"]
        DF["Workflow monitor<br/>Azure Durable Functions"]
        Job["Job executions<br/>Container Apps Jobs"]
        Run["Quality/performance runner<br/>API process thread pool"]
        DB[("Application database<br/>PostgreSQL")]
        Store[("Functions / Terraform / artifact storage")]
        GPU["Cloud inference runtime<br/>Private VM + vLLM"]
    end
    Local["Local inference runtime<br/>Ollama"]
    Azure["Azure management APIs"]
    Sources["Model and benchmark sources"]
    Visitor -->|Safe persisted GETs| UI
    User -->|Signed user session| Browser
    Browser -->|HTTPS UI and same-origin API proxy| UI
    Client -->|HTTPS with user bearer token| API
    UI -->|HTTPS API requests| API
    API --> DB
    API -->|Provision / teardown monitor| DF
    API -->|Pre-dispatch deployment job| Job
    DF -->|Dispatch or monitor| Job
    Job -->|ARM operations| Azure
    Job -->|Azure Run Command deployment target| GPU
    Job --> Store
    DF --> Store
    API -->|Report snapshots and state| DB
    API -->|Submit inference request| GPU
    Run -->|Golden / benchmark / performance traffic| GPU
    Run -->|Local engine requests| Local
    API -->|Select local adapter| Local
    GPU -->|Download model at deployment| Sources
    Run -.->|Worker definitions exist; API run path is local| Job
```

### What each container owns

| Container | Responsibility | Not its responsibility |
| --- | --- | --- |
| React SPA / Nginx | Routes browser pages; proxies `/api`; allows only safe public GETs anonymously. | Authorizing a user or filtering sensitive records. |
| FastAPI | Authenticates each request; validates inputs; coordinates domain/provider operations; persists reports and state. | Owning the cloud job's long-running work or acting as an identity provider. |
| Durable Functions | Stores workflow orchestration history, dispatches or monitors one job and handles cancellation/timeout paths. | Applying domain state directly or storing the model access token. |
| Container Apps Job execution | Isolated Terraform or model deployment worker process. | Serving every prompt or running current API quality/performance requests durably. |
| Quality/performance executor | Executes accepted run input in a backend process thread and updates PostgreSQL. | Surviving API process loss; its future and cooperative cancel event are in memory. |
| PostgreSQL | Persists environment/config/revision/workflow/run/report/comparison state. | Proving that an external VM/model or stopped database is currently reachable. |
| Blob/Queue/Table storage | Durable Functions runtime state, manually transferred Terraform state/leases, and artifacts. | A single shared native Terraform backend for every layer. |
| Private GPU VM / vLLM | Runs the deployed cloud model behind private networking. | Public web ingress, durable report storage or the control-plane database. |
| Local Ollama | Supplies an operator-managed local inference endpoint. | Cloud provisioning or a local fake for Azure capacity. |

### Trust and execution boundaries

The public visitor is not a trusted operator. Nginx strips identity headers on
public API requests; the backend admits only exact registered public GET routes
and serializes allowlisted saved projections. Operator requests carry a user
token and are verified by the backend. Internal workflow callbacks use a
different signed managed-identity token, audience and resource allowlist. These
are three different relationships, not one “authenticated app” arrow.

The model job receives an ephemeral gated-model credential through its direct
dispatch. Durable Functions sees the execution name and monitors the job; the
credential must not enter replayable orchestration history, database snapshots,
Terraform variables or diagnostic output. See the [deployment and provenance
view](DEPLOYMENT.md#source-and-artifact-provenance).

The dashed line is intentionally not an active route: job images/mappings exist
for evaluation, performance and export, but API runs still use the in-process
orchestrator. Reports persist; thread futures do not survive API restart. There
is no automatic orphan recovery/exactly-once claim. Do not route to the workers
until snapshots, report semantics, cancellation, failure, restart and ownership
parity have been proved.

Local Vite calls an explicit loopback API with exact CORS configuration instead
of the production Nginx transport. Local-demo headers are rejected on cloud hosts.
Ollama is presenter-managed; local “provision” does not allocate cloud resources.

## Moving to the next level

At L3, follow one running container at a time:
[frontend and API components](COMPONENTS.md),
[Functions components](COMPONENTS.md#functions-container-components).
To see *when* they interact, follow [provision](FLOWS.md#provision-and-teardown),
[deployment](FLOWS.md#deploy-a-model), or [run/report](FLOWS.md#quality-performance-and-report-persistence).
To see source-level composition, use [selected L4 views](CODE.md).

Sources: [`API composition`](../../backend/src/api/app.py),
[`provider registry`](../../backend/src/providers/registry.py),
[`run executor`](../../backend/src/evaluation/run_quality.py),
[`workflow mappings`](../../functions/orchestration_lib/workflow_jobs.py),
[`frontend transport`](../../frontend/nginx.conf),
[`Azure resource layers`](../../infra),
[`vLLM deployment job`](../../jobs/model_deployment/entrypoint.py).
