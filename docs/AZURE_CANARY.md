# Protected Azure OIDC and cleanup canary

This is a safety gate, not application deployment or GPU validation. The only
created resource is one fixed user-assigned managed identity (no compute, disks,
networking, database, or role assignments). Its resource group and the federated
login identity must already exist. **Never delete the resource group.**

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
