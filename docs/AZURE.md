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

The separate `Azure fallback read-only preflight` workflow uses the existing
protected fallback OIDC environment from `main`. It verifies the exact fallback
identity, retained group IDs and campaign ownership tags, reports only resource
counts/types, and queries `az vm list-skus --all` plus quota for the exact
Italy North `Standard_NC4as_T4_v3`. It never creates resources, registers
providers, changes CLI defaults, performs VM validation or alters roles/tags.
Azure CLI errors fail explicitly without publishing raw diagnostic payloads;
investigate the precise denial privately. No token/credential transfer is
needed from another machine.

The report retains restriction **types**, zones and `locationInfo` rather than
turning a Zone restriction into a region-wide denial or permission for an
unzoned deployment. Quota, SKU listing and an empty inventory do not prove
allocation, app bootstrap, SSO or billable-resource cleanup. Missing metadata
is not permission to spend. The script's read-only command allowlist and fixed
target are covered by credential-free tests. This is a new inspection workflow,
not evidence it has already run or that application deployment is ready.

The first protected inspection reached SKU parsing after successful OIDC and
group ownership/inventory reads, but rejected Azure's mixed-case `ItalyNorth`
location identifier. Region identifier matching is now case-insensitive while
SKU name/type remain exact and duplicate matches fail closed. The original
metadata failure was not an SKU eligibility denial; zonal restriction contents
are preserved unchanged.

Azure CLI can serialize usage counts as strings. Preflight normalizes
nonnegative JSON integers or 1–20 ASCII decimal digits to integers; booleans,
floats, signs, whitespace, scientific notation, non-ASCII digits and missing
values remain errors. The exact SKU family matches quota `name.value`
(case-insensitive), never a localized display label or an unrelated GPU family.
All three unique family/regional/low-priority rows remain mandatory. The second
inspection reached this count check, not an Azure quota denial.

The corrected protected inspection
[42028735853](https://github.com/ribumann/llmserving/actions/runs/42028735853)
passed at source `f52ce573f7a72c983f66b0dd42a65cb3707575da`.
All four inspected persistent groups were empty. Family/regional/low-priority
usage and limits were respectively 0/8, 0/108 and 0/100. The exact SKU retained
its Zone restrictions; unzoned eligibility and allocation remain unverified.
This observation is not a permanent quota, access or deployment guarantee.

For the same protected-main inspection, optional `inspect_bootstrap=true` adds
**fixed GET-only** reads of caller permission rules at the four retained groups
and exact approved ACA infrastructure-group scope, plus metadata for the already
identified fallback test app. It does not create another app or credential,
request secret values, grant roles, register providers or change redirects.
It also reads registration states for the exact namespaces used by this stack;
a missing registration is a separate operator prerequisite, never auto-registered.
The [documented Authorization API](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/authorization/resource-manager/Microsoft.Authorization/Authorization/stable/2022-04-01/authorization-RoleDefinitionsCalls.json)
is used for group permission rules, including management/data-action exclusions.
Only scoped booleans/counts are reported, not raw role/app objects or credential
metadata. App redirect/active-password counts are not consent or browser proof.

An unread/denied/absent scope is explicitly listed as **unverified**, never
converted to an empty allowlist or positive authorization. The operation prints
the partial report and fails if any scope cannot be read. Successful rule reads
still do not verify deny assignments, subscription-level group creation, ACA
platform behavior, private-vault access, exact new callbacks or a completed
bootstrap. The approved infrastructure-group name alone grants no permission.
Stop before any required role expansion and request authorization for its exact
scope; do not broaden parent/subscription rights to make inspection succeed.
No live bootstrap inspection is claimed by this source change.

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

### Fixed shared-stack native plan scope

The generic retained-group guard is ownership-only. For the isolated fallback
campaign, `scripts/validate_shared_plan.py` additionally requires the fixed
subscription, Italy North, `release` stage, `llmrelease` prefix, campaign tags,
and no public-vault exception. Initial plans must contain exactly the 29
reviewed shared creates from fresh non-group-owning state. Owned destroy plans
may contain a subset after partial provisioning, but only pure deletes covering
every prior managed resource and leaving no managed resources.

The guard checks fixed primary names/IDs/tags and selected security fields,
association targets/IDs and native configuration references for unknown new
association IDs, including the vault endpoint's exact nested vault/DNS targets.
Managed resources and context data must bind to the single fixed AzureRM
provider configuration, which must use the fixed subscription variable.
It rejects resource groups, state storage, roles, unexpected
addresses/types, updates/replacements, child modules and foreign data context.
It is **not** a complete Azure policy/security validator, a remote-state setup,
or independent cleanup implementation.

Run from the initialized pristine shared module using a saved native plan and
a **new** private log path:

```sh
python /approved/source/scripts/validate_shared_plan.py \
  --operation create --plan /protected/shared.tfplan \
  --private-log /protected/shared-scope-check.log
```

Use `--operation destroy` only for an explicitly prepared saved destroy plan.
The helper copies the plan privately, suppresses Terraform diagnostics into a
mode-0600 log, and **never applies** it. Do not upload native plans, JSON, logs
or state. The original module's local-state defaults are unchanged. Passing
does not authorize state data-plane grants/use/migration, establish remote
locking/recovery, prove live destroy behavior, or permit billable provisioning
before the independent persistence/cleanup gates are complete.

### Operator-only retained state bootstrap comes first

The reviewed [bootstrap gate](../infra/bootstrap/README.md#initial-saved-plan-execution-gate)
can create only the account, default blob service and private container. It does
**not** depend on temporary shared-stack deletion: these three resources are
intentionally retained, with local bootstrap state and `prevent_destroy`, and
are excluded from shared cleanup. This is not an Azure lock or a tested restore.

Before any independently authorized operator execution, verify fresh ARM
inventory in the explicit fallback subscription: the named account must be
absent and the retained group's five campaign tags unchanged. Also require
typed `nameAvailable=true` from:

```sh
az storage account check-name --name llmreleasestate0ea5e6 \
  --subscription 86677b6e-28fc-48e4-8988-5ab9e568eece -o json
```

Denied, ambiguous, present or unavailable means **stop**, never adopt. From
the durable private initialized bootstrap directory, with the same separately
approved isolated operator authentication and Terraform 1.16.6:

```sh
python /approved/reviewed-source/scripts/validate_bootstrap_plan.py \
  --plan /protected/bootstrap.tfplan \
  --expected-target /protected/independent-bootstrap-target.json \
  --private-log /protected/NEW-bootstrap-apply.log \
  --terraform-bin /approved/terraform-1.16.6 --apply
```

Keep restricted local state and a second private backup of the resulting state,
backups, reviewed source/provider lock, inputs and log. Never copy CLI/token
caches or upload these files. Verify exactly three managed state addresses and
ARM security settings, not blob data. Partial apply requires preserving
state/log and a separately reviewed recovery; the initial-create guard cannot
resume/update and is not a blanket destroy path. Only **after the account
exists**, and only following separately affirmative account-scoped approval,
may an operator assign Blob Data Contributor to the existing UAMI. Neither
operator availability nor this runbook authorizes that grant, data access,
migration, app credentials/consent, shared provisioning or ACA changes.

### Disabled one-shot shared lifecycle source

`azure-fallback-shared.yml` and the separate
`azure-fallback-shared-cleanup.yml` implement a **one-shot temporary shared
campaign**, not application deployment. They are disabled unless an authorized
operator explicitly records repository variables
`FALLBACK_STATE_DATA_ACCESS_APPROVED=true` and
`FALLBACK_SHARED_CLEANUP_ARMED=true`; creation additionally needs
`FALLBACK_SHARED_CREATION_ENABLED=true`. Do not set these based on inferred
approval. The first flag remains unapproved for the current campaign.
Identity secrets stay in protected, main-only `azure-e2e-fallback`.

The controller requires the existing exact keyless bootstrap account/security
and uses only OAuth at `tfstate/shared.tfstate`, with a conditional
`shared-owner.json` claim. No account/group/role/credential is created by the
controller and no local state is migrated. Backend locking is Terraform's
native mechanism; never force-unlock. Four additional resource tags bind the
exact creating run, attempt, source and four-hour deadline. The protected
owner record is independently checked against GitHub's exact run-attempt API,
including repository/main/manual/workflow/source and trusted creation time.
Creating attempts cannot overwrite existing owner/state data, even after
cleanup; a later campaign needs a separately reviewed recovery/rearm design.

The independent completion workflow handles failure/cancellation immediately;
successful creation is eligible after four hours, or earlier explicit manual
cleanup. Hourly scans retry and continue auditing cleaned owner records for
late completions. Scheduling, denied access, in-flight runs and live dependencies
can delay cleanup: this is **not a guaranteed spending deadline**. GitHub's
shared, non-cancelling concurrency group also serializes registry imports.
Control/demo groups must contain no resources before create or delete; this
controller never tears down their dependencies on their behalf.

Fresh staging pins Terraform 1.16.6/AzureRM 3.117.1 and disables Key Vault
purge/recovery **only in that staged fallback module**; original module defaults
remain unchanged. Exact live cohort-tagged primary orphans, including VNet
subnets and DNS links, may be imported into the same owned backend for recovery.
Foreign/unverifiable roots, subnets, links, provider/state bindings or generated
resources stop cleanup rather than broadening deletion. A private endpoint's
generated NIC/DNS group is accepted only with its verified owned parent and
relationship, never independently deleted. Other orphan forms require a
separately reviewed recovery. A soft-deleted vault is intentionally not purged,
so immediate same-name reuse is not promised.
Owned destruction also accepts an absent endpoint DNS group after interrupted
creation/deletion, but never a foreign group or missing service connection.
An empty refreshed destroy plan may persist already-completed deletions only
when no managed prior/planned resources or changes remain; stale managed
resources without corresponding delete changes still fail. Creation and the
standalone scope-check CLI remain strict.

Every apply uses a private native saved plan checked by the fixed shared guard;
only exact initial creates or pure owned deletes are permitted. Plans, state
and raw Terraform diagnostics are private ephemeral runner files, never public
artifacts; failed runners do not provide persistent raw logs. Preserve the
protected backend/owner records and use authorized Azure Activity Log inspection
for recovery. Source/schema/unit checks are **not actual state access,
locking/restore, cancellation cleanup or deployment evidence**. Those live
proofs and appropriate approval are required before treating the source as an
operational provision/cleanup gate.

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

### Fixed billable-disk cleanup proof

The separate `Azure fallback billable disk probe` and
`Azure fallback billable disk cleanup` workflows test **only one unattached empty
managed disk**, not app/VM/DB/network cleanup. The creation workflow is manual,
protected-main-only and intentionally fails after creation or waits up to
15 minutes for external cancellation. The independent cleanup runs on completion
(including failure/cancellation), hourly and manually. Both workflows share a
non-cancelling concurrency group; cleanup checks the exact owning run **attempt**
is completed before deleting. Rerunning a creator cannot adopt an existing disk.

| Reviewed resource manifest | Fixed value |
| --- | --- |
| Target | Existing fallback subscription/tenant/OIDC principal only |
| Parent | Existing campaign-tagged `rg-llmserving-e2e-demo`, preserved |
| Resource | `disk-llmserving-release-cleanup-probe`, Italy North |
| Shape | One empty 4 GiB `Standard_LRS` managed disk, unattached |
| Access | `DenyAll` network policy; public disk access disabled |
| Ownership | Exact campaign, purpose, repository, source SHA, run ID and attempt tags |
| Other mutations | None: no group, role, identity, VM, NIC, public IP, model or app creation |

Before any dispatch, require passing fresh-main guards and independent
exact-source review. Every creation queries the fixed public Azure Retail Prices
API and requires exactly one current primary Italy North S4 LRS consumption
price in USD/month, greater than zero and at most USD 10/month. An unavailable,
ambiguous or differently shaped quote refuses **before any Azure command**.
The billing tier can exceed the requested 4 GiB. One month of delayed-cleanup
contingency for this disk is therefore at most USD 10, excluding taxes/contract
adjustments; this is not a hard lifetime spending limit.
Manual Cloud safety CI dispatch also queries this public price without Azure
credentials or resource mutations, so its real response can be checked before
the probe. Source/tests alone are **not** live cleanup evidence or a price quote.
The expiry tag is advisory,
not an Azure TTL or hard spending cap. GitHub/Azure outages can delay cleanup;
inspect the exact owned disk and use the separately reviewed cleanup workflow,
never a group deletion or wildcard sweep. A foreign/malformed disk, changed
ownership, attached disk, untrusted or active owning run fails closed without
deletion. Any failure to verify disk absence remains a release blocker.

The first live disk exercise reached Azure creation but its post-create guard
and independent cleanup rejected the CLI size field: Azure returns
`diskSizeGB`, not `diskSizeGb`. The guard now requires the exact CLI field to
be integer `4`; it does not accept a guessed alias, missing value, string or
larger size. All other scope/shape/ownership/run checks are unchanged. This
schema correction alone is not evidence that recovery or cleanup succeeded.

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
Creation rejects a known-negative selected Azure SKU/quota assessment with
`409 azure_preflight_unavailable` before key generation, persistence or dispatch,
including an explicit region override. Preview remains diagnostic. Unknown
non-authorization metadata retains its documented advisory semantics; it is not
confirmation of availability or permission to spend.

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

### Minimum fallback path using the existing application

Keep the current public frontend/backend and Easy Auth pattern. Do not fork
the app into an anonymous playground, force private backend ingress or expose
the database/GPU inference port to make deployment simpler. Local/self-hosted
UI and headless API usage are documented in [UI deployment options](UI_DEPLOYMENT.md).

Use the already verified retained shared/control/demo groups and the exact
approved additional ACA platform group `rg-llmserving-e2e-aca-infra`. Its scope
approval is not proof of effective create/delete rights, permission for new
role grants, or evidence that ACA accepts an existing group. Check those exact
platform behaviors and effective grants before creating a Container Apps
environment; preserve all persistent groups and their existing grants.

The smallest existing-stack bring-up still has separate, ordered phases:

1. Prepare checked image/Functions candidate archives without Azure access.
   Record source/run/checksum identity as described below. An archive bundle
   removes the need to rebuild code during bootstrap; it does not create ACR.
2. Verify narrowly scoped bootstrap/state permissions and independent cleanup
   of the exact owned resource types. Prepare protected state/locking and the
   isolated registry/shared network/vault resources. No subscription-wide
   grant or provider-registration fallback.
3. Import verified image archives into the isolated registry and record actual
   registry pull digests. Complete the approved fallback Easy Auth application:
   final new callbacks, client UUID, approved domains/consent and a privately
   written versionless vault credential reference. No original app reuse.
4. Apply an exact reviewed retained-control plan with those artifacts and SSO
   inputs. Verify real UI/headless authentication, DB readiness and independent
   cleanup before GPU work. Existing image-update workflows alone cannot
   bootstrap empty groups.
5. After exact GPU manifest/cleanup review, a non-mutating unzoned VM validation
   may clarify SKU eligibility. The protected SKU listing is not that
   validation. Use explicit `Standard_NC4as_T4_v3`, not the 16-vCPU default,
   with an explicitly reviewed priority; do not infer restriction clearance
   or change allocation policy from differing capability observations.

These are execution phases, not a request for another architecture approval.
Current incomplete app/secret/callback bootstrap and unverified effective
platform-group/cleanup permissions are concrete target prerequisites; absence
of Azure CLI on one machine is not a blocker when protected OIDC or an
authorized isolated CLI profile is available.

### Credential-free checked artifact candidates

Runtime CI supports a **manual `main` dispatch only** with
`package_release=true`. Normal push/PR checks and default manual runs do not
export image archives, receive cloud credentials, push to a registry or deploy.
The option exports the exact locally tagged image after its existing import/
HTTP/toolkit checks, not a later rebuild:

```sh
gh workflow run runtime-ci.yml --repo ribumann/llmserving \
  --ref main --field package_release=true
```

Each of seven `release-image-<component>-<attempt>` artifacts contains a gzip
Docker-save archive. The Functions package remains in `functions-<source-sha>`.
Small per-component records and `release-manifest-<attempt>` bind all eight
files to source SHA, run ID and attempt, filename, size and SHA-256. The manifest
job requires all runtime jobs (including real model/browser/toolkits) to pass
and rejects incomplete or mixed-run records. Individual artifacts from a
failed/partial attempt are **not a complete candidate**. To regenerate a
candidate after failure, start a new full dispatch rather than mixing successful
jobs from different attempts. Artifacts expire after seven days; retain approved
copies in protected storage before expiry, not in Git.

Before any archive import, obtain the expected source/run/attempt from the
trusted Actions run, not from downloaded artifact content. Set
`GITHUB_REPOSITORY`, `GITHUB_REF=refs/heads/main`,
`GITHUB_EVENT_NAME=workflow_dispatch`, `GITHUB_SHA`, `GITHUB_RUN_ID` and
`GITHUB_RUN_ATTEMPT` to that expected identity, then verify all eight archives:

```sh
python scripts/release_bundle.py verify \
  --manifest /protected/candidate/release-manifest.json \
  --archives /protected/candidate/archives
```

The verifier requires exact component filenames, rejects symlinks, duplicate/
unknown/missing components and changed archives, and streams file hashing.
It does not load or execute archives. After a successful hash verification,
load only into an isolated trusted Docker host; verify each loaded image's
config ID matches `imageConfigDigest` before registry import. A Docker config
ID is **not** an OCI registry pull digest; record the actual pushed registry
digest before deployment. This is checksum-bound retention of a checked build,
not a signed provenance attestation, dependency lock, reproducible rebuild,
public GitHub release or proof of cloud deployment. No model weights, secrets,
Terraform state or database contents are bundled.

### Consume the retained candidate without rebuilding

`azure-fallback-release-import.yml` is a protected `main`-only manual consumer
of Runtime CI run `42031238122`, attempt `1`, source
`1f9f15f2c7046c81f9b988170d77ea3750a3ac65`. The expected identity is fixed
in reviewed source, never chosen by the downloaded manifest. It verifies the
successful producer attempt through GitHub and the fixed reviewed manifest
SHA-256 `2392632e34ff4622fdb4ab311637e9e70767cccb2b2ae91f1632b3451c2a3c7a`,
hashes all eight actual downloads,
then Docker-loads the seven checked images and compares Linux/amd64 config IDs.
It does not run their application entrypoints or claim new runtime acceptance.

```sh
gh workflow run azure-fallback-release-import.yml --repo ribumann/llmserving \
  --ref main --field push_to_registry=false
```

The default above performs **no Azure login or resource mutation**. Candidate
expiry or missing files fail closed; this workflow cannot select a replacement
build. A new candidate requires a reviewed source change.

Only after the approved persistence/provisioning/independent-cleanup gates have
created the shared registry may an authorized operator explicitly select
`push_to_registry=true`. The same download/hash/Docker-load gate completes
**before** OIDC login. Publication accepts only the existing
`llmreleaseacr0ea5e6` Basic registry in `rg-llmserving-e2e-shared`, Italy North,
with the fixed fallback subscription/principal, campaign/shared/stage tags and
admin credentials disabled. It never creates or adopts a registry/group, grants
roles, generates credentials, or falls back to another identity.

Images use `tested-<source-sha>` tags. An existing tag must first pull to the
expected config ID; a different image is rejected without overwrite. Missing
tags are published through a unique source-bound upload tag and ACR's server-side
**NoForce** import (never `--force`), so a concurrently created source tag cannot
be overwritten between inventory and publication. The verified upload tag is
untagged after successful promotion; failures can leave a source-bound upload
tag in the owned registry for operator inspection or whole-registry cleanup. Each
published image is pulled by its **actual registry manifest digest**, checked
against the tested config ID, and its tag and manifest write/delete flags are
disabled and read back. Privileged registry administrators can change those flags; deployment
must use the recorded digest references, not trust a tag. A partial push/lock
failure fails the run; an exact-image rerun can finish the remaining work.
No registry resources are deleted automatically by this consumer.

Successful nonsecret evidence is retained for seven days as
`checked-import-<run-id>-<attempt>` and distinguishes download/load-only evidence
from registry publication. Functions remains a checksum-verified ZIP, not an
image. Neither mode deploys applications, downloads models, proves full-stack
cleanup, or supplies the outstanding state-data/auth/ACA permissions.

### Remaining full release acceptance

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
