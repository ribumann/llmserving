# Azure bootstrap and release gates

**A clean reproducible Azure release is not yet demonstrated.** The modules
describe shared/control/demo layers, but still have local cross-module state,
placeholder image defaults and default to managing their own groups. Shared,
control and demo retained-group modes are opt-in. Existing
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
Protected bootstrap and independently verified actual-resource cleanup are
still pending. No Azure or GPU acceptance
gate is satisfied by credential-free plan tests.

For **fresh non-group-owning shared state**, `infra/shared` also accepts
`existing_resource_group_name`, reads the group as data and keeps all owned
platform resources in it. Deployment region remains `location`, not the existing
group's metadata region. Only opted-in retained mode honors an operator's
`managedBy` tag; default mode preserves legacy tag precedence and resource names.
The original singleton group address has an explicit move to index zero, with
an actual mocked-state upgrade contract. This is **not** permission to switch
old group-owning state to retained mode. Use the
[private exact-plan ownership guard](TERRAFORM_STATE.md#retained-shared-group-and-private-plan-guard)
before any approved retained-group apply.

For **fresh non-group-owning control state**, `infra/control` accepts the same
`existing_resource_group_name` option. It reads, never manages, that group and
requires distinct shared/control/demo/platform groups, a retained demo group,
external SSO with Easy Auth enabled, and an explicit platform infrastructure
group name. Referenced shared resource IDs must belong to the selected
subscription/shared group. Region still comes from shared outputs; retained
child tags honor the operator's `managedBy`. This does not authorize applying
the plan or changing existing group-owning state.

Retained control mode replaces the three legacy subscription grants with
Virtual Machine Contributor at the exact demo group for the backend,
Terraform runner and model worker. The backend gets Website Contributor only
at the isolated Functions site (host-key retrieval) and Jobs Operator only
at its model-deployment job. Functions gets Jobs Operator at each of its five
jobs. Blob/queue/table grants remain at their exact storage accounts. Backend
and Terraform runner receive VM Contributor at the exact shared GPU subnet
only after reading its real role definition and proving unconditional
read/join without subnet write/delete. Missing, conditional, denial-bearing
or unsafe metadata blocks the plan; no broad-role fallback or custom role is
created. These assignments are **proposed source-level scopes**, not existing
grants, permission to grant them, or evidence that denied subscription-level
SKU/quota reads will work. Obtain approval for exact live scopes before apply.
Default managed mode retains its old broad subscription grants and names;
it is not the least-privilege protected deployment path.

Retained shared/control mode sets AzureRM 3.x
`skip_provider_registration=true`; retained demo mode sets AzureRM 5.x
`resource_provider_registrations="none"`. Omitted retained-group input preserves
provider defaults. Required namespaces must already be registered by an
authorized operator; do not grant subscription writes to make a plan succeed.
Do not opt into AzureRM 3's 4.0 beta provider semantics: alternate registration
settings can conflict and must fail configuration rather than trigger a
registration workaround. Native mocked plans do not exercise Azure provider
authentication, registration, actual grants or deny assignments.

Control's VNet-integrated Consumption workload-profile environment accepts
`container_apps_infrastructure_resource_group_name`. Null retains the legacy
platform-generated name; an explicitly approved name is passed to the provider's
create request. Blank/invalid names fail. Existing environment naming is not
changed or force-replaced: a mismatched explicit name fails a postcondition
instead of silently accepting ignored drift. The configured AzureRM 3.117.1
provider supports this input and describes a **platform-managed infrastructure group created
in the subnet's subscription**. Parent control-group scope alone is therefore
not evidence that every created resource is inside the approved allowlist.
Verify the exact infrastructure group, platform creation/deletion behavior and
independent cleanup authorization before live deployment. Do not assume it can
reuse a pre-existing persistent group or add groups/roles automatically.

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

Azure capacity preflight needs approved read authorization for the subscription's
Compute SKU catalog and regional usages (`Microsoft.Compute/skus/read` and
`Microsoft.Compute/locations/usages/read`). Authentication failure or HTTP
401/403 returns `azure_preflight_authorization_failed` (503) from both preview
and creation, before creation-side persistence or provisioning dispatch. A
manual region override cannot bypass it. API responses and preflight logs omit
SDK error bodies/credentials; no new sign-in, alternate identity or grant is attempted.
Non-authorization transport/service failures and missing metadata retain the
existing explicit **unknown** advisory behavior. That fallback is not confirmed
quota, allocation, authorization or permission to spend on GPUs.

### Exact SKU and allocation priority

`configurableInputs.vmPriority` accepts only `Spot` or `Regular`; an omitted input
preserves the existing Spot default. Profile defaults and request overrides are
resolved identically for preview and the saved Terraform `vm_priority`. Regular
requires exact SKU-family and total regional vCPU headroom; Spot uses regional
`lowPriorityCores` and requires the SKU's `LowPriorityCapable` metadata. A false
capability blocks Spot; missing/invalid capability remains explicitly unknown.
Neither path ignores subscription/zone restrictions or confirms physical capacity.
There is no automatic Spot-to-Regular fallback.

The existing small default is **16-vCPU** `Standard_NC16as_T4_v3`, not the
4-vCPU `Standard_NC4as_T4_v3`. A bounded smaller test needs an explicit
`vmSizeOverride` checked against its actual capabilities. Released family quota
does not establish SKU access or Spot compatibility. Spot's bid ceiling can reach
the on-demand rate, and eviction/deallocation retains disks and other billable
resources; neither is cleanup. Regular incurs regular rates. Changing an existing
VM's priority can replace it: use only an approved exact plan, never mutate saved
state or infer deployment permission from this parameterization.

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
