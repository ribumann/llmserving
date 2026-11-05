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
ownership while resource/state changes may be uncertain. The workflow ID is
stored privately in the lock blob; lease IDs are not published in diagnostics.

Outside Azure hosting, with **both** storage variables unset, existing local
development/test behavior remains local-only. This is not a cloud opt-out:
inherited Azure hosting/identity markers require remote state. Authentication
is not weakened to make a test pass.

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
resources. An authorized operator may then release the exact held lease through
the storage lease API and review the next plan. Never blindly break a lease,
delete the lock blob, automatically expire it, or retry against an active or
unverified owner. No automated unlock/recovery command is provided.

Keep state, backups, plans, tfvars and provider output out of Git, public
artifacts/logs and chat. Recovery messages expose error class/status rather
than storage endpoints, tokens or state content. A successful retry must
persist state before completion and independently verify teardown residuals.

The current protected OIDC workflows may be disabled while target setup is
being reassessed. Historical canary proof applies only to its identity and
original target; it is neither current-target access nor billable cleanup.
