# Azure bootstrap and release gates

**A clean reproducible Azure release is not yet demonstrated.** The modules
describe shared/control/demo layers, but still have local cross-module state,
placeholder image defaults and default to managing their own groups. Demo-only
retained-group mode is now opt-in; shared/control still manage groups. Existing
deployment workflows update API/UI images only; they are not an end-to-end
bootstrap or independent cleanup of billable resources.
Their privileged checkout/login actions are now commit-pinned. Resource-name
configuration requires protected environment secrets so GitHub masks runner
step headers before any script starts; legacy variables must be explicitly
migrated before enabling deployment. These changes do not enable deployment or
establish current-target access.

Do not run the default modules against an original deployment or pre-existing
protected test groups. Validation (`init -backend=false`/`validate`) proves
neither an applicable plan nor ownership-safe migration.

For a **fresh demo state**, control inputs `demo_resource_group_name` and
`demo_resource_tags` wire operator-owned group/ownership tags into the backend.
The group name is omitted from the environment when unset, rather than silently
treating a blank typo as managed mode. Caller input cannot select a group or
override enforced operator tags. This does not adopt existing group state or
change already-saved teardown configuration; see
[state ownership and CLI limitations](TERRAFORM_STATE.md#retained-demo-resource-groups).
Shared/control persistent-group ownership, protected bootstrap and independently
verified actual-resource cleanup are still pending. No Azure or GPU acceptance
gate is satisfied by credential-free plan tests.

## Prerequisites before any billable resource

| Gate | Required evidence |
| --- | --- |
| Scope | Exact subscription/tenant, isolated resource allowlist and live ownership tags; preserve groups and grants |
| Identity | Protected-main environment, exact OIDC subject/audience and scoped RBAC; actual token exchange |
| Authentication | New isolated app, approved consent/assignments/domains, private credential reference, real browser/API acceptance |
| Cleanup | Separate failure/cancellation cleanup plus scheduled fallback for actual billable resources, independently verified |
| Exposure | Aggregate committed plus delayed cost bounded below US$500, including conservative contingency |
| Review | Reviewed SHA, current-head required CI and explicit artifact manifest |

The successful [canary](AZURE_CANARY.md) establishes its own OIDC/identity cleanup
only. It does not satisfy application authentication, a new target's access,
billable-resource cleanup, quota or GPU allocation.

Use explicit subscription/resource arguments for every command; do not change
shared Azure CLI subscription/region defaults. In public logs mask infrastructure
identifiers **before** `azure/login` and avoid dumping account/environment data.
Do not expand permissions merely to read administration settings that runtime
does not require. Stop on denied policy or unknown ownership.

## Minimal external SSO bootstrap

The application can accept an externally approved app without granting Graph
application-write rights to the scoped Actions identity. A compliant,
tenant-approved operator must provide the following for a **new isolated** app:

- Approved operator-tenant application client UUID and service principal. The
  deployment tenant is the default; an explicitly approved external tenant uses
  `existing_sso_tenant_id` without changing ARM/internal managed-identity tenants.
- Both exact new callbacks:
  `https://<frontend-fqdn>/.auth/login/aad/callback` and
  `https://<backend-fqdn>/.auth/login/aad/callback`.
- Approved delegated consent, user/group assignments and allowed email domains.
- A rotated credential written over approved private connectivity to the
  isolated shared Key Vault; supply only its versionless secret URI.
- Real platform token injection/token-store behavior and a browser session that
  reaches the backend with the correct signed audience/issuer.

Terraform inputs are paired `existing_sso_client_id` and
`existing_sso_secret_id`, plus optional explicit `existing_sso_tenant_id`; see
[the exact contract](AUTHENTICATION.md). Backend `AUTH_TENANT_ID` and both
Easy Auth issuers use that operator tenant. `AZURE_TENANT_ID` remains the ARM/
internal callback tenant; never replace it globally for cross-tenant sign-in.
Final callback FQDNs must be known, so external bootstrap may still require an
operator after planning/reserving endpoint names. ARM/OIDC success cannot
remove that prerequisite. Never reuse/alter the original app, put credential
values in tfvars/logs/chat, retry around tenant policy, grant broad MI Graph
rights, or enable cloud demo identity.

## Reproducible deployment sequence still required

1. Establish private, encrypted remote Terraform state with least-privilege
   access, blob locking, recoverable versions and independent recovery.
   Separate registry/bootstrap, shared, control and each demo state key. Migrate
   cross-module outputs away from the current local-file assumption without
   publishing state or credentials.
2. Parameterize isolated existing group ownership/import explicitly; a plan
   must preserve persistent groups/grants and never adopt original resources.
   Resolve the registry/image/bootstrap dependency before app creation.
3. Build all seven Dockerfiles at a reviewed SHA and record pushed **digests**:
   backend, frontend and all five jobs. Create the dependency-inclusive
   Functions package and record its checksum. Commit tags are not immutability.
4. Apply reviewed shared/control plans using approved SSO references and
   immutable artifacts. Verify private DB/GPU connectivity, approved private
   secret access, intended ingress and correct managed-identity callback
   audiences. Static validation and container imports do not prove these.
5. Prove real authenticated browser/API behavior and negative authorization,
   independent cleanup and bounded cost before GPU allocation. Then use one
   bounded small-model environment for prompt, versioned config, golden,
   compatible benchmark subset, single-stream/concurrency-10 performance,
   report, failure and cancellation acceptance.
6. Preserve exact manifest/workload/counts/failures/timings and limitations.
   Independently verify teardown and residual exposure. Roll back only through
   reviewed app/state/database-compatible paths; see [operations](OPERATIONS.md).

These are unmet release requirements, not claims that a single command or the
existing image-update workflows already implement them. Never turn a blocked
gate into a success by omitting it or substituting old measurements.
