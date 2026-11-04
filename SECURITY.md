# Security policy

This repository is exploratory software, not a production-hardened service.
Only the current default branch is maintained; no production support or
security certification is implied by passing CI.

## Reporting

Use GitHub private vulnerability reporting when enabled. Otherwise contact
the repository owner privately through a published profile contact before
disclosing details. Do not put credentials, tokens, private URLs, user data or
an actively exploitable deployment in a public issue or workflow artifact.
Revoke exposed credentials through the owning provider; deleting a commit or
log is not revocation.

## Authentication boundaries

Cloud operator access requires cryptographically validated Entra user JWTs.
Unsigned demo/principal/email headers are not authentication. `local-demo` is
an explicit development-only mode and is rejected on production/Azure hosting.
Internal workflow callbacks have separate managed-identity audience validation.
Do not broaden bypass paths, disable SSO/JWT validation, retry around Conditional
Access, or grant broad Graph permissions to a deployment identity.

See [authentication prerequisites and limitations](docs/AUTHENTICATION.md).
Actual browser SSO/token injection remains a release gate, not a consequence of
an ARM login or successful OIDC canary.

## Infrastructure and data

Keep pull-request CI read-only and credential-free. Privileged workflows must
use protected refs/environments and pinned OIDC actions; never trust PR artifacts
to select a subscription, resource, deletion target or Terraform state.
Scope identities to isolated resources. Avoid logging even nonsecret
infrastructure identifiers unnecessarily.

Terraform state/plans may contain application and database secrets. Keep them
out of Git, public artifacts and chat; require private encrypted remote storage,
least-privilege RBAC, locking, recoverable versions and tested recovery before
cloud bootstrap. A `sensitive` Terraform variable does not remove its value
from state.

Prompts, outputs and reports can contain personal or confidential information.
Use synthetic CI fixtures, restrict retention/access and review artifact/log
content before publishing. Pass model credentials only through approved
ephemeral/secret channels, never Terraform variables or public evidence.
Cloud execution metadata and secret retention need independent review; a
worker environment variable is not proof of memory-only storage.

Model weights, benchmark datasets and dependencies have their own licenses.
Review exact revisions, gating/consent, notices and supply-chain provenance.
No model catalog label grants redistribution rights.

Cleanup must independently verify exact subscription, ownership tags,
resource type/name/run owner and absence afterward. Preserve persistent groups,
their role assignments, original apps/data and resources owned by other runs.
See [safe operations](docs/OPERATIONS.md).
