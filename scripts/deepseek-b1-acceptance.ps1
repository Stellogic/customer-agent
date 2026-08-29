param(
    [switch]$ConfirmProviderSpend,
    [ValidateSet('success', 'handoff')]
    [string]$Phase = 'success'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited

if (-not $ConfirmProviderSpend) {
    throw '必须显式传入 -ConfirmProviderSpend 才能运行 Issue #128 B1 正式验收。'
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
$projectName = "customer-agent-issue128-$runId"
$imageTag = "issue128-$runId"
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$evidenceDir = [IO.Path]::GetFullPath((Join-Path $temporaryRoot $projectName))
$persistentEvidencePath = Join-Path $repoRoot 'docs\delivery\issue-128-formal-report.json'
[void](New-Item -ItemType Directory -Path $evidenceDir)
$evidenceVerified = $false
$providerKey = if ($Phase -eq 'handoff') {
    'issue128-controlled-invalid-provider-key'
} else {
    $env:DEEPSEEK_API_KEY
}
$priorEnvironment = @{}
$environmentNames = @(
    'COMPOSE_PROJECT_NAME',
    'COMPOSE_DISABLE_ENV_FILE',
    'CUSTOMER_AGENT_IMAGE_TAG',
    'CUSTOMER_AGENT_FRONTEND_PORT',
    'AGENT_INVESTIGATION_MODEL_MODE',
    'AGENT_INVESTIGATION_ACTION_MODEL_MODE',
    'AGENT_INVESTIGATION_SHADOW_MODE',
    'AGENT_INVESTIGATION_MAX_ACTIONS',
    'AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS',
    'AGENT_INVESTIGATION_MAX_TOKENS',
    'AGENT_INVESTIGATION_MAX_COST_MICROS',
    'AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS',
    'AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS',
    'DEEPSEEK_API_KEY'
)
foreach ($name in $environmentNames) {
    $priorEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
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
    $env:AGENT_INVESTIGATION_ACTION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_INVESTIGATION_SHADOW_MODE = 'disabled'
    $env:AGENT_INVESTIGATION_MAX_ACTIONS = '6'
    $env:AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS = '90000'
    $env:AGENT_INVESTIGATION_MAX_TOKENS = '12000'
    $env:AGENT_INVESTIGATION_MAX_COST_MICROS = '100000'
    $env:AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS = '6'
    $env:AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS = '0'
    $env:DEEPSEEK_API_KEY = $providerKey

    $effective = docker compose config --format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $effective.name -ne $projectName) {
        throw 'Issue #128 Compose project 未解析为专用 project。'
    }
    foreach ($resource in @($effective.volumes.PSObject.Properties.Value) + @($effective.networks.PSObject.Properties.Value)) {
        if ($resource.name -and -not (
            $resource.name.StartsWith("$projectName-") -or
            $resource.name.StartsWith("$projectName`_")
        )) {
            throw "Issue #128 Compose 资源不属于专用 project: $($resource.name)"
        }
    }
    if ([string]$effective.services.frontend.ports[0].published -ne $env:CUSTOMER_AGENT_FRONTEND_PORT) {
        throw 'Issue #128 Compose 前端端口未隔离。'
    }
    $agentEnvironment = $effective.services.'agent-server'.environment
    if (
        $agentEnvironment.AGENT_INVESTIGATION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.AGENT_INVESTIGATION_ACTION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.AGENT_INVESTIGATION_SHADOW_MODE -ne 'disabled' -or
        [int]$agentEnvironment.AGENT_INVESTIGATION_MAX_ACTIONS -ne 6 -or
        [int]$agentEnvironment.AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS -ne 6 -or
        [int]$agentEnvironment.AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS -ne 0
    ) {
        throw 'Issue #128 正式模型、行动轮数或重试预算未按冻结值解析。'
    }

    docker compose up --detach --build --wait backend
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #128 独立 Spring、LangGraph、PostgreSQL 栈启动失败。'
    }
    $arguments = @('--expect', $Phase, '--run-id', $runId)
    if ($Phase -eq 'success') {
        $arguments += @(
            '--expected-action-model-mode',
            'deepseek-v4-flash-action-formal-v1+deepseek-v4-flash-formal-v1'
        )
    }
    $arguments += @('--report-path', '/evidence/report.json')
    docker compose --profile formal run --rm --volume "${evidenceDir}:/evidence" `
        formal-mode-smoke @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #128 正式自主调查场景失败: $Phase"
    }
    $temporaryReportPath = Join-Path $evidenceDir 'report.json'
    $reportText = Get-Content -LiteralPath $temporaryReportPath -Raw
    $report = $reportText | ConvertFrom-Json
    $actionOrder = @($report.checkpointEvidence.actionOrder)
    $requiredActions = @(
        'CONFIRM_ORDER',
        'READ_LOGISTICS',
        'READ_PAYMENT_AND_REFUNDS',
        'READ_COMPENSATION_AND_PENDING_ACTIONS',
        'READ_APPLICABLE_POLICY',
        'SUBMIT_CONCLUSION'
    )
    $forbiddenEvidenceNames = @(
        'apiKey', 'prompt', 'responseBody', 'providerPayload', 'threadId',
        'ticketId', 'orderReference', 'evidenceReferences'
    )
    if (
        $report.schemaVersion -ne 'issue-128-formal-autonomous-acceptance-v1' -or
        $report.model -ne 'deepseek-v4-flash' -or
        $report.result -ne 'PASSED' -or
        [int]$report.checkpointEvidence.totalLogicalCalls -gt 7 -or
        [int]$report.checkpointEvidence.totalProviderAttempts -gt 7 -or
        [int]$report.checkpointEvidence.estimatedCostMicros -lt 1 -or
        [int]$report.springState.authoritativeFactCount -ne 8 -or
        [int]$report.springState.agentCommandCount -ne 6 -or
        $report.springState.generationStatus -ne 'COMPLETED' -or
        $report.springState.submissionStatus -ne 'COMPLETED' -or
        $report.springState.handlingMode -ne 'AGENT' -or
        -not [string]::IsNullOrEmpty([string]$report.publicFailureClassification) -or
        -not [string]::IsNullOrEmpty([string]$report.publicHandoffReason) -or
        $actionOrder.Count -ne $requiredActions.Count -or
        @($requiredActions | Where-Object { $_ -notin $actionOrder }).Count -ne 0 -or
        @($forbiddenEvidenceNames | Where-Object { $reportText -match [regex]::Escape($_) }).Count -ne 0
    ) {
        throw 'Issue #128 脱敏 state/audit/checkpoint/Spring 证据不完整。'
    }
    Copy-Item -LiteralPath $temporaryReportPath -Destination $persistentEvidencePath -Force
    if (
        -not (Test-Path -LiteralPath $persistentEvidencePath) -or
        (Get-FileHash -LiteralPath $temporaryReportPath).Hash -ne
            (Get-FileHash -LiteralPath $persistentEvidencePath).Hash
    ) {
        throw 'Issue #128 脱敏验收证据未安全持久化。'
    }
    $evidenceVerified = $true
} finally {
    $nativeErrorPreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    if ($evidenceVerified) {
        docker compose down --volumes --remove-orphans 2>$null
        $ownedContainers = @(docker ps --all --quiet --filter "label=com.docker.compose.project=$projectName")
        $ownedVolumes = @(docker volume ls --quiet --filter "label=com.docker.compose.project=$projectName")
        $ownedNetworks = @(docker network ls --quiet --filter "label=com.docker.compose.project=$projectName")
        if ($ownedContainers.Count -gt 0 -or $ownedVolumes.Count -gt 0 -or $ownedNetworks.Count -gt 0) {
            throw 'Issue #128 自有容器、卷或网络清理回读不为空。'
        }
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
    }
    foreach ($name in $priorEnvironment.Keys) {
        if ($null -eq $priorEnvironment[$name]) {
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        } else {
            [Environment]::SetEnvironmentVariable($name, $priorEnvironment[$name], 'Process')
        }
    }
    if ($evidenceVerified -and (Test-Path -LiteralPath $evidenceDir)) {
        Remove-Item -LiteralPath $evidenceDir -Recurse -Force
    }
    $PSNativeCommandUseErrorActionPreference = $nativeErrorPreference
}
