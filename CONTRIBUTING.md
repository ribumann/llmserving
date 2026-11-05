# Contributing

This is an exploratory MIT-licensed control plane. Keep contributions scoped,
preserve API/report schemas and saved configurations, and retain
[license and attribution notices](THIRD_PARTY_NOTICES.md). Do not import private
source/history, screenshots, telemetry, database contents, model credentials,
Terraform state or other users' deployment configuration.

## Development

Use Python 3.11+, Node 20 and the checked-in dependency manifests/lockfiles.
Follow [backend setup](backend/README.md), [frontend setup](frontend/README.md)
and [complete testing commands](docs/TESTING.md). Use a disposable PostgreSQL
database, explicit local-demo authentication and synthetic test inputs.
Local development and pull-request CI must not require cloud credentials.

Backend, Functions and worker environments are separate: their current Azure
Compute SDK constraints differ. Do not solve an install failure by changing
authentication, skipping integration tests or substituting a different
`llmperf` package. Genuine ray-project LLMPerf is pinned to
`f1d6bed47e4501b0e371082b41601b59ab55269f`.

## Pull-request gates

Every implementation PR requires independent agentic code review and passing
checks at its actual head commit before merge. Address meaningful findings and
rerun affected gates after changes. Never push implementation directly to main,
bypass failing checks, weaken tests, or grant a pull request Azure/OIDC write
permissions to make CI pass.

Required coverage follows the changed surface: backend Ruff/Black and full
PostgreSQL pytest, all Functions/jobs, frontend lint/build/unit, API-mocked
Playwright, all Terraform modules, every container and Functions package.
Add focused regressions for behavior changes; do not describe mocked tests as
full-stack or historical results as fresh acceptance.

Preserve the existing UX and report contracts. New provider names must be
explicitly supported or rejected, never silently mapped to Azure. Keep
capability flags tied to implemented routing and verified semantics. In
particular, do not enable durable evaluation or remove API runners before
golden/benchmark/genuine LLMPerf/report and lifecycle parity.

## Infrastructure and evidence

Cloud deployment is an opt-in protected-main operation, not a PR test.
Read [Azure bootstrap](docs/AZURE.md), [authentication](docs/AUTHENTICATION.md)
and [operations](docs/OPERATIONS.md) first. Preserve existing resources, shared
CLI defaults and original state; never infer that a resource is disposable
from its name alone.

Document exact commit/image/model versions, workload/counts/failures and
measurement semantics. Clearly separate static validation, mocked browsers,
real local inference and authenticated Azure/GPU acceptance. Update related
guides and Mermaid diagrams when architecture changes. Render diagrams locally
before publication; do not send private diagrams or data to online renderers.

Report suspected vulnerabilities privately using [the security policy](SECURITY.md).
