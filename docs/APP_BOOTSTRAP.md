# Main application operator bootstrap

This is the existing frontend ACA + backend ACA + private PostgreSQL/GPU +
Durable Functions architecture, not a second API. No deployment has been
established by these commands. The explicitly approved `create-secret` operation
adds one credential to the fixed existing app and writes it privately to Key
Vault. The helper creates no app, service principal, permission/consent grant,
role, DNS record or infrastructure resource.

The fixed target is subscription `86677b6e-28fc-48e4-8988-5ab9e568eece`,
tenant `ecd6dfda-d2ce-47a8-9901-e35f31fe18dd` and the explicitly approved isolated
app `962740a1-be3e-454f-87c3-537ed1f02b78`. Never substitute a production app.
Domain ownership of `liberatetheinnerchild.net` does not establish an operator's
Entra UPN domain. The confirmed admin UPN is
`admin@MngEnvMCAP621318.onmicrosoft.com`; explicitly allow its actual domain.
Any additional user domains must be separately selected by the operator.
Custom DNS is optional and is not required for initial Azure default-domain deployment.
Historical resource/workflow names are unchanged.

## Input contract

Create a local JSON file with exactly these fields. Replace every placeholder
with reviewed release outputs; registry **pull** digests are not Docker config
digests. The ZIP is resolved relative to this JSON file. No credential belongs
in this file or in Terraform inputs.

```json
{
  "acr_login_server": "<shared ACR login server>",
  "vault_name": "<shared private vault name>",
  "images": {
    "backend": "<registry>/llmserving-backend@sha256:<64 lowercase hex>",
    "frontend": "<registry>/llmserving-frontend@sha256:<64 lowercase hex>",
    "terraform_runner": "<registry>/llmserving-terraform-runner@sha256:<64 lowercase hex>",
    "model_deployment": "<registry>/llmserving-model-deployment@sha256:<64 lowercase hex>",
    "evaluation_worker": "<registry>/llmserving-evaluation-worker@sha256:<64 lowercase hex>",
    "performance_worker": "<registry>/llmserving-performance-worker@sha256:<64 lowercase hex>",
    "export_worker": "<registry>/llmserving-export-worker@sha256:<64 lowercase hex>"
  },
  "functions_zip": "functions.zip",
  "functions_sha256": "<reviewed ZIP SHA-256>",
  "allowed_email_domains": ["mngenvmcap621318.onmicrosoft.com"],
  "operator_upn": "admin@MngEnvMCAP621318.onmicrosoft.com"
}
```

```sh
python scripts/app_bootstrap.py validate --inputs /protected/app-inputs.json
```

This offline check requires all seven digest references and an actual
checksum-matching Functions ZIP with root `host.json` and `function_app.py`.
It prints nonsecret application tfvars, including the private-executor database
secret opt-in and checked Functions package digest, not a complete retained-control
configuration. Review these proposed inputs before any native plan/apply.
It does not prove registry pulls, artifact provenance, package
dependencies, state availability, permissions or authentication.

## Exact phase boundary

1. The operator first establishes approved state/locking/recovery and shared
   infrastructure, immutable registry imports, independent cleanup and budget
   gates. Existing lifecycle/plan guards remain mandatory and are not bypassed.
2. Obtain narrow existing-app credential/configuration access and private-vault
   secret-write access using the approved local operator identity. The helper
   grants no Graph/RBAC access. **Callbacks are not needed to create a credential
   or provision an Easy Auth-protected app.** Any required tenant user
   assignment/consent remains an explicit prerequisite.
3. Use `preview-secret` to read the shared ACR/private vault and the isolated
   app, without requiring a CAE or any callbacks. It refuses existing callbacks
   in this initial-secret phase; it is not a general credential-rotation tool.
   From an approved private-network operator process, run `create-secret` with
   the reviewed preview hash: Graph `addPassword` returns the one-time value
   directly into this process, which writes it to the shared vault via HTTPS.
   It never passes through stdout, an argument, a subprocess or a file. The
   initial-creation route refuses any existing app passwords and sets a previewed
   90-day expiry. Never open the public vault firewall or grant subscription-wide
   privileges. An already securely created credential may instead use
   `store-secret` with an operator-owned FD.
4. Merge the emitted application tfvars with the reviewed retained-control
   inputs, preserving ownership tags, shared state path, demo/platform groups
   and the explicit SSO tenant. Set `manage_database_url_secret=true` for a clean
   apply from the approved private-network Terraform executor. Prepare/review/apply the **full native control
   plan**, using the normal ownership/scope guards and approvals. Do not use
   `-target`, `-refresh=false` or a partial-plan bypass. The credential already
   exists for initial app secret resolution. Easy Auth stays enabled, but
   interactive sign-in fails closed until final callbacks are configured.
5. After CAE creation, `preview-callbacks` reads its real `defaultDomain` and
   computes exactly `llmrelease-{frontend,backend}.<defaultDomain>`. The separately
   approved `set-callbacks` route updates those two URLs and enables ID-token
   issuance. There is no CAE/app/auth dependency cycle and no temporary anonymous
   app. An interrupted full apply may leave a readable CAE; completing auth
   configuration is not permission to skip recovery/review of that apply.
6. Upload the verified Functions ZIP to its digest-named private host-storage
   blob, then restart/sync triggers as described below. The helper emits the
   checked `functions_package_sha256` Terraform input; Terraform creates the
   private container and configures the package URL, not the package bytes.

Shared/state absence is a real stop, not successful bootstrap. The next
operator action is phase 1, then preview and the approved `create-secret` command.

## Preview and separately approved writes

Use the operator's own existing Azure CLI login, not a transferred credential
cache. The script performs fixed-resource GETs during preview. Azure/Graph
errors fail closed without copying raw diagnostics into logs.

```sh
python scripts/app_bootstrap.py preview-secret --inputs /protected/app-inputs.json
python scripts/app_bootstrap.py create-secret --inputs /protected/app-inputs.json \
  --approve-preview-sha256 <reviewed-secret-preview-sha256>
```

On the Windows private-network operator, set `HTTPS_PROXY` only to the
approved local Squid listener (for example
`http://127.0.0.1:3128`) before `create-secret`. The helper requires a
credential-free loopback endpoint when configured and uses it only for the private Key Vault
HTTPS `CONNECT` tunnel; TLS still validates the vault hostname end to end.
Microsoft Graph requests and Azure CLI subprocesses are direct. The helper
performs a CONNECT/TLS preflight before creating the one-time app credential
and never falls back to direct vault access if a proxy is configured, or accepts
a remote proxy. With both `HTTPS_PROXY` and `https_proxy` unset, the existing
direct private-network/VPN path is preserved.

The control module preserves ACA job names that already fit Azure's 32-character
limit; only overlong names receive a shortened prefix and stable full-name hash
suffix. Dispatch, outputs and role scopes all use the same computed names.
Retained control assigns VM Contributor (join) plus Reader (read) to the backend
and Terraform-runner identities at the **exact GPU subnet**. Both live role
definitions must jointly prove unconditional subnet read/join with no subnet
write/delete, conditions or `not_actions`; no Network Contributor fallback is used.

The hash binds current live app redirects/token settings, target, images,
ZIP hash, explicit operator UPN, domain policy, current credential key IDs and
the new credential's display name/expiry; callback previews also bind
the real CAE domain. It is an operator confirmation, **not an
authorization grant or signed attestation**. Mutations require independently
approved access. Each write recomputes the live preview; changed inputs fail.
Foreign existing callbacks stop the helper instead of adopting another app.
No Graph permissions or API access-token issuance are added. `create-secret`
obtains both tokens before calling Graph and sends the generated secret directly
to the private vault. Run from a process with existing private connectivity.
Do not enable HTTP tracing, shell tracing, process/core dumps or record operator
process memory.

If vault delivery fails after credential creation, the command fails and prints
only the new credential's **nonsecret key ID** for recovery. No automatic retry
or deletion occurs: a failed/interrupted vault request may have succeeded.
Inspect vault secret **metadata** privately and determine whether delivery
succeeded. If the one-time value is lost and a fresh credential is necessary,
explicitly revoke only that new credential before previewing/creating again:

```sh
az rest --method POST \
  --url "https://graph.microsoft.com/v1.0/applications(appId='962740a1-be3e-454f-87c3-537ed1f02b78')/removePassword" \
  --body '{"keyId":"<only-the-new-recovery-key-id>"}' \
  --subscription 86677b6e-28fc-48e4-8988-5ab9e568eece \
  --only-show-errors --output none
```

After an uncertain Graph response, inspect the existing app's password metadata
before any retry; the helper will refuse a second initial credential when the
first is visible. This is not a transactional two-service operation. Use the
explicit expiry in rotation monitoring; never let a 90-day credential expire
without a separately approved rotation.

Alternatively, supply
the separately approved credential over an already-open, operator-owned pipe
or protected FD (FD 3 below), never a shell literal, argument, environment
variable, echoed terminal or chat. Do not enable HTTP tracing, shell tracing,
process/core dumps or record the secret-producing operator process.

```sh
python scripts/app_bootstrap.py store-secret --inputs /protected/app-inputs.json \
  --approve-preview-sha256 <reviewed-secret-preview-sha256> --secret-fd 3
```

The caller opens FD 3 and closes the writer after supplying the credential.
The helper keeps it in memory and sends it only in an HTTPS Key Vault request;
there is no temporary secret file, CLI secret argument, response-body logging
or stdout secret. It never follows redirects. The vault must be private-only,
RBAC-enabled, in the fixed shared group and tenant. CLI token output is captured
in memory, never printed. This operation creates a new secret version and does
not rotate/delete the Entra credential. A failed/interrupted request can have
partially succeeded: inspect remote state privately before retrying.

After the full reviewed control deployment, obtain a **separate callback
preview/hash** and apply only that exact app configuration:

```sh
python scripts/app_bootstrap.py preview-callbacks --inputs /protected/app-inputs.json
python scripts/app_bootstrap.py set-callbacks --inputs /protected/app-inputs.json \
  --approve-preview-sha256 <reviewed-callback-preview-sha256>
```

The FD-only route cannot verify that a supplied credential belongs to the application.
The operator must establish that provenance and validity in its approved
credential procedure. The helper does not retrieve the secret afterwards.
Do not delete the previous version/credential until real sign-in is verified.

## Acceptance before claiming running and clean

Verify actual frontend Easy Auth sign-in, signed ID-token injection through
nginx `/api`, backend tenant/audience/domain checks and negative authorization
paths. A successfully stored secret is not proof of consent or platform token
forwarding. Also verify Functions package/startup and orchestration, private
database connectivity/migrations, image pulls and cleanup. No GPU work before
these gates. A full reviewed control apply and
authenticated browser/API acceptance are still required.

## Database secret and full-apply ordering

The original external-seeding default has a first-deployment gap: the backend
cannot create its initial revision until `database-url` exists, but its generated
password and PostgreSQL FQDN originate in the same full control apply.
`manage_database_url_secret=true` closes this gap without a targeted apply:

1. Approved shared outputs/private DNS and the externally bootstrapped SSO
   secret exist before control planning. The executor must actually reach the
   private vault endpoint, not merely hold ARM Owner. A private ACI capable of
   one OAuth call is not proof of a trusted Terraform execution environment.
   The operator must prepare the approved Terraform version/provider set,
   source, protected state/locking, network path and narrow vault secret-write
   access there before approving a native plan.
2. PostgreSQL/server database creation completes. Native Terraform then writes
   the generated database URL into the shared vault. The backend secret
   reference depends on that resource's versionless URI, so its initial
   revision cannot race the vault write. The backend's existing AcrPull/Secrets
   User assignments and propagation wait remain unchanged.
3. The backend image runs `alembic upgrade head` followed by all four
   idempotent catalog seed commands before starting Uvicorn. Migration/seed
   failure terminates startup rather than reporting a healthy application.
   Test `/readyz` and actual catalog retrieval; `/healthz` alone does not prove
   database schema or seed readiness.
4. Jobs, Functions, exact per-resource runtime permissions and both Easy Auth
   configurations complete in the normal full graph. Configure the final app
   callbacks from the now-real CAE domain.

No new secret output or executor permission is added. The database password/URL
already reside in sensitive Terraform state; the managed secret also persists
its value there. Protect native plans/state and never print, upload or forward
their JSON. Existing `database_url` sensitive output is not an operator handoff
channel. Native mocked plans and graph ordering prove source dependencies,
not private endpoint reachability or a successful Azure apply.

Omitting the opt-in preserves legacy external seeding exactly. Do not enable
it over an already populated `database-url` without inspecting ownership and
reviewing adoption/import: the AzureRM resource checks existing secrets through
the data plane. It does not import an external secret automatically. Only this
secret is newly Terraform-owned; external SSO remains external. Cleanup plans
must account for the owned secret without deleting the retained shared vault.

## Functions deployment and startup

The full graph creates the Functions site with system-assigned identity, then
grants that identity blob/queue/table data roles at its exact private host
storage account and job operator roles at the five jobs. The site may initially
fail to start before those grants/private endpoints become available; no
application package is present yet. This is not a Terraform dependency cycle
requiring a new identity: package upload occurs **after the full apply**,
role propagation and real private storage/DNS reachability checks. An elapsed
timer is not proof of permissions.

The checked runtime workflow packages `.python_packages/lib/site-packages`,
all orchestration/activity modules, `host.json` and `function_app.py`, then
imports/enumerates functions from the extracted ZIP. Use that exact
checksum-verified ZIP with dependencies already installed; do not rebuild or
ask a remote build to fetch different dependencies. This is the existing
orchestration app, not an API replacement. Basic-auth publishing stays disabled.

**Premium code storage is distinct from host storage.** This stack disables
shared keys and has no Azure Files connection/share. A plain Kudu ZIP push or
`WEBSITE_RUN_FROM_PACKAGE=1` is therefore not its supported keyless content
route. The [documented no-Azure-Files Premium path](https://learn.microsoft.com/azure/azure-functions/storage-considerations#create-an-app-without-azure-files)
requires a private Blob package URL and managed identity. Set
`functions_package_sha256` to the verified ZIP checksum **in the original full
native control plan**; its exact blob path is
`functions-packages/functions-<sha256>.zip` in the Functions host account.
The existing host Blob Data Owner role supplies read access, so no additional
app identity, role, SAS, public storage exception or account key is introduced.
The output `functions_package_blob_url` is nonsecret and SAS-free.

After confirming actual private blob connectivity and separately approved
operator upload access, use the reviewed outputs for account/app names:

```sh
python scripts/app_bootstrap.py validate --inputs /protected/app-inputs.json
az storage blob upload --auth-mode login --overwrite false \
  --account-name <functions_storage_account_name> \
  --container-name functions-packages --name functions-<reviewed-sha256>.zip \
  --file /protected/functions.zip \
  --subscription 86677b6e-28fc-48e4-8988-5ab9e568eece \
  --only-show-errors --output none
az functionapp restart --resource-group rg-llmserving-e2e-control \
  --name <functions_app_name> \
  --subscription 86677b6e-28fc-48e4-8988-5ab9e568eece \
  --only-show-errors --output none
az rest --method POST \
  --url "https://management.azure.com/subscriptions/86677b6e-28fc-48e4-8988-5ab9e568eece/resourceGroups/rg-llmserving-e2e-control/providers/Microsoft.Web/sites/<functions_app_name>/syncfunctiontriggers?api-version=2022-03-01" \
  --subscription 86677b6e-28fc-48e4-8988-5ab9e568eece \
  --only-show-errors --output none
```

The uploaded file must be the same path/file hash checked by `validate`, not
another ZIP. Upload refuses overwriting an existing digest-named blob. This
naming/command prevents accidental overwrite; it is not an immutable-storage
policy against another authorized writer. If a blob already exists, verify
its content checksum privately rather than overwrite/adopt it. Package rotation
uses a new reviewed digest and full plan, uploads that new object, then
restarts/syncs. Old objects remain until explicitly reviewed cleanup; never
remove the active package.

No Azure Files means no shared writable content and potentially limited
Premium scale-out. This orchestration-only app must not depend on writable
`wwwroot`; use Application Insights rather than file-log streaming. This is an
intentional documented keyless deployment mode, not a plan/architecture
migration. Omitting the digest preserves legacy settings, not a certified
clean deployment.

After package deployment, confirm that the actual host enumerates both HTTP
routes, both orchestrator versions and six activities before starting work.
Then perform an authenticated bounded orchestration and verify the backend's
managed-identity callback allowlist, job dispatch, cancellation and terminal
state. The backend fetches this site's function key via its existing exact-site
ARM permission; never copy a key into tfvars, logs or acceptance artifacts.
The host can be reachable while storage/role propagation or function discovery
is broken, so successful HTTP ingress alone is not startup acceptance.
