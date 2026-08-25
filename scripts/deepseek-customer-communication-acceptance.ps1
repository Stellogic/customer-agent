param([switch]$ConfirmProviderSpend)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

if (-not $ConfirmProviderSpend) {
    throw '必须显式传入 -ConfirmProviderSpend 才能运行 Issue #129 正式验收。'
}
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    throw '当前验证进程缺少 DEEPSEEK_API_KEY；脚本不会读取或打印 .env。'
}
if ($env:DEEPSEEK_MODEL -ne 'deepseek-v4-flash') {
    throw 'DEEPSEEK_MODEL 必须显式设置为 deepseek-v4-flash；不会自动切换模型。'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$runId = [guid]::NewGuid().ToString('N').Substring(0, 10)
$projectName = "customer-agent-issue129-$runId"
$imageTag = "issue129-$runId"
$evidenceDir = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) $projectName))
$persistentEvidencePath = Join-Path $repoRoot 'docs\delivery\issue-129-formal-report.json'
[void](New-Item -ItemType Directory -Path $evidenceDir)
$evidenceVerified = $false
$priorEnvironment = @{}
$environmentNames = @(
    'COMPOSE_PROJECT_NAME',
    'COMPOSE_DISABLE_ENV_FILE',
    'CUSTOMER_AGENT_IMAGE_TAG',
    'CUSTOMER_AGENT_FRONTEND_PORT',
    'AGENT_INVESTIGATION_MODEL_MODE',
    'AGENT_INVESTIGATION_ACTION_MODEL_MODE',
    'AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE',
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
    $env:AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_INVESTIGATION_SHADOW_MODE = 'disabled'
    $env:AGENT_INVESTIGATION_MAX_ACTIONS = '6'
    $env:AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS = '120000'
    $env:AGENT_INVESTIGATION_MAX_TOKENS = '16000'
    $env:AGENT_INVESTIGATION_MAX_COST_MICROS = '150000'
    $env:AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS = '6'
    $env:AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS = '0'

    $effective = docker compose config --format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $effective.name -ne $projectName) {
        throw 'Issue #129 Compose project 未解析为专用 project。'
    }
    foreach ($resource in @($effective.volumes.PSObject.Properties.Value) + @($effective.networks.PSObject.Properties.Value)) {
        if ($resource.name -and -not (
            $resource.name.StartsWith("$projectName-") -or
            $resource.name.StartsWith("$projectName`_")
        )) {
            throw "Issue #129 Compose 资源不属于专用 project: $($resource.name)"
        }
    }
    if ([string]$effective.services.frontend.ports[0].published -ne $env:CUSTOMER_AGENT_FRONTEND_PORT) {
        throw 'Issue #129 Compose 前端端口未隔离。'
    }
    $agentEnvironment = $effective.services.'agent-server'.environment
    if (
        $agentEnvironment.AGENT_INVESTIGATION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.AGENT_INVESTIGATION_ACTION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.AGENT_INVESTIGATION_SHADOW_MODE -ne 'disabled' -or
        [int]$agentEnvironment.AGENT_INVESTIGATION_MAX_ACTIONS -ne 6 -or
        [int]$agentEnvironment.AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS -ne 6
    ) {
        throw 'Issue #129 三个 Flash 模型接缝或调用预算未按冻结值解析。'
    }

    docker compose --profile smoke --profile formal up --detach --build --wait backend browser-frontend
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #129 独立全栈启动失败。'
    }
    $combinedMode = (
        'deepseek-v4-flash-action-formal-v1+deepseek-v4-flash-formal-v1+' +
        'deepseek-v4-flash-customer-communication-formal-v1'
    )
    docker compose --profile formal run --rm --volume "${evidenceDir}:/evidence" `
        formal-mode-smoke --expect success --run-id $runId `
        --expected-action-model-mode $combinedMode `
        --expected-customer-communication-mode deepseek-v4-flash-customer-communication-formal-v1 `
        --report-path /evidence/report.json
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #129 真实模型业务路径失败。'
    }
    docker compose --profile smoke run --rm browser-acceptance `
        e2e/issue124.offline-fullstack-readiness.spec.ts
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #129 真实 Chromium 客户、客服与泄漏矩阵失败。'
    }

    $temporaryReportPath = Join-Path $evidenceDir 'report.json'
    $reportText = Get-Content -LiteralPath $temporaryReportPath -Raw
    $report = $reportText | ConvertFrom-Json
    $forbiddenEvidenceNames = @(
        'apiKey', 'prompt', 'responseBody', 'providerPayload', 'threadId',
        'ticketId', 'orderReference', 'evidenceReferences'
    )
    if (
        $report.schemaVersion -ne 'issue-129-formal-customer-communication-acceptance-v1' -or
        $report.model -ne 'deepseek-v4-flash' -or
        $report.result -ne 'PASSED' -or
        [int]$report.checkpointEvidence.totalLogicalCalls -ne 8 -or
        [int]$report.checkpointEvidence.totalProviderAttempts -gt 9 -or
        [int]$report.checkpointEvidence.customerCommunicationRun.logicalCalls -ne 1 -or
        [int]$report.checkpointEvidence.customerCommunicationRun.providerAttempts -gt 2 -or
        [int]$report.checkpointEvidence.customerCommunicationRun.durationMs -lt 0 -or
        -not [string]::IsNullOrEmpty(
            [string]$report.checkpointEvidence.customerCommunicationRun.failureClassification
        ) -or
        [int]$report.checkpointEvidence.estimatedCostMicros -lt 1 -or
        $report.springState.generationStatus -ne 'COMPLETED' -or
        $report.springState.submissionStatus -ne 'COMPLETED' -or
        $report.springState.handlingMode -ne 'AGENT' -or
        @($forbiddenEvidenceNames | Where-Object { $reportText -match [regex]::Escape($_) }).Count -ne 0
    ) {
        throw 'Issue #129 脱敏调用、成本、延迟或 Spring 终态证据不完整。'
    }
    $report | Add-Member -NotePropertyName browserAcceptance -NotePropertyValue ([pscustomobject]@{
        testCount = 3
        browser = 'Chromium'
        result = 'PASSED'
    })
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporaryReportPath -Encoding utf8
    Copy-Item -LiteralPath $temporaryReportPath -Destination $persistentEvidencePath -Force
    $evidenceVerified = $true
} finally {
    $nativeErrorPreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    if ($evidenceVerified) {
        docker compose --profile smoke --profile formal down --volumes --remove-orphans 2>$null
        $ownedContainers = @(docker ps --all --quiet --filter "label=com.docker.compose.project=$projectName")
        $ownedVolumes = @(docker volume ls --quiet --filter "label=com.docker.compose.project=$projectName")
        $ownedNetworks = @(docker network ls --quiet --filter "label=com.docker.compose.project=$projectName")
        if ($ownedContainers.Count -gt 0 -or $ownedVolumes.Count -gt 0 -or $ownedNetworks.Count -gt 0) {
            throw 'Issue #129 自有容器、卷或网络清理回读不为空。'
        }
    }
    foreach ($name in $priorEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $priorEnvironment[$name], 'Process')
    }
    if ($evidenceVerified -and (Test-Path -LiteralPath $evidenceDir)) {
        Remove-Item -LiteralPath $evidenceDir -Recurse -Force
    }
    $PSNativeCommandUseErrorActionPreference = $nativeErrorPreference
}
