# Protected Azure OIDC and cleanup canary

This is a safety gate, not application deployment or GPU validation. The only
created resource is one fixed user-assigned managed identity (no compute, disks,
networking, database, or role assignments). Its resource group and the federated
login identity must already exist. **Never delete the resource group.**

**Current execution pause:** both canary and cleanup workflows are explicitly
disabled while the coordinator reassesses exact target/scoped identity setup.
The recorded successful runs below remain historical evidence for their
original target only. Scheduled fallback does not execute while its workflow
is disabled. Do not re-enable or transplant federation to another subscription
without approved scoped setup and an independent cleanup plan.

## Prerequisites

Configure the `azure-e2e` GitHub environment with a main-branch-only deployment
policy and these nonsecret environment variables:

| Variable | Meaning |
| --- | --- |
| `AZURE_CLIENT_ID` | User-assigned login identity with environment-scoped federation |
| `AZURE_TENANT_ID` | Expected tenant |
| `AZURE_SUBSCRIPTION_ID` | Exact authorized test subscription |
| `AZURE_CANARY_RESOURCE_GROUP` | `rg-llm-cleanup-canary-oss-e2e` |
| `AZURE_CANARY_REGION` | Existing canary resource group's region |

Federation must trust only the repository's `environment:azure-e2e` subject.
The login identity requires Contributor only on that pre-existing canary group;
the workflow does not grant itself permissions. Group tags must be exactly
`project=llmserving-public-validation` and `managedBy=copilot-release`.
Identifiers are masked before the pinned Azure login action executes.
No long-lived Azure credential is required.

## Independent failure and cancellation exercises

After review, credential-free Cloud safety CI, and merge to main:

1. Dispatch **Azure OIDC canary** on main with `outcome=failure`. It must create
   and verify the identity, then deliberately fail.
2. Verify a separate **Azure canary cleanup** `workflow_run` completes
   successfully and logs verified identity absence.
3. Dispatch the canary with `outcome=cancellation`. Wait for the create-and-verify
   step to finish, then cancel it externally (for example, `gh run cancel`).
4. Verify another separate cleanup succeeds and verifies absence. Record links
   to both canaries and both cleanup runs; do not describe the deliberate failure
   as an application failure.

The canary times out after 20 minutes; the cancellation wait is bounded to 15
minutes. Cleanup has its own 10-minute limit and also runs every 15 minutes as a
best-effort fallback (GitHub schedules may be delayed). Manual cleanup dispatch
is available on main. These are separate server-side runs, not `if: always()`
steps that disappear with a cancelled runner.

Both workflows serialize access to the fixed identity. Cleanup loads code from
protected main, never PR code, triggering-run artifacts, or an artifact-provided
resource list. It checks the exact subscription/tenant, group ID/name/region/tags,
identity name/type/ID/location/ownership tags, and the identity's source run
(repository, main, workflow path, dispatch event, SHA, attempt, completed status)
before deleting only that identity by name. Any mismatch fails closed and leaves
the resource intact. Azure authorization/network failures are errors, never
interpreted as resource absence.

## Scope and limitations

Passing these exercises proves OIDC and cleanup of **this identity only**.
It does not prove Graph consent, application authentication, GPU availability,
quota, private connectivity, budget enforcement, or cleanup of billable
resources. Implement and independently test a separately scoped teardown
mechanism before provisioning actual compute or storage. The existing
`azure-deployment` application workflows remain opt-in and unchanged.

Unit guard checks (no Azure credentials):

```sh
python -m unittest discover -s scripts/tests -v
```

Never transfer local cached Azure/GitHub credentials to a cloud runner. Record
denied consent or policy as a blocker rather than disabling authentication.

## Recorded exercise: 2026-11-04 UTC

Reviewed main commit: `f52fcacffd8734de84cd4443744862982e8f9a71`
([canary implementation PR](https://github.com/ribumann/llmserving/pull/2)).

| Exercise | Canary outcome | Independent cleanup |
| --- | --- | --- |
| Deliberate failure after verified creation | [Failed as intended](https://github.com/ribumann/llmserving/actions/runs/41922899569) | [Succeeded; absence verified](https://github.com/ribumann/llmserving/actions/runs/41922982864) |
| External cancellation after verified creation | [Cancelled as intended](https://github.com/ribumann/llmserving/actions/runs/41923092659) | [Succeeded; absence verified](https://github.com/ribumann/llmserving/actions/runs/41923357529) |

An [initial attempt](https://github.com/ribumann/llmserving/actions/runs/41922340020)
failed OIDC before creation because the actual GitHub subject used immutable
owner/repository IDs rather than the configured name-only subject. The operator
corrected only the isolated login identity's exact federated subject; issuer,
audience and resource scopes were not broadened. Trust the observed environment
subject, not an assumed historical formatting template.

Both successful cleanup runs verified the fixed identity absent and preserved
the resource group. Only non-compute managed identities were created; estimated
incremental Azure compute/storage exposure for these exercises was $0. This is
not a billing reconciliation or a billable-resource cleanup test.

GitHub environment execution required no local approval. Target-tenant Graph
SSO bootstrap remains unverified after blocked interactive attempts; do not infer
their cause or retry around policy. No app, service principal or SSO secret was
created and no policy bypass was attempted.
These results therefore do **not** certify unattended authenticated application
deployment.
