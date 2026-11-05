# Temporary private operator access (source under review)

This independent local-state module proposes **seven Terraform resources**:
GatewaySubnet, Standard static VPN public IP, VpnGw1AZ route-based gateway,
resolver subnet, private DNS resolver, inbound endpoint, and the state blob
private endpoint. The endpoint's embedded DNS zone group is an eighth ARM
object, not an eighth Terraform state address. Its generated NIC is
platform-owned. Nothing creates a second VNet, group, identity, role, storage
account, client key, VPN client installation or policy exception.

Existing main shared resources must already be deployed and verified. Only
the approved shared VNet, private-endpoint subnet and blob private DNS zone
are referenced. State storage remains public-network-disabled. The storage
target is an exact ARM ID, **not an AzureRM storage data source that could
list account keys**. Subnets use unused proposed ranges `10.20.30.0/27` and
`10.20.31.0/28`; VPN clients use `172.29.240.0/24`. Verify no overlap with
actual VNet and operator routes before planning.

## Trust and private data

The operator generates a short-lived root/client certificate pair locally.
Private keys remain local and are never Terraform inputs, Azure resources,
command-line payloads, repository files or public artifacts. Only base64 DER
**public root** certificate data and its independently verified SHA256 enter
this module. Certificate authentication is network access, not an Azure
authorization grant; existing tenant-scoped operator authentication/RBAC still
applies to Terraform and storage.

Authoritative shared/control/bootstrap state and inputs stay in the restricted
operator directories with second verified backups. Use Terraform **1.16.6**
throughout; this module pins AzureRM **3.117.1**. Initial state is local and
must remain independently recoverable outside the network it manages. No
backend migration is performed here.

The VPN client must use the resolver inbound endpoint at `10.20.31.4` for
private names, with a supported client-profile DNS configuration. Do not
assume Azure's platform address `168.63.129.16` is accessible from P2S. Do not
replace DNS with public endpoint enablement, a policy exemption or an
unreviewed hosts-file workaround. Downloading a client profile is distinct
from permission to install software, certificates or routes on the user's OS.

The separate [isolated Linux operator candidate](../../tools/private_operator/README.md)
avoids a Windows client/certificate-store installation, but requires actual
local Docker ownership/TUN verification and independent runtime-boundary
review. Its CI is not evidence that the actual operator can connect.

## Required gates before execution

This is **not executable approval**: the exact native scope guard, independent
ARM cleanup, provider-backed tests, independent review and required CI must
all pass first. Verify provider availability, live resource names/ownership,
network overlap, certificate validity and fixed cleanup deadline. Generate
the native plan privately using the actual public certificate; never publish
plan/state/inputs or provider diagnostics. Source/schema validation is not
proof that VpnGw1AZ is allocatable in Italy North, a client connects, private
DNS works, or secret/state data-plane operations succeed.

A genuine acceptance must connect the operator client, verify private
resolution and TLS of the exact state/vault FQDNs, perform separately scoped
OAuth blob/lease checks and invoke the reviewed Terraform 1.16.6 control plan
from the canonical private directory. Private blob access is not migration,
locking recovery or restore proof.

## Guarded initial local execution

After review/CI, shared29 completion and the actual native seven-create check,
arm the independent protected-main cleanup with **the same** public root
fingerprint and a fixed deadline no later than the already-armed shared
deadline. Set repository variables `OPERATOR_ACCESS_CLEANUP_ARMED=true`,
`OPERATOR_ACCESS_ROOT_SHA256=<PUBLIC-ROOT-SHA256>` and
`OPERATOR_ACCESS_EXPIRES_AT=<FIXED-UTC-DEADLINE>`, then dispatch:

```text
gh workflow run azure-operator-access-cleanup.yml --repo ribumann/llmserving \
  --ref main -f cleanup_now=false
```

Require actual successful attempt1 on protected main, no older than 30 minutes.
Before the deadline this performs ARM identity/ownership/inventory checks,
not deletion. Do not extend the existing campaign deadline automatically.
No concurrent shared cleanup or apply may run. To stop independently,
dispatch the same cleanup workflow with `cleanup_now=true`.

From the restricted canonical **operator_access** directory, use native
Terraform **1.16.6**, fresh full private saved plan and public target JSON
containing only public certificate DER/hash/expiry. A verified second backup
must be outside the canonical module and retain appropriate host ACLs:

```text
python <reviewed-source>/scripts/azure_operator_apply.py \
  --plan <PRIVATE-main-operator-access-create.tfplan> \
  --private-log <NEW-PRIVATE-operator-apply.log> \
  --target <PRIVATE-PUBLIC-ONLY-main-operator-access-target.json> \
  --second-backup <RESTRICTED-EXTERNAL-BACKUP-DIRECTORY> \
  --cleanup-run <RECENT-SUCCESSFUL-OPERATOR-CLEANUP-RUN>
```

This wrapper executes a private copied plan only after the unchanged exact
seven-create native guard, complete owned shared infrastructure, absent
operator resources, registered policy-required public-IP feature, default
workspace/local backend, matching cleanup variables/run and fixed deadline.
It additionally verifies the **copied saved plan's embedded backend**, not
only the current module metadata: only Terraform 1.16.6's exact default-local
backend encoding and default workspace are accepted. Explicit backend paths,
remote backends, state stores and unknown encodings fail before mutation.
Shared initial/reconcile execution uses the same embedded-backend gate.
The cleanup run must contain an actually successful `cleanup` job and
successful Azure login/ARM verification steps; workflow success with skipped
jobs is not arming evidence.
It preserves verified before/after checkpoints even on apply failure.
Existing local state, partial failure or lost state cannot be retried/adopted
automatically. Preserve logs/checkpoints for separate reviewed reconciliation.
The operator PIP mirrors shared lifecycle `ignore_changes=[ip_tags,zones]` so
enforced platform policy's appended IP tags are not removed by Terraform;
this is not policy exemption or public-IP tag removal.

## Cost and teardown budget

The actual 2026-11-05 ARM create rejected non-AZ `VpnGw1` with
`NonAzSkusNotAllowedForVPNGateway`; this module now requests `VpnGw1AZ`,
without changing the seven resource addresses or replacing the existing PIP.
The coordinator's official Azure Retail Prices API read on that date returned
Italy North Consumption USD `VpnGw1AZ` base **$0.21/hour** (effective
2025-01-01), P2S connection meter $0.01/hour and S2S connection meter
$0.015/hour. The base is $0.02/hour above the former VpnGw1 meter.
These are retail meter observations, not a quote, hard cap or billing
measurement; applicable connection quantities, resolver inbound endpoint,
Standard IPv4 public IP, Private Link and transfer charges are additional.
Successful allocation and compatibility with the actual retained Standard
PIP still require genuine native plan/apply acceptance. DNS resolver and VPN
provisioning can bill while idle; gateway creation can take 30–60 minutes.

For review budgeting only, reserve **US$2/hour** for this access layer and
**24 additional hours of teardown contingency** (US$56 for a four-hour
session plus contingency), excluding app/shared resources and transferred
data. This is a conservative planning allowance, **not a verified price,
hard charge cap or permission to apply**. Adjust against actual rates and
the aggregate campaign ceiling before provisioning.

Independent cleanup must remove VPN gateway before its public IP and
GatewaySubnet, inbound endpoint before resolver/subnet, and blob endpoint
before its DNS records/group/NIC are considered absent. Preserve the shared
blob zone/link and all bootstrap storage/groups/grants. Do not delete the
shared VNet until these additional children are verified absent. Disconnect
the operator VPN and remove local client configuration only with appropriate
local OS authorization.

## Exact partial operator recovery

The failed non-AZ create retained six resources in canonical serial8,
lineage `5a630028-d04a-3e1c-af96-bbd58b8434fe`, SHA256
`4496a600b605459310e5df169868204ec02894d661214b70ca421c2434054f76`.
Only the absent gateway may be created as `VpnGw1AZ`; all six existing
resources must remain exact known NOOPs. Only native null-to-empty refresh of
PIP `zones` and the two subnets' `service_endpoints`/
`service_endpoint_policy_ids`, plus their corresponding newly empty sensitivity
arrays, is allowed. Each change must bind canonical before/native prior after
values and exact drift evidence; all other values and metadata must match.
This is not a
general retry mechanism. The approved public root and `2026-11-05T21:55:55Z`
deadline cannot change. Retain the verified failed-apply checkpoints.

From the canonical restricted operator directory, generate a fresh full
native plan after updating only the gateway SKU. First run the read-only gate:

```text
python <reviewed-source>/scripts/validate_operator_reconcile.py \
  --plan <PRIVATE-RECOVERY-PLAN> --target <PUBLIC-ONLY-TARGET-JSON> \
  --private-log <NEW-PRIVATE-CHECK-LOG>
```

Only after independent review, required exact-head checks, normal merge and
fresh successful cleanup arming, run the existing `azure_operator_apply.py`
command with the additional flag `--recover-serial8`. It rechecks the exact
snapshot immediately before execution, requires the live owned six-resource
inventory with no gateway, and retains verified before/after checkpoints even
on failure. Initial execution without this flag still rejects any existing
state/resources. No automatic retry follows another failure. After successful
completion, a refreshed full Terraform plan must be NOOP before VPN acceptance.
