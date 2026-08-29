param(
    [AllowEmptyString()]
    [string]$ProjectName = [Environment]::GetEnvironmentVariable('COMPOSE_PROJECT_NAME', 'Process'),
    [AllowEmptyString()]
    [string]$ImageTag = [Environment]::GetEnvironmentVariable('CUSTOMER_AGENT_IMAGE_TAG', 'Process'),
    [AllowEmptyString()]
    [string]$FrontendPort = [Environment]::GetEnvironmentVariable('CUSTOMER_AGENT_FRONTEND_PORT', 'Process')
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited

if ([string]::IsNullOrWhiteSpace($ProjectName)) {
    throw '执行 destructive Compose reset 前必须显式提供唯一的非 baseline Compose project。'
}
if ($ProjectName -match '^customer-agent-baseline(?:-|$)') {
    throw 'baseline Compose project 禁止执行 destructive reset。'
}
if (
    $ImageTag -notmatch '^gate-[a-z0-9][a-z0-9-]{7,}$' -or
    $ProjectName -cne "customer-agent-$ImageTag"
) {
    throw 'destructive reset 必须使用匹配的唯一 gate project 与镜像 tag。'
}
if ($FrontendPort -notmatch '^[0-9]+$' -or $FrontendPort -eq '4180') {
    throw 'destructive reset 必须显式提供非 baseline 前端端口。'
}

$effectiveConfigJson = docker compose -p $ProjectName config --format json
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($effectiveConfigJson)) {
    throw '无法读回 destructive gate 的有效 Compose 配置。'
}

& "$PSScriptRoot/assert-compose-reset-isolation.ps1" `
    -ProjectName $ProjectName `
    -ImageTag $ImageTag `
    -FrontendPort $FrontendPort `
    -EffectiveConfigJson $effectiveConfigJson

Write-Host 'Destructive Compose gate 隔离配置读回通过。'
