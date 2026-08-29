param([switch]$ConfirmProviderSpend)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited

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
$formalReportPath = Join-Path $evidenceDir 'formal.json'
$aggregateReportPath = Join-Path $evidenceDir 'report.json'
$acceptancePlan = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'issue129-acceptance-plan.psd1')
$logicalCallLimit = [int]$acceptancePlan.LogicalCallLimit
$providerAttemptLimit = [int]$acceptancePlan.ProviderAttemptLimit
$costLimitMicros = [int]$acceptancePlan.CostLimitMicros
$forbiddenEvidenceNames = @(
    'apiKey', 'prompt', 'responseBody', 'providerPayload', 'threadId',
    'ticketId', 'orderReference', 'evidenceReferences'
)
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

function Write-AggregateEvidence([switch]$Final) {
    docker compose --profile formal run --rm --volume "${evidenceDir}:/evidence" `
        --entrypoint python formal-mode-smoke -m baseline_agent.formal_mode_metrics `
        --report-path /evidence/report.json
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #129 真实模型调用聚合失败。'
    }
    $reportText = Get-Content -LiteralPath $aggregateReportPath -Raw
    $report = $reportText | ConvertFrom-Json
    if (
        $report.schemaVersion -ne 'issue-129-aggregate-provider-metrics-v1' -or
        $report.model -ne 'deepseek-v4-flash' -or
        [int]$report.totalLogicalCalls -gt $logicalCallLimit -or
        [int]$report.totalProviderAttempts -gt $providerAttemptLimit -or
        [int]$report.estimatedCostMicros -gt $costLimitMicros -or
        @($forbiddenEvidenceNames | Where-Object { $reportText -match [regex]::Escape($_) }).Count -ne 0
    ) {
        throw 'Issue #129 脱敏指标无效或真实调用硬上限已触发。'
    }
    Copy-Item -LiteralPath $aggregateReportPath -Destination $persistentEvidencePath -Force
    if ($Final -and (
        [int]$report.observedGenerationCount -lt 5 -or
        [int]$report.totalLogicalCalls -le 8 -or
        [int]$report.totalProviderAttempts -lt [int]$report.totalLogicalCalls -or
        [int]$report.customerCommunication.logicalCalls -lt 4 -or
        [int]$report.customerCommunication.providerAttempts -lt [int]$report.customerCommunication.logicalCalls -or
        [int]$report.customerCommunication.totalDurationMs -lt 1 -or
        [int]$report.estimatedCostMicros -lt 1 -or
        [int]$report.generationResults.successCount -lt 3 -or
        [int]$report.generationResults.handoffCount -lt 2 -or
        [int]$report.generationResults.handoffWithModelCallsCount -lt 2
    )) {
        throw 'Issue #129 脱敏调用、延迟或 Spring 终态证据不完整。'
    }
    return $report
}

function Invoke-BrowserScenario([string]$File, [string]$Title) {
    docker compose --profile smoke run --rm browser-acceptance `
        --max-failures=1 --grep $Title $File
    if ($LASTEXITCODE -ne 0) {
        Write-AggregateEvidence | Out-Null
        throw 'Issue #129 真实 Chromium 路径失败。'
    }
    Write-AggregateEvidence | Out-Null
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
    $env:AGENT_INVESTIGATION_MAX_COST_MICROS = '50000'
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
        [int]$agentEnvironment.AGENT_INVESTIGATION_MAX_COST_MICROS -ne 50000 -or
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
        --report-path /evidence/formal.json
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #129 真实模型业务路径失败。'
    }
    $formalReportText = Get-Content -LiteralPath $formalReportPath -Raw
    $formalReport = $formalReportText | ConvertFrom-Json
    if (
        $formalReport.schemaVersion -ne 'issue-129-formal-customer-communication-acceptance-v1' -or
        $formalReport.model -ne 'deepseek-v4-flash' -or
        $formalReport.result -ne 'PASSED' -or
        @($forbiddenEvidenceNames | Where-Object { $formalReportText -match [regex]::Escape($_) }).Count -ne 0
    ) {
        throw 'Issue #129 真实模型 smoke 脱敏证据不完整。'
    }
    Copy-Item -LiteralPath $formalReportPath -Destination $persistentEvidencePath -Force
    Write-AggregateEvidence | Out-Null

    foreach ($scenario in $acceptancePlan.Scenarios) {
        if ($scenario.Fixture) {
            Get-Content -LiteralPath $scenario.Fixture -Raw | `
                docker compose exec --no-TTY postgres psql --username postgres --dbname customer_agent
            if ($LASTEXITCODE -ne 0) {
                throw 'Issue #129 浏览器合成 fixture 导入失败。'
            }
        }
        Invoke-BrowserScenario $scenario.File $scenario.Title
    }

    $report = Write-AggregateEvidence -Final
    $report | Add-Member -NotePropertyName browserAcceptance -NotePropertyValue ([pscustomobject]@{
        testCount = $acceptancePlan.Scenarios.Count
        browser = 'Chromium'
        result = 'PASSED'
        customerSuccessScenarios = 2
        customerHandoffScenarios = 2
        approvalIsolationScenarios = 1
    })
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $aggregateReportPath -Encoding utf8
    Copy-Item -LiteralPath $aggregateReportPath -Destination $persistentEvidencePath -Force
    $evidenceVerified = $true
} catch {
    if (docker ps --quiet --filter "label=com.docker.compose.project=$projectName") {
        Write-AggregateEvidence | Out-Null
    }
    throw
} finally {
    $nativeErrorPreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    docker compose --profile smoke --profile formal down --volumes --remove-orphans 2>$null
    $ownedContainers = @(docker ps --all --quiet --filter "label=com.docker.compose.project=$projectName")
    $ownedVolumes = @(docker volume ls --quiet --filter "label=com.docker.compose.project=$projectName")
    $ownedNetworks = @(docker network ls --quiet --filter "label=com.docker.compose.project=$projectName")
    if ($ownedContainers.Count -gt 0 -or $ownedVolumes.Count -gt 0 -or $ownedNetworks.Count -gt 0) {
        throw 'Issue #129 自有容器、卷或网络清理回读不为空。'
    }
    foreach ($name in $priorEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $priorEnvironment[$name], 'Process')
    }
    if ($evidenceVerified -and (Test-Path -LiteralPath $evidenceDir)) {
        Remove-Item -LiteralPath $evidenceDir -Recurse -Force
    }
    $PSNativeCommandUseErrorActionPreference = $nativeErrorPreference
}
