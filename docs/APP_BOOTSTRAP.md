# Main application operator bootstrap

This is the existing frontend ACA + backend ACA + private PostgreSQL/GPU +
Durable Functions architecture, not a second API. No deployment has been
established by these commands. The helper creates no app, credential, service
principal, permission/consent grant, role, DNS record or Azure resource.

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
It prints nonsecret application tfvars, not a complete retained-control
configuration. It does not prove registry pulls, artifact provenance, package
dependencies, state availability, permissions or authentication.

## Exact phase boundary

1. The operator first establishes approved state/locking/recovery and shared
   infrastructure, immutable registry imports, independent cleanup and budget
   gates. Existing lifecycle/plan guards remain mandatory and are not bypassed.
2. Separately create the approved app's first credential using an approved
   secure operator procedure. **Callbacks are not needed to create a credential
   or provision an Easy Auth-protected app.** This helper deliberately cannot
   create credentials or grant Graph/RBAC access. Narrow existing-app ownership
   and any required tenant user assignment/consent remain explicit prerequisites.
3. Use `preview-secret` to read the shared ACR/private vault and the isolated
   app, without requiring a CAE or any callbacks. It refuses existing callbacks
   in this initial-secret phase; it is not a general credential-rotation tool.
   From an approved private-network operator process, store that credential in
   the shared vault. The caller needs separately approved secret-write access;
   never open the public vault firewall or grant subscription-wide privileges.
4. Merge the emitted application tfvars with the reviewed retained-control
   inputs, preserving ownership tags, shared state path, demo/platform groups
   and the explicit SSO tenant. Prepare/review/apply the **full native control
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
6. Deploy the verified Functions ZIP through the approved deployment path; the
   Terraform module does not deploy its Python package.

Shared/state absence is a real stop, not successful bootstrap. The next
operator action is phase 1, then initial credential approval/private delivery.

## Preview and separately approved writes

Use the operator's own existing Azure CLI login, not a transferred credential
cache. The script performs fixed-resource GETs during preview. Azure/Graph
errors fail closed without copying raw diagnostics into logs.

```sh
python scripts/app_bootstrap.py preview-secret --inputs /protected/app-inputs.json
```

The hash binds current live app redirects/token settings, target, images,
ZIP hash, explicit operator UPN and domain policy; callback previews also bind
the real CAE domain. It is an operator confirmation, **not an
authorization grant or signed attestation**. Mutations require independently
approved access. Each write recomputes the live preview; changed inputs fail.
Foreign existing callbacks stop the helper instead of adopting another app.
No Graph permissions or API access-token issuance are added. Supply
the separately approved credential over an already-open, operator-owned pipe
or protected FD (FD 3 below), never a shell literal, argument, environment
variable, echoed terminal or chat. Do not enable HTTP tracing, shell tracing,
process/core dumps or record the secret-producing operator process.

```sh
python scripts/app_bootstrap.py store-secret --inputs /protected/app-inputs.json \
  --approve-preview-sha256 <new-reviewed-preview-sha256> --secret-fd 3
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

The helper cannot verify that a supplied credential belongs to the application.
The operator must establish that provenance and validity in its approved
credential procedure. The helper does not retrieve the secret afterwards.
Do not delete the previous version/credential until real sign-in is verified.

## Acceptance before claiming running and clean

Verify actual frontend Easy Auth sign-in, signed ID-token injection through
nginx `/api`, backend tenant/audience/domain checks and negative authorization
paths. A successfully stored secret is not proof of consent or platform token
forwarding. Also verify Functions package/startup and orchestration, private
database connectivity/migrations, image pulls and cleanup. Database URL
private-vault seeding remains the existing
[in-VNet operator prerequisite](../infra/README.md), separate from this SSO
helper. No GPU work before these gates. A full reviewed control apply and
authenticated browser/API acceptance are still required.
