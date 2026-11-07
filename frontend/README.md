# Frontend setup

This frontend is a Vite + React + TypeScript shell for the Azure LLM Serving Demo operator UI.

The static shell and workflow guide are public. Live pages mount only after
the backend verifies `/session` using its normal operator authentication.
Signed-out visitors can navigate the workflow and use **Sign in with Microsoft**;
live environments, configuration, history, reports and all operational actions
remain private. There are no public sample results or invented historical runs.
An expired or forbidden session returns the UI to an explanatory protected state.

This is not a read-only release mode: authorized operators retain the full
workflow, including billable actions. A future public historical showcase needs
a separately approved, sanitized dataset and server-side execution restrictions.

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

- Node.js 18+
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

The app runs on Vite's default port. To point it at a backend API, set:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

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
npm install
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
No token returns 401; missing platform token injection is not a demo fallback.

The real-image smoke uses a synthetic loopback upstream to check path/header
transport and missing-token rejection. It does not validate an Entra session.
Actual platform ID-token injection and authenticated browser requests remain a
separate release gate; see [authentication prerequisites](../docs/AUTHENTICATION.md).

Container builds use the locked local TypeScript/Vite binaries, never `npx`
downloads as a fallback for an incomplete install. Registry fetches are bounded
and logged; missing build tools fail the install layer explicitly. A registry
TLS/network failure must be repaired without disabling certificate verification.
Browser CI uses the same bounded, logged npm fetches without install-time audits,
checks the locked tools exist, and gives dependency/browser installation separate
five-/twelve-minute deadlines. Playwright installation uses the installed local binary,
not an `npx` fallback download.
