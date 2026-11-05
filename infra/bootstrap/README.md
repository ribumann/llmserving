# Keyless state storage bootstrap (source only)

This independent module proposes **three ARM resources**: a StorageV2
Standard_LRS account, its default blob service configuration, and a private
`tfstate` container in a **required existing resource group**. The group is
read as data, never created, tagged, imported or deleted. Use **fresh local
bootstrap state only**, separate from shared/control/demo state. Do not adopt
an existing account or import resources already owned by another layer.

AzAPI is pinned to **2.4.0**, with storage ARM API **2023-05-01** and group
read API **2024-03-01**. Provider registration and preflight writes are disabled;
required namespaces must already be registered. The module creates no ACR,
identity, role assignment, application, password, consent or directory group.
In particular, the existing shared layer remains the sole owner of its ACR.
No storage keys are listed, read, exported or stored: account, blob service
and container provisioning all use management-plane requests.

## Protection and authorization boundary

The account requires HTTPS and TLS 1.2, disables shared-key and anonymous blob
access, defaults to OAuth and disables cross-tenant replication. Blobs use
Microsoft-managed encryption. Blob versioning and seven-day blob/container
soft delete provide recovery; these are not independently tested restores or
immutable backups. The container has `publicAccess=None`. The public TLS
endpoint is intentional: no private-network prerequisite, key/SAS fallback
or anonymous access is introduced.

All three resources have `prevent_destroy`; replacement/destruction is blocked
while these declarations remain in configuration. This is a Terraform guard,
not an Azure resource lock or protection against removing configuration,
external deletion, a privileged writer or deletion of the retained group.
Versioning/soft delete do not recover a deleted storage account. Preserve
private state/backups and independently review exact live plans.

**Current campaign data-plane access is NOT authorized.** Management-plane
Owner is not OAuth blob data access. Granting or using **Storage Blob Data
Contributor at the exact new account** requires explicit user approval before
any grant, blob access or migration. This module never creates that assignment
and does not grant itself access. Do not test access with keys/SAS or broaden
roles to work around denial.

## Inputs and proposed names

Inputs are `subscription_id`, `location`, `stage`, `name_prefix`,
`existing_resource_group_name`, and `tags`. Identity/tenant selection comes
from the independently approved provider authentication environment, not
embedded campaign identities. Account naming deliberately matches shared's
actual suffix:

```hcl
"${name_prefix}state${substr(md5("${subscription_id}-${stage}"), 0, 6)}"
```

The current operator proposal (not defaults or permission to apply) is
subscription `86677b6e-28fc-48e4-8988-5ab9e568eece`, deployment tenant
`ecd6dfda-d2ce-47a8-9901-e35f31fe18dd`, location `italynorth`, stage `release`,
prefix `llmrelease`, existing group `rg-llmserving-e2e-shared`. This computes
**`llmreleasestate0ea5e6` (21 characters)** and container **`tfstate`**, distinct
from shared's `llmreleaseacr0ea5e6`. Preserve the exact campaign tags:

```hcl
tags = {
  project   = "llmserving-public-validation"
  managedBy = "copilot-release"
  target    = "personal-fallback-e2e"
  runId     = "public-release-20261105"
  expiresOn = "2026-12-05"
}
```

No separate bootstrap resource group is created or assumed authorized.
Use private operator configuration for actual execution; never publish state,
plans, tfvars, credentials or provider logs.

## Backend outputs are candidates, not migration

Outputs are `resource_group_name`, `location`, `state_account_id`,
`state_storage_account_name`, `state_container_name` and `backend_configs`.
The latter contains nonsecret candidate `azurerm` backend settings for
`bootstrap.tfstate`, `shared.tfstate` and `control.tfstate`, each including
`use_azuread_auth=true`, `use_oidc=true`, subscription, authenticated tenant,
resource group, account and container. The approved OIDC client identity and
token configuration must come from the execution environment, not state.

This module intentionally has **no backend block**; initial state remains local.
The output does not initialize a backend, transfer state, change
shared/control/demo, change cross-module state reads, configure the job runner,
or authorize access. It does not replace control's existing private runtime
state account/container. The worker's current `infra-shared.tfstate` protocol
is also unchanged. Separate keys alone do not provide per-layer RBAC isolation.
Never put two states in charge of the same account/container or resources.

After explicit account-scoped data-access approval, an independent follow-up
must preserve/verify local state and lineage, review backend overrides and
cross-module wiring, authorize migration, verify native locking and recovery,
and test restore before claiming protected remote state. Do not run
`init -migrate-state` or copy blobs based only on these outputs.

## Credential-free validation

From `infra/bootstrap`, with Terraform 1.9.8:

```bash
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
terraform test -no-color
```

Native mocked plans cover ARM hierarchy/ownership, exact API types, naming
and length, tags/region independence, TLS/OAuth/encryption/anonymous access,
versioning/recovery, nonsecret separate backend configurations and rejected
inputs. Supplemental source-shape assertions check the managed resource
allowlist, computed parent references and `prevent_destroy` declarations
(computed IDs are unknown in fresh plans on Terraform 1.9.8). No mocked apply
is needed or run. These checks are regression guards for reviewed source,
not an arbitrary-code/ownership sandbox. They make no Azure calls and prove neither live permissions, account
availability, actual apply, usable blob access, locking, restore nor deployment.
The credential-free Infra CI matrix includes this module; no deployment
workflow or Azure write permission is added.
