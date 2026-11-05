# UI hosting, public APIs and authentication

Use the existing application for demos and exploration. A publicly reachable
backend is intentional: the UI and headless clients use the same operator API.
Public reachability does **not** make provisioning, model deployment or runs
anonymous. Keep their signed-token authentication and authorization enabled.
There is no separate anonymous playground API or reduced duplicate application.

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
Vite. Do not use this configuration on an internet-facing server.

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
