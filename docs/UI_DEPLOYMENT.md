# UI hosting, public APIs and authentication

Use the existing application for demos and exploration. A publicly reachable
backend is intentional: the UI and headless clients use the same operator API.
Public reachability does **not** make provisioning, model deployment or runs
anonymous. Keep their signed-token authentication and authorization enabled.
There is no separate anonymous playground API or reduced duplicate application.

The frontend static shell and workflow descriptions are accessible without
sign-in. In Container Apps, only the **frontend** Easy Auth policy allows
anonymous requests; its identity provider remains enabled for explicit sign-in.
Nginx still rejects `/api` requests without a token, backend Easy Auth remains
enabled, and the backend independently validates signed operator JWTs.

Before mounting a live page, the UI checks the authenticated `GET /session`
endpoint through the same API proxy. A 401 or 403 shows an intentional protected
state, not an automatic failed-data panel. Other session-check failures keep
live pages locked with a retry action. Sign-in returns to the requested route;
no credentials are stored by the frontend and private API responses are not
cached. Static workflow descriptions are not historical run evidence.

Authorized operators still have the full workflow. This public shell is **not**
the future read-only open-source showcase: publishing sanitized historical
examples and disabling execution server-side are separate release changes.

## What the repository currently supports

| UI option | Implementation | Authentication and limits |
| --- | --- | --- |
| Local development | Vite; `frontend/README.md` | Explicit local backend `AUTH_MODE=local-demo`; development-only demo header. Not cloud authentication. |
| Self-hosted container | `frontend/Dockerfile`, Nginx same-origin `/api` proxy | Forwards a real bearer token or a platform-injected ID token; does not provide a login service itself. |
| Azure Container Apps | `infra/control`, `frontend.yml` image update | Existing public UI/backend ingress and Easy Auth configuration, plus independent backend JWT verification. This is the implemented cloud UI host. |
| Second cloud UI host | Not implemented | App Service for Containers could reuse the Nginx image and Easy Auth pattern, but needs its own infrastructure, identity/secret configuration, callbacks and tests. Static hosting alone cannot replace the token-forwarding proxy. |

Local/self-hosted and Container Apps are different hosting paths, not two
implemented cloud hosting services. Do not describe App Service or Static Web
Apps as supported deployments merely because they can host React. No second
host is required to exercise the application through its existing UI or API.

## Straightforward local exploration

Use the backend and frontend setup guides, an isolated PostgreSQL database and
the local Ollama profile. Set `AUTH_MODE=local-demo`, `APP_ENV=development` and
an explicitly allowed demo email domain on the **local** backend. Set
`VITE_API_BASE_URL` to that backend and `VITE_DEMO_USER` to a matching email for
Vite. Also set backend `CORS_ALLOWED_ORIGINS` to the exact Vite browser origin
(for example `http://localhost:5173`); it defaults to an empty list. Use the
actual origin if Vite selects another port, and do not substitute a wildcard.
Do not use this configuration on an internet-facing server.

This keeps the same provisioning/configuration/prompt/run/report APIs as the
cloud application. Local Ollama is not evidence of Azure deployment or GPU
performance. See [testing](TESTING.md) for the real-model evidence boundary.

## Existing cloud UI and headless API

The Container Apps UI serves the existing Nginx/React image. Browser requests
use same-origin `/api`; Nginx strips `/api` and forwards to `BACKEND_URL` over
certificate-verified HTTPS. The default Terraform configuration gives both
frontend and backend external ingress and Easy Auth. Backend JWT validation
still checks issuer, tenant, audience, expiry and allowed user domain.

Headless clients can call the backend directly with an approved **user** bearer
token for its configured audience. For example, with a token supplied privately
by an approved authentication mechanism:

```sh
curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${OPERATOR_TOKEN}" \
  "${BACKEND_URL}/providers"
```

Do not enable shell tracing, commit tokens, print them or place them in frontend
build variables/browser storage. This command does not obtain a token, grant
consent or demonstrate a live authenticated deployment. The operator validator
rejects application-only identities; internal service callbacks have a separate
managed-identity authentication contract. Automated headless actions must not
assume an arbitrary ARM or application-only token authenticates as an operator.

## Local UI with an authenticated cloud backend

Easy Auth is an option at the cloud hosting edge, not a feature supplied by a
local Vite server. A local UI cannot authenticate simply by setting
`VITE_API_BASE_URL` to a remote API or adding `X-Demo-User`.
The current frontend has no standalone Entra login/token-acquisition flow.
Direct cross-origin usage also needs an explicitly allowed backend CORS origin;
the existing API client does not opt into cross-origin session cookies.

For the implemented authenticated browser path, use the cloud-hosted UI and
its same-origin proxy with actual Easy Auth ID-token injection. Supporting an
authenticated local UI requires an approved login/redirect and token transport
flow, not disabling JWT checks or copying cached credentials. See
[authentication](AUTHENTICATION.md) for the existing configuration and consent
requirements. Historical deployment success is useful context, not verification
that a new tenant, callback, identity or secret is already configured.

## Optional frontend custom domain

The generated frontend and backend hostnames and their SSO callbacks remain in
use. To add a subdomain you control, choose the hostname and verify the target
frontend app, Container Apps environment and authoritative DNS zone before
making any changes. The DNS zone can be in a different resource group or with
another provider; neither that zone nor its records are managed by this module.

1. If Terraform manages the Entra application, set the control module input
   `additional_frontend_sso_redirect_uris` to a list such as
   `["https://ui.example.com/.auth/login/aad/callback"]` in your private
   deployment inputs and review a full plan before applying. The default is
   empty; Terraform retains both generated callbacks. Only exact HTTPS Easy
   Auth callback URLs on DNS hostnames are accepted.
2. With an external SSO application, this input does not update its registration.
   Have its authorized owner add the exact custom callback to the existing
   frontend and backend callbacks through the approved directory workflow.
   The external bootstrap helper's two-callback ownership checks are not a
   custom-domain management workflow; do not use it to overwrite additional
   callbacks.
3. Obtain the frontend's generated FQDN and domain verification ID with
   `az containerapp show` (`properties.configuration.ingress.fqdn` and
   `properties.customDomainVerificationId`). At the authoritative DNS provider,
   add a CNAME from the chosen subdomain directly to that FQDN and a TXT record
   named `asuid.<subdomain>` containing the verification ID. Keep these records
   for issuance and renewal; an intermediate CNAME can prevent both.
4. Following Microsoft's [managed certificate instructions](https://learn.microsoft.com/en-us/azure/container-apps/custom-domains-managed-certificates),
   add the hostname and bind a managed certificate with CNAME validation using
   the Azure CLI or portal. HTTP ingress must be publicly reachable by the
   certificate authority, the app must be running, and any CAA policy must
   permit the issuer. Verify the binding is secured and HTTPS validates.
5. Visit the custom hostname, use the normal sign-in flow, and verify an
   authenticated same-origin API request. Also verify the generated frontend
   hostname still works. This does not change public frontend viewing or
   backend authorization.

DNS, the certificate and the frontend hostname binding are externally managed.
Terraform ignores only `frontend.ingress[0].custom_domain` (as well as its
pre-existing image ignore); other ingress and auth configuration remains
Terraform-managed. Monitor the external binding and certificate separately:
Terraform will not repair their drift, and a replacement frontend must be
rebound. Review the full plan before applying, including any resource
replacement and SSO redirect changes.

## Network and deployment boundaries

Public backend ingress is supported; a private backend is not required by the
application design. PostgreSQL, Key Vault and the GPU inference VM have separate
private-network configuration in the existing Terraform stack. Do not conflate
the public control API with directly exposing a database, SSH or inference port.

The existing deployment workflows update images in already provisioned apps.
They do not bootstrap all infrastructure or prove billable-resource cleanup.
For a new isolated deployment, retain the existing Easy Auth architecture and
verify exact target ownership, artifacts, deployment prerequisites, SKU/quota
and independent cleanup before resource creation. Preserve the original
deployment. See [Azure gates](AZURE.md); a released GPU-family quota alone does
not override SKU restrictions or prove physical allocation.
