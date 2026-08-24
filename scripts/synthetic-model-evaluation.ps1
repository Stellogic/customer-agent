param(
    [ValidateSet('offline')]
    [string]$Mode = 'offline'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ($Mode -ne 'offline') {
    throw 'Issue #115 只提供离线评测；真实 DeepSeek 评测必须由后续显式授权票据接入。'
}

$imageTag = if ($env:CUSTOMER_AGENT_IMAGE_TAG) { $env:CUSTOMER_AGENT_IMAGE_TAG } else { 'local' }
docker build --target runtime --tag "customer-agent/agent:$imageTag" agent
docker run --rm --entrypoint python "customer-agent/agent:$imageTag" `
    -m baseline_agent.synthetic_evaluation
