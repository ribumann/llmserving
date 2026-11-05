# Terraform worker state persistence and recovery

The current `terraform_runner` uses its managed identity to download/upload
private Azure blob state, then invokes Terraform with a local backend. This
guide documents fail-closed transfer and worker leasing, not a full remote backend or
complete reproducible Azure bootstrap certification.

## Required behavior

Both `TF_STATE_STORAGE_ACCOUNT` and `TF_STATE_CONTAINER` must be configured in
cloud execution. Partial configuration, invalid storage names, missing cloud
configuration, identity errors and HTTP/network failures stop before Terraform.
There is no empty-state fallback on denied storage access.

The fixed `infra-shared.tfstate` must be readable and structurally valid.
Per-environment state is addressed by the validated environment ID, which must
match any `terraformVariables.environment_id`. A first **apply** may start
without existing state only on explicit Azure `BlobNotFound`, not a generic 404
or missing container. A destroy must find existing state. If the blob is absent
but local state exists, execution stops rather than adopting a stale file.
Downloaded/uploaded state must have the Terraform v4 object shape with resource
and output collections; malformed or unsupported state stops explicitly.

After apply/destroy, the runner persists whatever Terraform wrote, including
partial state after nonzero exit or a command exception/timeout. Successful
cloud execution requires a produced state file and an acknowledged upload.
Upload failure prevents the success callback even if Terraform returned zero.
An apply also requires a successful object-shaped JSON output before it can
report completion.

Before any state read or Terraform command, cloud workers acquire an exclusive
Azure blob lease on `locks/<environmentId>.json` in the state container.
Creation is conditional; existing ownership metadata must match the environment.
Only the acquiring lease ID can update the owning workflow or release it.
Concurrent workers fail before Terraform; no worker breaks, expires or steals
another worker's lease. The lease covers shared/environment state reads,
initialization, apply/destroy, partial-state persistence and output validation.
Completion requires acknowledged state persistence and owned lease release.

Leases are intentionally infinite rather than automatically expiring into an
untracked retry. Initialization failures release the lease, but failed mutations,
timeouts, persistence/output failures and force-killed workers retain it for
operator recovery. This sacrifices automatic retry availability to preserve
ownership while resource/state changes may be uncertain.

Before acquisition, every attempt durably writes its proposed lease UUID,
workflow/environment IDs and recovery-record name to a new private
`locks/<environmentId>/attempts/<random-attempt-id>.json` blob, using conditional
creation. Acquisition cannot proceed without acknowledgment. The lock's
ownership metadata points to that recovery record after acquisition. Attempt
records cover termination before that metadata update and ambiguous acquisition
responses; they are retained, not automatically deleted. Lease IDs never appear
in logs, public diagnostics, Terraform state or public artifacts. Treat these
private records as sensitive lease capabilities, not an outputs manifest.

Outside Azure hosting, with **both** storage variables unset, existing local
development/test behavior remains local-only. This is not a cloud opt-out:
inherited Azure hosting/identity markers require remote state. Authentication
is not weakened to make a test pass.

## Retained demo resource groups

The operator may set control input `demo_resource_group_name` (backend
`AZURE_DEMO_RESOURCE_GROUP_NAME`) to an existing, approved group. It is not a
browser-configurable input. The server persists `existing_resource_group_name`
with the exact environment variables, and destroy reuses those saved variables
even if operator settings later change. `demo_resource_tags` / JSON
`AZURE_RESOURCE_TAGS` enforce ownership tags over caller tags; retained mode
honors the operator's `managedBy` while Terraform still enforces environment
and profile tags. Legacy managed mode keeps `managedBy=terraform`.

Model dispatch carries only the saved effective group and name prefix, not
the full Terraform variables. NIC resolution, VM power/start and Run Command
use that same scope; retained deployments with missing or inconsistent scope
fail rather than falling back to current operator settings. Worker inputs also
support this explicit scope for future evaluation/performance use, but durable
evaluation/performance routing and parity are not enabled by this change.

Use **fresh per-environment state only**. In retained mode, `infra/demo` reads
the group as data, never creates/adopts it, and owns only its NIC, VM and driver
extension. Resource names still include the environment ID. Compute uses the
shared subnet's region, not the group's metadata location. Teardown preview
does not list the group for deletion or imply other environments/grants are
removed. Omitted configuration preserves the original managed-group path; the
explicit `moved` block maps its original group address to index zero.

Inside the existing lease, after download and before Terraform initialization,
the worker structurally validates state ownership. It rejects mode changes,
wrong group/environment ownership, malformed group records and unexpected
managed resource types. A managed-group state cannot be converted to retained
mode, even for destroy. A data-only group is allowed only in its saved retained
mode. Rejected pre-mutation attempts do not complete successfully.

This guard checks the worker's downloaded state, **not arbitrary CLI use**.
Never switch ownership using bare `terraform apply`/`destroy`, remove group
records to evade the guard, or adopt original deployment state. A raw CLI
conversion can plan deletion of the previously managed group. Control
group ownership and guarded all-layer bootstrap remain separate requirements;
this option alone does not make protected-group deployment safe or enabled.

## Retained shared group and private plan guard

`infra/shared.existing_resource_group_name` selects an existing data-only group
for **fresh non-group-owning state**. Null preserves the original managed mode;
blank/invalid names fail. Owned child resources use the selected group and
`location`, not the group's metadata region. Operator ownership tags are honored
only in retained mode; default managed tag precedence stays unchanged.

The explicit singleton-to-index-zero `moved` block preserves the default
managed-state address. Credential-free native contracts run on Terraform 1.9.8;
the exact old-singleton-state upgrade uses Terraform 1.14.0's `state_key`
to share real mocked state across legacy and current module configurations.
These are not Azure apply or cleanup evidence.

After all independent deployment gates have passed, generate a native saved
plan in a mode-0700 private directory from the reviewed module. Keep plan/state,
tfvars and logs private and out of GitHub artifacts. Run the ownership guard
**from the same initialized module directory**:

```bash
python ../../scripts/validate_retained_group_plan.py \
  --plan /approved/private/retained.tfplan \
  --resource-group "rg-approved-existing" \
  --private-log /approved/private/new-guard.log
```

Validation does not apply. An explicitly authorized execution adds `--apply`
and uses a **new** private log path. The guard copies the native plan privately,
uses `terraform show -json`, checks its variables, prior/planned resources and
all changes (including before-values of deletes/replacements), then applies
that exact copied plan. It rejects any managed AzureRM group, group-owning prior
state, malformed records and explicit foreign/unknown `resource_group_name`
values. Terraform's native stale-plan checks still apply. Errors return failure;
Terraform output stays in the mode-0600 private log, never public JSON dumps.

This is an **ownership-only guard for reviewed module plans**, not a sandbox for
arbitrary Terraform code. It does not establish foreign parent-ID/RBAC scope,
hidden platform resources, tags, cost, auth, private remote-backend locking,
pre-init state safety or independent cleanup. Raw CLI bypasses it. Never remove
state records or use raw apply/destroy to convert group ownership. Control
group/scoped-role support and safe all-layer deployment remain unfinished.

## Explicit remaining limitations

The worker lease serializes cooperating executions; it does not provide atomic
Terraform remote-backend semantics or fence an authorized external writer that
ignores this lock. Shared-layer writers need their own backend/locking contract.
Protocol/guarded-run tests are credential-free, not actual Azure lease acceptance
or independently verified restart recovery. The API lock is a separate control.
The runner's failure handler cannot survive process/host cancellation;
independent server-side billable-resource cleanup remains required.

Do not provision billable resources until those gates, actual authenticated
Azure UX and bounded aggregate exposure pass. Do not enable durable evaluation
or remove API runners based on these Terraform state tests.

Shared/control module state still has local cross-module assumptions. Moving
every layer to private encrypted remote state with scoped RBAC, locking,
recoverable versions and tested restore is separate work. Shared state can
include secrets and must not be treated as a public outputs manifest.

## Persistence failure response

A persistence error means resources may have changed while their latest state
is only on the worker's ephemeral disk. **Do not automatically retry apply or
destroy.** Preserve the failed workflow status and have an authorized operator
inventory exactly scoped owned resources and recover state through an approved
private channel before retrying. If local state was lost, recover/import only
after independently proving ownership and reviewing a plan; never reconstruct
state by guessing resource names or adopting original deployment resources.

For a retained lease, first prove the named worker and its child processes have
terminated, recover the latest private state and independently inventory owned
resources. Read the private per-attempt recovery record for that execution to
obtain its proposed lease UUID. If acquisition or metadata acknowledgment was
lost, inspect the private attempt records instead of assuming the lock's older
workflow label is current. An authorized operator may then release the exact
held lease through the storage lease API and review the next plan. A mismatched
lease UUID must fail, never trigger a break or takeover. Never blindly break a lease,
delete the lock blob, automatically expire it, or retry against an active or
unverified owner. No automated unlock/recovery command is provided.

Keep state, backups, plans, tfvars and provider output out of Git, public
artifacts/logs and chat. Recovery messages expose error class/status rather
than storage endpoints, tokens or state content. A successful retry must
persist state before completion and independently verify teardown residuals.

The current protected OIDC workflows may be disabled while target setup is
being reassessed. Historical canary proof applies only to its identity and
original target; it is neither current-target access nor billable cleanup.
