param(
    [switch]$ConfirmProviderSpend
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

if (-not $ConfirmProviderSpend) {
    throw '必须显式传入 -ConfirmProviderSpend 才能运行 Issue #126 真实业务 shadow。'
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
$projectName = "customer-agent-issue126-$runId"
$imageTag = "issue126-$runId"
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$evidenceDir = [IO.Path]::GetFullPath((Join-Path $temporaryRoot $projectName))
$persistentEvidencePath = Join-Path $repoRoot 'docs\delivery\issue-126-shadow-report.json'
if (-not $evidenceDir.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Issue #126 临时证据目录未落在系统临时目录内。'
}
[void](New-Item -ItemType Directory -Path $evidenceDir)

$providerKey = $env:DEEPSEEK_API_KEY
$priorEnvironment = @{}
foreach ($name in @(
    'COMPOSE_PROJECT_NAME',
    'COMPOSE_DISABLE_ENV_FILE',
    'CUSTOMER_AGENT_IMAGE_TAG',
    'CUSTOMER_AGENT_FRONTEND_PORT',
    'AGENT_INVESTIGATION_SHADOW_MODE',
    'AGENT_INVESTIGATION_SHADOW_FAULT',
    'DEEPSEEK_PRIOR_CONTRACT_ADMITTED'
)) {
    $priorEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Set-ShadowMode([string]$Mode, [string]$Fault = '') {
    $env:AGENT_INVESTIGATION_SHADOW_MODE = $Mode
    $env:AGENT_INVESTIGATION_SHADOW_FAULT = $Fault
    docker compose up --detach --force-recreate --wait agent-server
    if ($LASTEXITCODE -ne 0) {
        throw "Agent Server shadow 模式切换失败: $Mode/$Fault"
    }
}

function Invoke-ShadowPhase([string]$Phase, [string]$Fault = '') {
    $arguments = @('--phase', $Phase, '--run-id', $runId, '--evidence-dir', '/evidence')
    if ($Fault) {
        $arguments += @('--fault', $Fault)
    }
    docker compose --profile shadow run --rm --volume "${evidenceDir}:/evidence" `
        real-shadow-smoke @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #126 business shadow 阶段失败: $Phase/$Fault"
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
    $env:AGENT_INVESTIGATION_SHADOW_MODE = 'disabled'
    $env:AGENT_INVESTIGATION_SHADOW_FAULT = ''
    $env:DEEPSEEK_PRIOR_CONTRACT_ADMITTED = 'issue-125-admitted'
    Remove-Item Env:DEEPSEEK_API_KEY

    $effective = docker compose config --format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $effective.name -ne $projectName) {
        throw 'Issue #126 Compose project 未解析为专用 project。'
    }
    foreach ($resource in @($effective.volumes.PSObject.Properties.Value) + @($effective.networks.PSObject.Properties.Value)) {
        if ($resource.name -and -not (
            $resource.name.StartsWith("$projectName-") -or
            $resource.name.StartsWith("$projectName`_")
        )) {
            throw "Issue #126 Compose 资源不属于专用 project: $($resource.name)"
        }
    }
    if ([string]$effective.services.frontend.ports[0].published -ne $env:CUSTOMER_AGENT_FRONTEND_PORT) {
        throw 'Issue #126 Compose 前端端口未隔离。'
    }

    docker compose up --detach --build --wait backend
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #126 独立 Spring、LangGraph、PostgreSQL 栈启动失败。'
    }
    Invoke-ShadowPhase 'control'

    $env:DEEPSEEK_API_KEY = $providerKey
    Set-ShadowMode 'deepseek'
    Invoke-ShadowPhase 'real'
    $realEvidence = Get-Content (Join-Path $evidenceDir 'real.json') -Raw | ConvertFrom-Json
    foreach ($scenario in $realEvidence.scenarios) {
        $status = $scenario.comparison.provider_http_status
        $failure = $scenario.comparison.failure_classification
        $statusCode = 0
        $numericStatus = [int]::TryParse([string]$status, [ref]$statusCode)
        if ($status -eq '402') {
            throw 'INSUFFICIENT_BALANCE'
        }
        if ($status -in @('401', '403', '429') -or ($numericStatus -and $statusCode -ge 500)) {
            throw 'SUPPLIER_UNAVAILABLE'
        }
        if ($failure -in @('CONNECTION_TIMEOUT', 'READ_TIMEOUT', 'DEADLINE_EXCEEDED', 'TRANSIENT_PROVIDER_ERROR', 'PROVIDER_FAILED')) {
            throw 'SUPPLIER_FAILURE'
        }
    }

    Remove-Item Env:DEEPSEEK_API_KEY
    foreach ($fault in @('refusal', 'timeout', 'invalid-output')) {
        Set-ShadowMode 'offline' $fault
        Invoke-ShadowPhase 'fault' $fault
    }

    docker compose --profile shadow run --rm --volume "${evidenceDir}:/evidence" `
        real-shadow-smoke --phase aggregate --evidence-dir /evidence `
        --report-path /evidence/report.json
    if ($LASTEXITCODE -ne 0) {
        throw 'Issue #126 真实业务 shadow 未达到冻结门槛。'
    }
    $temporaryReportPath = Join-Path $evidenceDir 'report.json'
    $report = Get-Content -LiteralPath $temporaryReportPath -Raw | ConvertFrom-Json
    $classificationTotal = 0
    foreach ($classification in $report.auditEvidence.failureClassifications.PSObject.Properties) {
        $classificationTotal += [int]$classification.Value
    }
    $comparisonTotal = (
        [int]$report.comparisonEvidence.matches +
        [int]$report.comparisonEvidence.mismatches +
        [int]$report.comparisonEvidence.failed
    )
    if (
        $report.candidateModel -ne 'deepseek-v4-flash' -or
        [int]$report.attempts.actualReal -ne 3 -or
        [int]$report.attempts.retries -ne 0 -or
        [int]$report.auditEvidence.realProviderAttempts -ne 3 -or
        [int]$report.auditEvidence.retries -ne 0 -or
        $classificationTotal -ne 3 -or
        $comparisonTotal -ne 3 -or
        $report.admittedForFormalMode -ne $true -or
        $null -ne $report.blockedReason
    ) {
        throw 'Issue #126 脱敏 audit/comparison/admission 证据不完整。'
    }
    Copy-Item -LiteralPath $temporaryReportPath -Destination $persistentEvidencePath -Force
    if (
        -not (Test-Path -LiteralPath $persistentEvidencePath) -or
        (Get-FileHash -LiteralPath $temporaryReportPath).Hash -ne
            (Get-FileHash -LiteralPath $persistentEvidencePath).Hash
    ) {
        throw 'Issue #126 脱敏证据未安全持久化。'
    }
} finally {
    $nativeErrorPreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:AGENT_INVESTIGATION_SHADOW_FAULT -ErrorAction SilentlyContinue
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
    if (Test-Path -LiteralPath $evidenceDir) {
        $resolvedEvidence = [IO.Path]::GetFullPath($evidenceDir)
        if ($resolvedEvidence.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
        }
    }
    $PSNativeCommandUseErrorActionPreference = $nativeErrorPreference
}
