# Temporary private operator access (source under review)

This independent local-state module proposes **seven Terraform resources**:
GatewaySubnet, Standard static VPN public IP, VpnGw1 route-based gateway,
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

## Required gates before execution

This is **not executable approval**: the exact native scope guard, independent
ARM cleanup, provider-backed tests, independent review and required CI must
all pass first. Verify provider availability, live resource names/ownership,
network overlap, certificate validity and fixed cleanup deadline. Generate
the native plan privately using the actual public certificate; never publish
plan/state/inputs or provider diagnostics. Source/schema validation is not
proof that VpnGw1 is allocatable in Italy North, a client connects, private
DNS works, or secret/state data-plane operations succeed.

A genuine acceptance must connect the operator client, verify private
resolution and TLS of the exact state/vault FQDNs, perform separately scoped
OAuth blob/lease checks and invoke the reviewed Terraform 1.16.6 control plan
from the canonical private directory. Private blob access is not migration,
locking recovery or restore proof.

## Cost and teardown budget

**Live retail pricing could not be retrieved from this execution host**
(`prices.azure.com` DNS resolution failed). Do not label an estimate a quote
or fresh billing measurement. Before apply, retrieve actual Italy North
Consumption USD rates for VpnGw1, Private DNS Resolver inbound endpoint,
Standard IPv4 public IP and Private Link endpoint/data processing, plus
applicable data transfer. DNS resolver and VPN provisioning can bill while
idle; Microsoft/provider documentation warns gateway creation can take
30–60 minutes.

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
