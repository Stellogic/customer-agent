param(
    [string]$Model = 'gpt-5.6-terra'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $env:OPENAI_API_KEY) {
    throw '请仅在当前终端设置 OPENAI_API_KEY；脚本不会把密钥写入仓库、Compose 或浏览器。'
}

$imageTag = if ($env:CUSTOMER_AGENT_IMAGE_TAG) { $env:CUSTOMER_AGENT_IMAGE_TAG } else { 'local' }
docker build --target runtime --tag "customer-agent/agent:$imageTag" agent
docker run --rm --entrypoint python --env OPENAI_API_KEY --env "OPENAI_MODEL=$Model" `
    "customer-agent/agent:$imageTag" -m baseline_agent.release_evaluation
