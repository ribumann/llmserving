# Documentation guide

Current implementation and observed results are separated from historical
planning. Start with [the root README](../README.md) or choose a path below.

| Reader / task | Read in order |
| --- | --- |
| Visitor or presenter | [User guide](USER_GUIDE.md), [demo](DEMO.md), [metric interpretation](DEMO.md#interpreting-results), [release evidence](RELEASE_VALIDATION.md) |
| Developer | [Backend](../backend/README.md), [frontend](../frontend/README.md), [architecture by depth](ARCHITECTURE.md), [testing](TESTING.md), [contributing](../CONTRIBUTING.md) |
| Authorized Azure operator | [Private configuration](OPERATOR_CONFIGURATION.md), [auth](AUTHENTICATION.md), [infra](../infra/README.md), [Azure gates](AZURE.md), [app bootstrap](APP_BOOTSTRAP.md) |
| Availability or recovery | [Data and backups](DATA_AND_RECOVERY.md), [Terraform leases](TERRAFORM_STATE.md), [operations](OPERATIONS.md) |
| UI hosting / custom domain | [UI deployment](UI_DEPLOYMENT.md), [auth transport](AUTHENTICATION.md#browser-to-api-transport) |
| Plan AWS / GCP support | [Provider extension roadmap and coding-agent prompt](PROVIDER_EXTENSION.md), [current capability matrix](PROVIDERS.md) |

## Architecture by depth

[Architecture map](ARCHITECTURE.md) teaches the complete C4 L1 context, L2
containers, L3 container components and selective L4 code views. It links
deployment/trust and sequence diagrams as **complementary, not C4** views, with a
guided source trace and glossary. Use it for today's system; do not infer
capabilities from a specification diagram or a Terraform worker definition alone.

## Reference and evidence

| Document | Authority and scope |
| --- | --- |
| [Provider matrix](PROVIDERS.md) | Azure and local Ollama implemented; AWS/GCP unsupported; durable evaluation pending. |
| [Testing](TESTING.md) | Commands and distinction between static, mocked, real local and cloud checks. |
| [Release validation](RELEASE_VALIDATION.md) | Latest dated observations and remaining limits; prior local/pre-GPU evidence retained and labeled. |
| [Canary](AZURE_CANARY.md) | Exact identity-only cleanup evidence; not general resource-cleanup certification. |
| [Azure gates](AZURE.md) | Detailed operator contracts and recovery history. Historical inventory/quota/app-bootstrap statements are not today's live state. |
| [Specifications](../specs/001-llm-serving-demo) | Historical requirements, planning, research and tasks; broader end-state intent, not current release status. |
| [Security](../SECURITY.md), [notices](../THIRD_PARTY_NOTICES.md) | Private reporting, source/dependency/model/dataset license boundaries. |

Public docs intentionally contain no operator identities, subscription IDs,
private endpoints, Terraform state, credentials or raw acceptance datasets.
Keep exact deployment manifests and backups privately, not in this index.
