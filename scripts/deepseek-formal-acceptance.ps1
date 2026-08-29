param(
    [switch]$ConfirmProviderSpend,
    [ValidateSet('all', 'handoff')]
    [string]$Phase = 'all'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited

if (-not $ConfirmProviderSpend) {
    throw '必须显式传入 -ConfirmProviderSpend 才能运行 Issue #127 正式 Flash 验收。'
}
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    throw '当前验证进程缺少 DEEPSEEK_API_KEY；脚本不会读取 .env 文件。'
}
if ($env:DEEPSEEK_MODEL -ne 'deepseek-v4-flash') {
    throw 'DEEPSEEK_MODEL 必须显式设置为 deepseek-v4-flash；不会自动切换模型。'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$runId = [guid]::NewGuid().ToString('N').Substring(0, 10)
$projectName = "customer-agent-issue127-$runId"
$imageTag = "issue127-$runId"
$providerKey = if ($Phase -eq 'handoff') {
    'issue127-controlled-invalid-provider-key'
} else {
    $env:DEEPSEEK_API_KEY
}
$priorEnvironment = @{}
foreach ($name in @(
    'COMPOSE_PROJECT_NAME',
    'COMPOSE_DISABLE_ENV_FILE',
    'CUSTOMER_AGENT_IMAGE_TAG',
    'CUSTOMER_AGENT_FRONTEND_PORT',
    'AGENT_INVESTIGATION_MODEL_MODE',
    'AGENT_INVESTIGATION_SHADOW_MODE',
    'DEEPSEEK_API_KEY'
)) {
    $priorEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Restart-FormalAgent([string]$ApiKey) {
    $env:DEEPSEEK_API_KEY = $ApiKey
    docker compose up --detach --force-recreate --wait agent-server backend
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #127 正式 Agent Server 重建失败。'
    }
}

function Invoke-FormalScenario([string]$Expectation) {
    docker compose --profile formal run --rm formal-mode-smoke `
        --expect $Expectation --run-id $runId
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #127 正式业务场景失败: $Expectation"
    }
}

try {
    $env:COMPOSE_PROJECT_NAME = $projectName
    $env:COMPOSE_DISABLE_ENV_FILE = 'true'
    $env:CUSTOMER_AGENT_IMAGE_TAG = $imageTag
    $portProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $portProbe.Start()
    $env:CUSTOMER_AGENT_FRONTEND_PORT = [string]$portProbe.LocalEndpoint.Port
    $portProbe.Stop()
    $env:AGENT_INVESTIGATION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_INVESTIGATION_SHADOW_MODE = 'disabled'
    $env:DEEPSEEK_API_KEY = $providerKey

    $effective = docker compose config --format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $effective.name -ne $projectName) {
        throw 'Issue #127 Compose project 未解析为专用 project。'
    }
    foreach ($resource in @($effective.volumes.PSObject.Properties.Value) + @($effective.networks.PSObject.Properties.Value)) {
        if ($resource.name -and -not (
            $resource.name.StartsWith("$projectName-") -or
            $resource.name.StartsWith("$projectName`_")
        )) {
            throw "Issue #127 Compose 资源不属于专用 project: $($resource.name)"
        }
    }
    if ([string]$effective.services.frontend.ports[0].published -ne $env:CUSTOMER_AGENT_FRONTEND_PORT) {
        throw 'Issue #127 Compose 前端端口未隔离。'
    }
    if (
        $effective.services.'agent-server'.environment.AGENT_INVESTIGATION_MODEL_MODE -ne
            'deepseek-formal' -or
        $effective.services.'agent-server'.environment.AGENT_INVESTIGATION_SHADOW_MODE -ne
            'disabled'
    ) {
        throw 'Issue #127 正式模式与 shadow 模式未被显式隔离。'
    }

    docker compose up --detach --build --wait backend
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #127 独立 Spring、LangGraph、PostgreSQL 栈启动失败。'
    }
    if ($Phase -eq 'all') {
        Invoke-FormalScenario 'success'
        Restart-FormalAgent 'issue127-controlled-invalid-provider-key'
    }
    Invoke-FormalScenario 'handoff'
} finally {
    $nativeErrorPreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    docker compose down --volumes --remove-orphans 2>$null
    foreach ($image in @(
        "customer-agent/backend:$imageTag",
        "customer-agent/agent:$imageTag",
        "customer-agent/frontend:$imageTag"
    )) {
        docker image inspect $image 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            docker image rm $image 2>$null | Out-Null
        }
    }
    foreach ($name in $priorEnvironment.Keys) {
        if ($null -eq $priorEnvironment[$name]) {
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        } else {
            [Environment]::SetEnvironmentVariable($name, $priorEnvironment[$name], 'Process')
        }
    }
    $PSNativeCommandUseErrorActionPreference = $nativeErrorPreference
}
