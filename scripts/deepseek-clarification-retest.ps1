param([switch]$ConfirmProviderSpend)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited

if (-not $ConfirmProviderSpend) {
    throw '必须显式传入 -ConfirmProviderSpend 才能运行 Issue #129 单路径复验。'
}
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    throw '当前验证进程缺少 DEEPSEEK_API_KEY；脚本不会读取或打印 .env。'
}
if ($env:DEEPSEEK_MODEL -ne 'deepseek-v4-flash') {
    throw 'DEEPSEEK_MODEL 必须显式设置为 deepseek-v4-flash；不会自动切换模型。'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$plan = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'issue129-clarification-retest-plan.psd1')
$runId = [guid]::NewGuid().ToString('N').Substring(0, 10)
$projectName = "customer-agent-issue129-clarification-$runId"
$imageTag = "issue129-clarification-$runId"
$evidenceDir = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) $projectName))
$temporaryReportPath = Join-Path $evidenceDir 'report.json'
$persistentReportPath = Join-Path $repoRoot 'docs\delivery\issue-129-clarification-retest-report.json'
$forbiddenEvidenceNames = @(
    'apiKey', 'prompt', 'responseBody', 'providerPayload', 'threadId',
    'ticketId', 'orderReference', 'evidenceReferences'
)
$priorEnvironment = @{}
$environmentNames = @(
    'COMPOSE_PROJECT_NAME', 'COMPOSE_DISABLE_ENV_FILE', 'CUSTOMER_AGENT_IMAGE_TAG',
    'CUSTOMER_AGENT_FRONTEND_PORT', 'AGENT_INVESTIGATION_MODEL_MODE',
    'AGENT_INVESTIGATION_ACTION_MODEL_MODE', 'AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE',
    'AGENT_INVESTIGATION_SHADOW_MODE', 'AGENT_INVESTIGATION_MAX_ACTIONS',
    'AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS', 'AGENT_INVESTIGATION_MAX_TOKENS',
    'AGENT_INVESTIGATION_MAX_COST_MICROS', 'AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS',
    'AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS', 'DEEPSEEK_API_KEY'
)
foreach ($name in $environmentNames) {
    $priorEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
[void](New-Item -ItemType Directory -Path $evidenceDir)
$evidencePersisted = $false
$evidenceVerified = $false
$stackStarted = $false
$browserExitCode = $null

function Write-ClarificationEvidence {
    docker compose --profile formal run --rm --volume "${evidenceDir}:/evidence" `
        --entrypoint python formal-mode-smoke `
        -m baseline_agent.clarification_retest_evidence --report-path /evidence/report.json
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #129 单路径脱敏证据收集失败。'
    }
    $reportText = Get-Content -LiteralPath $temporaryReportPath -Raw
    $report = $reportText | ConvertFrom-Json
    if (
        $report.schemaVersion -ne 'issue-129-clarification-retest-evidence-v1' -or
        $report.model -ne 'deepseek-v4-flash' -or
        [int]$report.metrics.totalLogicalCalls -gt [int]$plan.LogicalCallLimit -or
        [int]$report.metrics.totalProviderAttempts -gt [int]$plan.ProviderAttemptLimit -or
        [int]$report.metrics.estimatedCostMicros -gt [int]$plan.CostLimitMicros -or
        @($forbiddenEvidenceNames | Where-Object { $reportText -match [regex]::Escape($_) }).Count -ne 0 -or
        $reportText.Contains($env:DEEPSEEK_API_KEY)
    ) {
        throw 'Issue #129 单路径脱敏证据无效或真实调用硬上限已触发。'
    }
    Copy-Item -LiteralPath $temporaryReportPath -Destination $persistentReportPath -Force
    $script:evidencePersisted = $true
    return $report
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
        throw 'Issue #129 单路径 Compose project 未隔离。'
    }
    foreach ($resource in @($effective.volumes.PSObject.Properties.Value) + @($effective.networks.PSObject.Properties.Value)) {
        if ($resource.name -and -not (
            $resource.name.StartsWith("$projectName-") -or
            $resource.name.StartsWith("$projectName`_")
        )) {
            throw 'Issue #129 单路径 Compose 卷或网络未隔离。'
        }
    }
    if ([string]$effective.services.frontend.ports[0].published -ne $env:CUSTOMER_AGENT_FRONTEND_PORT) {
        throw 'Issue #129 单路径前端端口未隔离。'
    }
    foreach ($service in $effective.services.PSObject.Properties.Value) {
        if ($service.image -and $service.image.StartsWith('customer-agent/') -and -not $service.image.EndsWith(":$imageTag")) {
            throw 'Issue #129 单路径镜像 tag 未隔离。'
        }
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
        throw 'Issue #129 单路径模型或调用预算未按冻结值解析。'
    }

    docker compose --profile smoke --profile formal up --detach --build --wait backend browser-frontend
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #129 单路径独立全栈启动失败。'
    }
    $stackStarted = $true

    $nativeErrorPreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    docker compose --profile smoke run --rm browser-acceptance `
        --max-failures=1 --grep $plan.Title $plan.File *> $null
    $browserExitCode = $LASTEXITCODE
    $PSNativeCommandUseErrorActionPreference = $nativeErrorPreference

    $report = Write-ClarificationEvidence
    if ($browserExitCode -ne 0) {
        throw 'Issue #129 单路径真实 Chromium 复验失败。'
    }
    $expectedActions = @(
        'CONFIRM_ORDER', 'REQUEST_CLARIFICATION', 'CONFIRM_ORDER', 'READ_LOGISTICS',
        'READ_PAYMENT_AND_REFUNDS', 'READ_COMPENSATION_AND_PENDING_ACTIONS',
        'READ_APPLICABLE_POLICY', 'SUBMIT_CONCLUSION'
    )
    $selectedActions = @($report.actionState.selectedActions)
    $expectedFactActions = @($expectedActions[3..6] | Sort-Object)
    $selectedFactActions = @($selectedActions[3..6] | Sort-Object)
    if (
        [int]$report.metrics.observedGenerationCount -ne 1 -or
        [int]$report.metrics.totalLogicalCalls -ne 11 -or
        [int]$report.metrics.totalProviderAttempts -lt 11 -or
        [int]$report.metrics.totalProviderAttempts -gt 13 -or
        [int]$report.metrics.estimatedCostMicros -lt 1 -or
        [int]$report.metrics.generationResults.successCount -ne 1 -or
        [int]$report.metrics.generationResults.handoffCount -ne 0 -or
        @($report.metrics.failureClassifications.PSObject.Properties).Count -ne 0 -or
        [int]$report.metrics.customerCommunication.logicalCalls -ne 2 -or
        [int]$report.metrics.customerCommunication.providerAttempts -lt 2 -or
        [int]$report.metrics.customerCommunication.totalDurationMs -lt 1 -or
        -not $report.clarification.submitted -or -not $report.clarification.resumed -or
        -not $report.customerReply.generated -or
        $report.customerReply.intent -ne 'COMPENSATION_REVIEW_PENDING' -or
        $report.springState.generationStatus -ne 'COMPLETED' -or
        $report.springState.submissionStatus -ne 'COMPLETED' -or
        $report.springState.lifecycleState -ne 'INVESTIGATING' -or
        $report.springState.handlingMode -ne 'AGENT' -or
        $null -ne $report.springState.handoffReasonCode -or
        -not $report.actionState.checkpointTerminal -or
        $selectedActions.Count -ne 8 -or
        $selectedActions[0] -ne 'CONFIRM_ORDER' -or
        $selectedActions[1] -ne 'REQUEST_CLARIFICATION' -or
        $selectedActions[2] -ne 'CONFIRM_ORDER' -or
        $selectedActions[7] -ne 'SUBMIT_CONCLUSION' -or
        (Compare-Object -ReferenceObject $expectedFactActions -DifferenceObject $selectedFactActions)
    ) {
        throw 'Issue #129 单路径 action、checkpoint、客户回复或 Spring 权威终态证据不完整。'
    }
    $evidenceVerified = $true
} catch {
    if ($stackStarted -and -not $evidencePersisted) {
        Write-ClarificationEvidence | Out-Null
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
        throw 'Issue #129 单路径自有资源清理回读不为空。'
    }
    foreach ($name in $priorEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $priorEnvironment[$name], 'Process')
    }
    if ($evidenceVerified -and (Test-Path -LiteralPath $evidenceDir)) {
        Remove-Item -LiteralPath $evidenceDir -Recurse -Force
    }
    $PSNativeCommandUseErrorActionPreference = $nativeErrorPreference
}
