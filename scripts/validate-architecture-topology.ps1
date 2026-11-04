<#
.SYNOPSIS
    Scripted Azure CLI companion check for quickstart.md Scenario 8 (T145):
    validates the deployed Baseline Pilot Architecture topology - the parts of
    User Story 10's acceptance criteria that require inspecting real Azure
    resources rather than the frontend UI (which the Playwright spec
    e2e/tests/architecture-topology.spec.ts covers instead).

.DESCRIPTION
    Run this AFTER a real deployment (Phase 4: p4-deploy-shared-control /
    p4-deploy-demo-validate), against the Azure subscription/stage that was
    deployed. It never runs in CI - the user's Azure subscription requires an
    interactive `az login`, and this repo's GitHub Actions cannot reach it
    (see quickstart.md Scenario 8 preamble); it is meant to be run manually or
    from this workspace's session.

    Checks performed (quickstart.md Scenario 8, item numbers below):
      4. Exactly rg-llm-shared-{stage}, rg-llm-control-{stage}, and one
         rg-llm-demo-{environmentId} per provisioned environment exist - no
         other rg-llm* resource group, and no Application Gateway/Front
         Door/Azure Firewall/Bastion resource anywhere in the subscription
         (FR-074, FR-075, SC-018).
      5. The GPU VM's network interface has no public IP configuration
         (FR-079, SC-018).
      7. (When -BeforeTeardownGroups is supplied) confirms a teardown removed
         only rg-llm-demo-{environmentId} and left the shared/control groups
         intact (FR-080, SC-017).

    Item 6 (Hugging Face token must never appear in Postgres/Terraform
    state/Durable Functions history/logs/traces) requires querying each of
    those stores with real credentials this script cannot assume are
    available in every environment; this script only prints the
    Log Analytics KQL query an operator should run by hand (`-HfToken`).

.PARAMETER Stage
    The deployment stage suffix used when the shared/control layers were
    applied (infra/shared, infra/control - e.g. "dev", "demo").

.PARAMETER EnvironmentIds
    One or more demo environmentId values that should each have exactly one
    rg-llm-demo-{environmentId} resource group.

.PARAMETER SubscriptionId
    Azure subscription id/name to check (passed to `az account set`). Uses
    the current `az` context if omitted.

.PARAMETER BeforeTeardownGroups
    Optional: the full list of rg-llm* resource group names captured before
    a teardown ran (e.g. from a prior run of this same script), to diff
    against the current list and assert only the torn-down environment's
    group was removed (item 7).

.PARAMETER HfToken
    Optional: a Hugging Face token value used in a just-completed gated
    deployment. If supplied, this script only prints (never executes) the
    `az monitor log-analytics query` command an operator should run to
    confirm zero matches (FR-082/SC-019) - it does not send the token to
    Azure itself.

.EXAMPLE
    ./scripts/validate-architecture-topology.ps1 -Stage demo -EnvironmentIds env-abc123
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Stage,

    [Parameter(Mandatory = $true)]
    [string[]]$EnvironmentIds,

    [string]$SubscriptionId,

    [string[]]$BeforeTeardownGroups,

    [string]$HfToken
)

$ErrorActionPreference = 'Stop'
$failures = @()

function Write-Check {
    param([bool]$Passed, [string]$Message)
    if ($Passed) {
        Write-Host "[PASS] $Message" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $Message" -ForegroundColor Red
        $script:failures += $Message
    }
}

if ($SubscriptionId) {
    az account set --subscription $SubscriptionId | Out-Null
}

Write-Host "== Scenario 8 item 4: resource group topology (rg-llm-shared/-control/-demo only) =="

$expectedGroups = [System.Collections.Generic.HashSet[string]]::new()
[void]$expectedGroups.Add("rg-llm-shared-$Stage")
[void]$expectedGroups.Add("rg-llm-control-$Stage")
foreach ($environmentId in $EnvironmentIds) {
    [void]$expectedGroups.Add("rg-llm-demo-$environmentId")
}

$allGroups = az group list --query "[].name" -o tsv
$llmGroups = $allGroups | Where-Object { $_ -like 'rg-llm-*' }

$unexpected = $llmGroups | Where-Object { -not $expectedGroups.Contains($_) }
Write-Check -Passed ($unexpected.Count -eq 0) `
    -Message "No unexpected rg-llm* resource groups (found extra: $($unexpected -join ', '))"

$missing = $expectedGroups | Where-Object { $llmGroups -notcontains $_ }
Write-Check -Passed ($missing.Count -eq 0) `
    -Message "All expected resource groups present (missing: $($missing -join ', '))"

Write-Host "`n== Scenario 8 item 4: no Application Gateway/Front Door/Firewall/Bastion exists =="

$forbiddenTypes = @(
    'Microsoft.Network/applicationGateways',
    'Microsoft.Network/frontDoors',
    'Microsoft.Cdn/profiles',
    'Microsoft.Network/azureFirewalls',
    'Microsoft.Network/bastionHosts'
)
foreach ($resourceType in $forbiddenTypes) {
    $found = az resource list --resource-type $resourceType --query "[].name" -o tsv
    Write-Check -Passed (-not $found) `
        -Message "No '$resourceType' resources exist (found: $($found -join ', '))"
}

Write-Host "`n== Scenario 8 item 5: GPU VM has no public IP =="

foreach ($environmentId in $EnvironmentIds) {
    $demoGroup = "rg-llm-demo-$environmentId"
    $nics = az network nic list --resource-group $demoGroup --query "[].ipConfigurations[].publicIPAddress.id" -o tsv 2>$null
    Write-Check -Passed (-not $nics) `
        -Message "$demoGroup's GPU VM NIC(s) have no public IP configuration"
}

if ($BeforeTeardownGroups) {
    Write-Host "`n== Scenario 8 item 7: teardown removed only the torn-down demo group =="

    $currentGroups = az group list --query "[].name" -o tsv
    $removed = $BeforeTeardownGroups | Where-Object { $currentGroups -notcontains $_ }
    $unexpectedlyRemoved = $removed | Where-Object { $_ -notlike 'rg-llm-demo-*' }

    Write-Check -Passed ($unexpectedlyRemoved.Count -eq 0) `
        -Message "Only rg-llm-demo-* group(s) were removed by teardown (also removed: $($unexpectedlyRemoved -join ', '))"
    Write-Check -Passed ($currentGroups -contains "rg-llm-shared-$Stage") `
        -Message "rg-llm-shared-$Stage still exists after teardown"
    Write-Check -Passed ($currentGroups -contains "rg-llm-control-$Stage") `
        -Message "rg-llm-control-$Stage still exists after teardown"
}

if ($HfToken) {
    Write-Host "`n== Scenario 8 item 6: Hugging Face token leakage (manual follow-up) =="
    Write-Host @"
This script does not scan for the token itself (that would mean sending a
secret to Azure APIs from an automated script). Run this by hand instead
against the deployed Log Analytics workspace, and separately grep Terraform
state/plan output and PostgreSQL for the same token value - all three MUST
return zero matches (FR-082, SC-019):

  az monitor log-analytics query `
    --workspace <log-analytics-workspace-id> `
    --analytics-query "union * | where * has '<redact-token-before-running>'" `
    --timespan P7D
"@
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "All automated architecture topology checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "$($failures.Count) architecture topology check(s) failed:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
