# Keyless state storage bootstrap (source only)

This independent module manages a StorageV2 Standard_LRS account, an
`azapi_update_resource` for its default blob service configuration, and a private
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
configuration and container provisioning all use management-plane requests.

Azure automatically creates `blobServices/default` with the account.
Attempting to create it as an `azapi_resource` fails with
`ResourceAlreadyExists` after account creation. The update resource configures
only versioning/recovery on that automatically owned service, rather than
trying to create or import it. It is bound to the account resource's ID.
The container depends on the configuration update, so it is created only after
the requested protection settings are acknowledged.

## Protection and authorization boundary

The account requires HTTPS and TLS 1.2, disables shared-key and anonymous blob
access, defaults to OAuth and disables cross-tenant replication. Blobs use
Microsoft-managed encryption. Blob versioning and seven-day blob/container
soft delete provide recovery; these are not independently tested restores or
immutable backups. The container has `publicAccess=None`.
Account `publicNetworkAccess` is **Disabled**, respecting enforced governance.
ARM-only provisioning does not need a blob data-plane route. A separately
reviewed private endpoint/DNS and execution route are required before actual
OAuth blob access or backend migration; this module does not create that route.
No key/SAS fallback, exemption or public-network re-enable workaround is allowed.

All three Terraform records have `prevent_destroy`; replacement/destruction is blocked
while these declarations remain in configuration. This is a Terraform guard,
not an Azure resource lock or protection against removing configuration,
external deletion, a privileged writer or deletion of the retained group.
Removing an `azapi_update_resource` would not delete the service or revert its
properties; the physical service's lifecycle belongs to the managed account,
not an independently orphanable resource. The account remains owned and
protected by this module. Versioning/soft delete do not recover a deleted storage account. Preserve
private state/backups and independently review exact live plans.

**Data-plane access requires independent authorization.** Management-plane
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

## Initial saved-plan execution gate

Before any independently authorized bootstrap apply, use
[`validate_bootstrap_plan.py`](../../scripts/validate_bootstrap_plan.py) from
the **initialized, independently reviewed bootstrap module directory**, with
the same approved provider authentication environment. This is separate from
the AzureRM retained-group guard: that guard does not validate AzAPI parents.
Generate the saved plan and run the guard/apply from the **same canonical
initialized directory using its existing default local state**. A plan-time
absolute `-state` override is not a guarantee that applying from a different
checkout/directory will select that state. Copying the binary plan preserves
its bytes, not the execution directory's local-backend state selection.
An isolated checkout can therefore fail with a state-lineage mismatch even
when the plan itself passed validation. Do not force state, import, remove
records or retry the mismatched plan: return to the canonical directory,
preserve state/backup, and generate/review a new full saved plan there.
Keep the native plan, state, expected-target JSON and log private. Create the
target JSON independently from approved inputs, not by extracting whatever
the plan happens to select. It must contain exactly `subscription_id`,
`tenant_id`, `existing_resource_group_name`, `location`, `name_prefix`, `stage`
and `tags` (the complete exact expected account tag map).

```bash
python ../../scripts/validate_bootstrap_plan.py \
  --plan /approved/private/bootstrap.tfplan \
  --expected-target /approved/private/bootstrap-target.json \
  --private-log /approved/private/new-bootstrap-guard.log
```

Default execution **checks only**. Only an independently authorized execution
adds `--apply`, with a new log path; the guard then applies the exact same
private copied binary plan that `terraform show -json` validated. Terraform's
native stale-plan checks still apply. The private copy/log are mode 0600
inside a temporary mode-0700 directory (log path is operator-selected).
The guard strips inherited `TF_CLI_ARGS*`/`TF_LOG*`; Terraform errors/output
remain in the private log, never a public payload dump.

The initial gate requires exactly the three reviewed managed addresses:
`azapi_resource.state`, `azapi_update_resource.blobs` and `azapi_resource.tfstate`.
The service's Terraform `create` action means creating an update record and
configuring the automatically existing service, not an ARM service create.
The default initial gate requires
create-only changes with no prior managed resources/import/move/update/delete,
the exact pinned APIs/provider, explicit target inputs, known account parent,
exact security/recovery bodies, names and tags, and resolved tenant/group data
reads. Unknown critical security fields, extra resources/providers/modules and
foreign or ambiguous parents fail closed.

Fresh child IDs are normally unknown. In that case the guard requires exactly
the reviewed configuration dependency on `azapi_resource.state.id` for the
blob service and `azapi_update_resource.blobs.id` for the container, while binding the
known account parent to the exact approved group. Empty nested unknown-metadata
objects do not mean the security properties are unknown. Terraform JSON
references **do not encode full expression semantics**: a malicious expression
can mention the right resource while computing a foreign ID. Consequently
this is an execution gate for the **reviewed module**, not a sandbox or
approval for arbitrary Terraform code/provider binaries/environment.
Do not substitute unreviewed module code, use targeting, edit plan JSON, or
retry against an existing account/state without the explicit narrowly scoped
recovery gate below. General state refresh/update/recovery remains rejected.

### Account-only partial-apply recovery

If the former service-create bug left **only this module's account** in
preserved local state, do not delete/recreate the account, remove state records,
import the default service, use `-target`, or retry the old saved plan. Preserve
state/backup and independently verify the exact account ARM ID, subscription,
group, location and all ownership tags against approved inputs, plus account
security settings and the default service's exact
`<owned-account-id>/blobServices/default` ID/type. Inspect the service's live
versioning and blob/container recovery baseline using ARM GET, not keys or blob
data access. Absence of the intended settings is the failure baseline to fix,
not evidence of a separate disposable resource.

From the reviewed corrected module, generate a **new full native saved plan**
using the preserved partial state in that same canonical directory's default
local backend and independently approved target variables. Run the guard and
any authorized apply from that directory too; do not generate with an absolute
`-state` override in an isolated checkout and assume apply will retain it.
The only acceptable recovery shape is the exact owned account **no-op**,
`azapi_update_resource.blobs` **create** (configures the automatically existing
service), and `azapi_resource.tfstate` **create**. Review the real plan and
independently verified live baseline before checking it:

```bash
python ../../scripts/validate_bootstrap_plan.py \
  --plan /approved/private/bootstrap-recovery.tfplan \
  --expected-target /approved/private/bootstrap-target.json \
  --private-log /approved/private/new-bootstrap-recovery-check.log \
  --recover-account-only
```

This explicit flag requires exactly one prior managed record: the original
`azapi_resource.state`, with exact known owned ID and unchanged prior/before/after
values. Its security body/tags/location must still match approval; any account
update/replacement, import, other prior managed record, unknown account value,
foreign scope or extra action fails closed. It does not import/adopt a different
account or allow a recovery after the service/container has entered state.
The gate validates plan/state, not live ARM ownership or service baseline;
independent GET verification remains mandatory. Only after independent review,
passing checks and explicit apply authorization may the operator use the same
guard with `--recover-account-only --apply` and a new private log. No state
migration, role grant or blob access is implicit in this operation.

### Verified governance refresh baseline

The original campaign account was created requesting public networking
Enabled, but management-group governance changed it to Disabled during creation.
Do not treat this as permission to reverse policy or seek an exemption.
The corrected module and guard require Disabled. First independently verify
the exact account's ARM GET and activity-policy result, preserving original
partial state and the native drift evidence privately.

If the new full recovery plan contains **only** that exact account refresh
transition, add `--accept-policy-network-disable` alongside
`--recover-account-only`. This accepts exactly one fully known drift record:
the owned account's `Enabled → Disabled` refresh, with every other field
unchanged. The sole optional normalization is an empty AzAPI computed
`output` object becoming null; it is not a resource setting.
The refreshed account must match preserved refreshed prior state and still
have a **no-op** planned action with exact approved security/tags/location.
An account update of any kind remains rejected, including a proposed network
re-enable or computed-output-only update. No general drift allowlist exists.
If the native shape differs, stop and inspect it privately rather than
refreshing/removing state records or weakening the checks.

This flag checks a precisely described native transition; it does not prove
the live cause was policy or authorize execution. Independent policy evidence
and reviewed exact-plan authorization remain required. After a later reviewed
state refresh removes that drift from the plan, use ordinary account-only
recovery instead; the policy flag requires the actual transition to be present.
The operation can configure service recovery/create the container via ARM,
but **cannot establish data-plane readiness** while no private route exists.

Credential-free unit tests mirror native first-plan shapes and reject malformed
targets/payloads, foreign parent chains, roles/extra resources, prior state,
shared keys/public access and unknown security. They also verify private-copy
check-only/apply behavior without invoking Azure. Passing this guard is not
permission to create storage or grant/use data access, nor evidence of apply,
migration, actual backend locking, restore or complete deployment.
