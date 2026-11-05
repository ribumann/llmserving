# Protected Azure OIDC and cleanup canary

This is a safety gate, not application deployment or GPU validation. The only
created resource is one fixed user-assigned managed identity (no compute, disks,
networking, database, or role assignments). Its resource group and the federated
login identity must already exist. **Never delete the resource group.**

**Target separation:** the original **Azure OIDC canary** and **Azure canary
cleanup** workflows remain manually disabled. Do not re-enable them. New
**Azure fallback OIDC canary** and **Azure fallback canary cleanup** workflows
use a distinct main-only `azure-e2e-fallback` environment and shared fallback-only
concurrency key. Their fixed helper target rejects the old subscription, tenant,
principal, group, workflow path or ownership tags. Old successful runs below
remain historical evidence for their original target only, not the fallback.
No application or GPU deployment is enabled.

## Fallback prerequisites

The operator must provision the isolated login identity/federation, exact empty
canary group, scoped Contributor permission and main-only environment first.
The helper pins the approved fallback identifiers; changing protected values
does not silently retarget it. Configure these identifiers as same-named
**environment secrets** in `azure-e2e-fallback` (they are not Azure credentials):

| Variable | Meaning |
| --- | --- |
| `AZURE_CLIENT_ID` | User-assigned login identity with environment-scoped federation |
| `AZURE_TENANT_ID` | Expected tenant |
| `AZURE_SUBSCRIPTION_ID` | Exact authorized test subscription |
| `AZURE_CANARY_RESOURCE_GROUP` | `rg-llmserving-e2e-canary` |
| `AZURE_CANARY_REGION` | `polandcentral` |

Federation must trust only the repository's exact observed
`environment:azure-e2e-fallback` subject, including immutable owner/repository
IDs where configured, with the approved issuer/audience.
The login identity requires Contributor only on that pre-existing canary group;
the workflow does not grant itself permissions. Group tags must be exactly
`project=llmserving-public-validation`, `managedBy=copilot-release` and
`target=personal-fallback-e2e`.
Secret-backed identifiers are masked from the first runner environment header,
then escaped/masked again before checkout and pinned Azure login. A no-cloud
`validate-config --target fallback` step checks the fixed target before login.
Variables alone cannot hide values printed before a masking step runs.
No long-lived Azure credential is required.

## Independent failure and cancellation exercises

After review, credential-free Cloud safety CI, and merge to main:

1. Dispatch **Azure fallback OIDC canary** on main with `outcome=failure`. It must create
   and verify the identity, then deliberately fail.
2. Verify a separate **Azure fallback canary cleanup** `workflow_run` completes
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

The fallback exercises have not yet been recorded here. Do not describe a
reviewed workflow, successful CI or historical primary exchange as new-target
OIDC/cleanup proof. The operator also reported T4-family quota zero and a
subscription SKU restriction in Poland Central; generic NC-family quota does
not establish T4 availability. No quota request, region change or GPU allocation
is authorized by this canary.

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

## Historical primary-target exercise: 2026-11-04 UTC

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
