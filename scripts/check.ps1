param(
    [ValidateSet("all", "backend", "agent", "frontend")]
    [string]$Component = "all",
    [switch]$SkipAcceptance
)

$ErrorActionPreference = "Stop"
$components = if ($Component -eq "all") { @("backend", "agent", "frontend") } else { @($Component) }

& "$PSScriptRoot/test-runtime-log-policy.ps1"
& "$PSScriptRoot/test-gradle-proxy.ps1"
& "$PSScriptRoot/test-compose-network-policy.ps1"
& "$PSScriptRoot/test-issue129-acceptance-contract.ps1"
& "$PSScriptRoot/assert-deprecated-human-auth-contract.ps1"

foreach ($current in $components) {
    docker build --target test --tag "customer-agent/${current}-test:local" $current
    if ($LASTEXITCODE -ne 0) {
        throw "$current canonical check failed"
    }
}

if (-not $SkipAcceptance -and $Component -eq "all") {
    & "$PSScriptRoot/smoke.ps1" -Reset
    & "$PSScriptRoot/issue80-acceptance.ps1"
}
