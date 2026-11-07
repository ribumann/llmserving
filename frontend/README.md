# Frontend setup

This is the Vite + React + TypeScript application for the Azure LLM Serving Demo,
with implemented operator workflows and public read-only views across all screens.
Start with [the demo walkthrough](../docs/DEMO.md) or
[the architecture map](../docs/ARCHITECTURE.md).

Signed-out visitors can browse persisted, sanitized environment/deployment state,
configuration versions, profiles/catalog, test definitions, experiments, aggregate
reports and saved comparisons through the explicit `/public` API. These are real
stored summaries, not sample results or a workflow guide. Raw prompts/outputs,
operator identities, credentials, private endpoints and infrastructure identifiers
are excluded server-side. Capacity/teardown previews, saves, generated exports,
prompts, run submissions and all mutations remain operator-only.

The backend verifies `/session` before mounting the existing operator pages.
Expired or forbidden access immediately replaces those pages with public read-only
views. **Sign in with Microsoft** preserves the current route. Identity-provider
unavailability does not prevent public browsing; public API/database failures have
their own visible error and retry control. Public pages contain no submission forms
and action buttons are disabled, including for keyboard users.

Authorized operators retain their owner-scoped workflow, including billable actions.
Frontend disabling is an affordance, not an authorization boundary: the backend
continues rejecting every unauthenticated mutation and side-effecting preview.

Saving a configuration creates an immutable version; only an explicit deployment
changes traffic. Compare uses the **Result report ID** from completed quality or
performance reports, and its generated URL reopens the persisted comparison.
Exercise prompt history is session-only and clears on close or refresh. Prompt
timing uses the report display convention (integers unchanged, otherwise one
decimal place); API measurements retain their original precision.

Local Vite, the self-hosted Nginx image and Azure Container Apps use the same
application. Container Apps is currently the only implemented cloud UI host;
a second cloud host and standalone local-to-cloud Entra login are not supplied.
Public API reachability is supported without removing operator authentication.
See [hosting and authentication options](../docs/UI_DEPLOYMENT.md).

## Prerequisites

- Node.js 20 recommended (the CI version)
- npm 9+

## Install

```bash
cd frontend
npm ci
```

## Run locally

```bash
cd frontend
npm run dev
```

The app runs on Vite's default port. Create an untracked `frontend/.env.local`
with the loopback backend used by [root setup](../README.md#local-development):

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:18000
VITE_DEMO_USER=presenter@example.com
```

Use explicit local-demo/development authentication and an allowed email domain
on the local backend, plus exact `CORS_ALLOWED_ORIGINS=http://localhost:5173`
(or the actual Vite origin). This is not an authenticated local-to-cloud login
flow. On Windows with `npm.ps1` blocked, use the installed `npm.cmd` entry point;
do not change system execution policy for setup.

## Lint

```bash
cd frontend
npm run lint
```

## Unit tests

```bash
cd frontend
npm run test
```

## End-to-end smoke test

```bash
cd e2e
npm ci
npx playwright install chromium
npm test
```

The Playwright config starts the frontend automatically. Its nine API-mocked
scenarios are browser coverage, not genuine inference or Azure SSO validation.

## Production API transport

Production builds default to same-origin `/api`; set `BACKEND_URL=https://<backend-fqdn>`
on the nginx container at runtime. Do not bake a cloud backend hostname into
`VITE_API_BASE_URL`: that bypasses the same-origin proxy. Local Vite development
retains the explicit API URL and optional `VITE_DEMO_USER`; production builds
never generate a demo identity.

The proxy forwards an Easy Auth ID token as bearer authorization, or preserves
an explicit bearer token. It strips unsigned identity headers and never invents
an identity. The backend still validates the JWT signature, tenant, audience,
expiry and user/domain policy. Upstream HTTPS certificate verification is enabled.
No token returns 401 on operator APIs; `/public` reads do not need a token.
Missing platform token injection is not a demo fallback.

The real-image smoke uses a synthetic loopback upstream to check path/header
transport and missing-token rejection. It does not validate an Entra session.
Actual platform ID-token injection and authenticated browser requests are a
per-target gate; see [authentication prerequisites](../docs/AUTHENTICATION.md)
and [dated existing-target acceptance](../docs/RELEASE_VALIDATION.md).

Container builds use the locked local TypeScript/Vite binaries, never `npx`
downloads as a fallback for an incomplete install. Registry fetches are bounded
and logged; missing build tools fail the install layer explicitly. A registry
TLS/network failure must be repaired without disabling certificate verification.
Browser CI uses the same bounded, logged npm fetches without install-time audits,
checks the locked tools exist, and gives dependency/browser installation separate
five-/twelve-minute deadlines. Playwright installation uses the installed local binary,
not an `npx` fallback download.
