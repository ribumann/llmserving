# Infrastructure: Baseline Azure Pilot Architecture

This directory contains three independent Terraform modules that together implement the
"Baseline Azure Pilot Architecture" described in
[`specs/001-llm-serving-demo/plan.md`](../specs/001-llm-serving-demo/plan.md) (Target Platform
section) and [`research.md`](../specs/001-llm-serving-demo/research.md) (Section 7):

An optional, separate [`infra/bootstrap`](./bootstrap) module proposes keyless
state storage in an existing shared group. It owns no group, ACR or grants
and does not migrate any module's local state. Account-scoped OAuth blob
access and any backend migration still require explicit approval.

| Module | Resource group | Applied | Owns |
|---|---|---|---|
| [`infra/shared`](./shared) | `rg-llm-shared-{stage}` | Once per stage | VNet + 5 subnets, private DNS zones/links, NAT Gateway, NSG (GPU subnet), ACR, Key Vault, Log Analytics + Application Insights |
| [`infra/control`](./control) | `rg-llm-control-{stage}` | Once per stage, after `infra/shared` | Container Apps environment + backend/frontend Container Apps (Entra ID SSO), 5 Container Apps Job definitions, Durable Functions orchestration app, private PostgreSQL Flexible Server, storage accounts (Functions state, Terraform state, artifacts), managed identities/RBAC, alerts |
| [`infra/demo`](./demo) | `rg-llm-demo-{environmentId}` | Once per Demo Environment, dispatched by the `terraform_runner` Container Apps Job | Private GPU VM (no public IP, no Bastion) serving vLLM on `snet-gpu` |

## Why this replaces `infra/azure`, `infra/database`, `infra/app-host` outright

The former three-module layout (`infra/azure` = single-VM demo environment with a public IP +
Bastion, `infra/database` = a standalone Postgres module, `infra/app-host` = a single Container
App with subscription-scoped Contributor and a synchronous Terraform-in-request-thread deployment
path) predates User Story 10's Baseline Azure Pilot Architecture requirements (FR-074–FR-090):
exactly three resource groups with a fixed naming scheme, Entra ID SSO on the app itself, workflow
orchestration handed off to Durable Functions instead of blocking the request thread.
Terraform/model deployment use isolated jobs, but quality/performance still run in
the API process; evaluation/performance/export worker definitions do not establish
durable API routing or parity.

Those are topology changes, not incremental config edits. The superseded modules are
not included. This source snapshot contains no Terraform state and makes no claim
about resources in your subscription. Inspect your existing resources and preserve
state before any migration or replacement; do not infer that deletion is safe.
The current modules use private storage access and Spot GPU VMs. Review availability,
quota, policy, costs, and interruption behavior in your own subscription before applying.

## Bring-up order

**Not a clean-bootstrap certification.** These modules create/manage resource groups,
use local cross-module state and default placeholder images. Do not apply them
against an original deployment or protected existing test groups. First satisfy
[remote-state, immutable-artifact, SSO, ownership, cleanup and budget gates](../docs/AZURE.md).

Each module has an opt-in `existing_resource_group_name` for **fresh data-only
group state**, never an automatic migration of group-owning state. Control
mode requires explicit external SSO/demo/platform inputs and replaces its
legacy subscription grants with the documented resource-scoped runtime
assignments. Retained groups and existing grants are not cleanup targets.
The ACA infrastructure group remains platform-created, not another retained
group. Its ownership/deletion/permission verification is still a live-apply
gate. See [state ownership and the private plan guard](../docs/TERRAFORM_STATE.md).

1. `infra/shared` — first dependency layer; creates billable resources. An independent
   reviewed plan and cleanup are required, not just `subscription_id`.
2. `infra/control` — reads `infra/shared`'s outputs via a local `terraform_remote_state` data
   source (`shared_state_path`, default `../shared/terraform.tfstate`). Container image variables
   (`backend_image`, `frontend_image`, the 5 Container Apps Job image variables) default to a
   placeholder tag in ACR that does not exist yet; the Container Apps/Jobs will show an image pull
   failure until the corresponding image is pushed (`az acr build ...`) and the variable is set to
   the real tag. This is expected and mirrors the former `infra/app-host` module's bring-up
   behavior — infra validates independently of application code being ready.
   Clean private-network applies may set `manage_database_url_secret=true` to
   write the PostgreSQL URL into the shared private vault after database
   creation and before the backend revision. This requires an actual approved
   private Terraform executor with narrow vault secret-write access, not an
   external runner or ARM permission alone. The default retains external
   secret seeding. See the [complete app bootstrap ordering](../docs/APP_BOOTSTRAP.md#database-secret-and-full-apply-ordering);
   no targeted apply or authentication bypass is needed.
   The keyless Premium Functions route also requires the reviewed
   `functions_package_sha256`: a private digest-named Blob package replaces
   Azure Files/account-key content storage. Upload that exact ZIP with OAuth
   after full apply and then restart/sync triggers; see
   [Functions package startup](../docs/APP_BOOTSTRAP.md#functions-deployment-and-startup).
3. `infra/demo` — applied once per Demo Environment, not by an operator running Terraform
   directly. The `terraform_runner` Container Apps Job (defined in `infra/control`) executes this
   module against a per-environment backend state key inside `infra/control`'s `tfstate` storage
   account. It reads only `infra/shared`'s outputs (VNet/subnet/DNS zone IDs) and must never read
   or modify `infra/control`'s or another environment's resources (FR-090).

## Cross-module isolation (FR-090)

- `infra/demo` only ever reads `infra/shared`'s local state file — it has no `terraform_remote_state`
  reference to `infra/control`, and its only resources live inside its own
  `rg-llm-demo-{environmentId}` resource group.
- No module grants a demo environment's identity (the GPU VM has no managed identity assigned)
  any role scoped above its own resource group.
