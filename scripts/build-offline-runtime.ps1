param(
    [Parameter(Mandatory = $true)][string]$TestTag,
    [Parameter(Mandatory = $true)][string]$RuntimeTag,
    [string]$TargetTag = 'local'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

foreach ($component in @('backend', 'agent', 'frontend')) {
    docker image tag "customer-agent/$component-test:$TestTag" `
        "customer-agent/$component-test:$TargetTag"
    docker build --pull=false -f "$component/Dockerfile.offline" `
        --build-arg "TEST_IMAGE=customer-agent/$component-test:$TestTag" `
        --build-arg "RUNTIME_IMAGE=customer-agent/${component}:$RuntimeTag" `
        --tag "customer-agent/$component`:$TargetTag" .
}
