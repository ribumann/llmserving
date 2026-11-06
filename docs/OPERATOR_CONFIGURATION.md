# Private operator configuration

The public repository contains generic, bounded Azure operator tools, not an
Azure connection. **No live target, identity, state lineage, recovery hash or
release candidate is configured in source.** Local development does not need
this configuration.

Before using any cloud operator script, independently review its exact target
and supply a JSON object in `LLM_SERVING_OPERATOR_CONFIG`. Keep the actual JSON
outside the checkout and never commit or upload it. This is separate from the
active Azure login: the tools still compare the logged-in tenant, subscription,
principal, resource IDs, tags, ownership and workflow provenance against the
reviewed values. Configuration is frozen on first use in a process. Changing
it requires a new process and a new review, not an in-process target switch.

```powershell
$env:LLM_SERVING_OPERATOR_CONFIG = Get-Content -Raw 'C:\private\operator-target.json'
python scripts\azure_release_preflight.py --help
```

Required fields depend on the imported tool and its dependency chain. Every
supplied field must have a known name and valid format; missing required fields,
unknown fields, duplicate keys and malformed values fail before Azure operations.
All JSON values are strings (including run attempts and state serials).

| Fields | Independently reviewed meaning |
|---|---|
| `repository` | Exact GitHub `owner/repo`, not inferred from the current invocation |
| `subscription_id`, `tenant_id`, `deployment_client_id` | Exact Azure subscription, tenant and deployment service principal application ID |
| `sso_client_id`, `sso_object_id` | Existing operator SSO application's client and directory object IDs |
| `resource_prefix`, `resource_suffix` | Existing blueprint resource prefix and six-character naming suffix |
| `shared_group`, `control_group`, `demo_group`, `canary_group`, `primary_canary_group`, `infrastructure_group` | Exact retained group names; configuration does not create them |
| `state_account`, `registry_name` | Exact existing state storage account and image registry names |
| `region`, `canary_region` | Reviewed application and canary regions |
| `target_tag`, `campaign_tag`, `expires_on` | Exact ownership target, campaign identifier and `YYYY-MM-DD` expiry tag |
| `candidate_run`, `candidate_attempt`, `candidate_sha`, `candidate_manifest_sha256` | Successful trusted release run/attempt, full source SHA and independently verified manifest SHA-256 |
| `shared_lineage`, `shared_serial`, `shared_state_sha256` | Exact independently checkpointed shared recovery state |
| `operator_lineage`, `operator_serial`, `operator_state_sha256`, `operator_root_sha256` | Exact independently checkpointed operator recovery state and public root-certificate SHA-256 |
| `recovery_deadline` | Reviewed recovery UTC deadline, `YYYY-MM-DDTHH:MM:SSZ` |
| `dns_resource_guid`, `dns_platform_ipconfig`, `storage_topic_name` | Exact observed platform attachment identities, recognized for preservation only |

The schema is in [`scripts/operator_config.py`](../scripts/operator_config.py).
The [offline test fixture](../scripts/tests/fixtures/operator-config.json) is
deliberately fictitious; it documents the shape, **not deployment defaults**.
Never use its candidate checksums, state pins or fabricated identities for Azure.
These tools preserve the existing network and resource-layout safety policies;
supplying different IDs does not turn them into a general-purpose deployer or
cleaner, and arbitrary deployments may not match their fixed blueprint.

## GitHub Actions

Every `azure-*.yml` operator workflow is disabled unless both repository variables
are explicitly configured:

- `AZURE_OPERATOR_REPOSITORY`: the exact approved `owner/repo`.
- `ENABLE_AZURE_OPERATOR_WORKFLOWS`: exactly `true`.

Configure protected `azure-e2e` or `azure-e2e-fallback` environment **secrets**:
`LLM_SERVING_OPERATOR_CONFIG` containing the reviewed JSON and the independently
provided `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`. Canary
workflows additionally require `AZURE_CANARY_RESOURCE_GROUP` and
`AZURE_CANARY_REGION`. Restrict environments to protected `main`, require
reviewers and create narrow environment-bound OIDC trust separately. Existing
operation-specific approval and cleanup-arming gates still apply.

The private shared-state provision/cleanup pair additionally requires the
explicit `AZURE_OPERATOR_RUNNER_LABEL` variable selecting an approved private
executor. The `self-hosted`, `linux`, `x64` requirements remain fixed; no runner
host or custom label is bound by the public template.

Release packaging in Runtime CI also requires `AZURE_OPERATOR_REPOSITORY`; it
uses only that nonsecret repository field, not cloud credentials. PR checks use
synthetic fixtures and never need operator configuration or Azure access.

**Coordinate migration before merging or enabling these changes.** Existing
operators must checkpoint their canonical source/config/state and populate their
private configuration explicitly. Do not disable cleanup gates, change target
configuration, rotate credentials or remove federation while owned resources or
the current deployment still depend on them. Complete or safely hand over cleanup
under its original reviewed configuration first. This change does not revoke
live Azure/GitHub connections and does not erase identifiers from Git history.

## Terraform operator-access module

Supply `operator_target` alongside `subscription_id` and
`existing_resource_group_name`. The latter two must exactly match the independent
target's `subscription_id` and `resource_group_name`. Its remaining fields are
`resource_prefix`, `state_account`, `region`, `target_tag`, `campaign_tag`,
`expires_on`, matching the Python configuration. The native saved-plan guard
compares the complete object to its independently supplied configuration before
apply; certificate fingerprints, expiry and seven-resource scope remain mandatory.
