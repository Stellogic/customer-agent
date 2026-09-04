param(
    [switch]$ConfirmProviderSpend,
    [switch]$IntakeDiagnostic,
    [switch]$InvestigationDiagnostic,
    [string]$EnvFile = 'D:\customer-agent\.env',
    [string]$LedgerPath = 'D:\customer-agent\.local\issue190-sufficiency\cost-ledger.json',
    [string]$KnowledgeModelPath = 'C:\Users\lizhuo\.codex\worktrees\745a\customer-agent\.local\models\bge-small-zh-v1.5',
    [string]$RunId = "issue174-live-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
. "$PSScriptRoot/gate-images.ps1"
. "$PSScriptRoot/gate-resources.ps1"

$projectLimitMicroCny = 8000000
$expectedPriorMicroCny = 3810222
$runReservationMicroCny = if ($IntakeDiagnostic) { 100000 } else { 1000000 }
$logicalCallLimit = 100
$providerAttemptLimit = 100
$knownTokenLimit = 200000
$intakeCallUpperMicroCny = 20000

if (-not $ConfirmProviderSpend) { throw '必须显式传入 -ConfirmProviderSpend。' }
if ($IntakeDiagnostic -and $InvestigationDiagnostic) { throw '只能选择一种诊断模式。' }
if (-not $IntakeDiagnostic -and -not $InvestigationDiagnostic) {
    $executionCatalog = Get-Content (Join-Path $PSScriptRoot '../docs/implementation/issue-174-live-scenarios.json') -Raw | ConvertFrom-Json
    if ($executionCatalog.executionAuthorized -ne $true -or $executionCatalog.status -ne 'FROZEN_AUTHORIZED_NOT_RUN') {
        throw '发布配置尚未冻结授权；禁止读取密钥、预留费用或调用供应商。'
    }
}
if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') { throw 'RunId 格式无效。' }
foreach ($path in @($EnvFile, $LedgerPath, $KnowledgeModelPath)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "所需输入不存在: $path" }
}
if (@(git status --porcelain).Count -ne 0) { throw '真实验收前工作树必须干净。' }

$keyLines = @(Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^\s*DEEPSEEK_API_KEY\s*=' })
if ($keyLines.Count -ne 1) { throw '授权 EnvFile 必须恰好包含一个 DEEPSEEK_API_KEY。' }
$providerKey = ($keyLines[0] -replace '^\s*DEEPSEEK_API_KEY\s*=\s*', '').Trim()
if ([string]::IsNullOrWhiteSpace($providerKey)) { throw 'DEEPSEEK_API_KEY 为空。' }

function Read-SharedLedger {
    $value = Get-Content -LiteralPath $LedgerPath -Raw | ConvertFrom-Json
    if ($value.schema -ne 'issue190-sufficiency-cost-v1') { throw '共享账本 schema 不符。' }
    return $value
}

function Get-SettledMicroCny($Ledger) {
    return [long]$Ledger.prior_paid_micro_cny + [long](
        @($Ledger.attempts | Where-Object status -eq 'SETTLED' | Measure-Object charged_upper_micro_cny -Sum)[0].Sum
    )
}

$ledger = Read-SharedLedger
$settledBefore = Get-SettledMicroCny $ledger
$pending = @($ledger.attempts | Where-Object status -eq 'PENDING')
$expectedPendingCount = if ($IntakeDiagnostic) { 5 } else { 11 }
if ($IntakeDiagnostic -and ($RunId -ne 'issue174-intake-diagnostic-04' -or $pending.Count -ne 5 -or
    @($pending | Where-Object { $_.phase -eq 'issue174-live-20260903a' -and $_.reserved_micro_cny -eq 1000000 }).Count -ne 1 -or
    @($pending | Where-Object { $_.phase -eq 'issue174-intake-diagnostic-01' -and $_.reserved_micro_cny -eq 100000 }).Count -ne 1 -or
    @($pending | Where-Object { $_.phase -eq 'issue174-intake-diagnostic-02' -and $_.reserved_micro_cny -eq 100000 }).Count -ne 1 -or
    @($pending | Where-Object { $_.phase -eq 'issue174-intake-diagnostic-03' -and $_.reserved_micro_cny -eq 100000 }).Count -ne 1 -or
    @($pending | Where-Object { $_.phase -eq 'issue174-live-02' -and $_.reserved_micro_cny -eq 1000000 }).Count -ne 1)) {
    throw '第四阶段诊断须保留已知的五笔 PENDING，且只能使用冻结的新运行标识。'
}
if (-not $IntakeDiagnostic) {
    $expectedRunId = if ($InvestigationDiagnostic) { 'issue174-investigation-diagnostic-01' } else { 'issue174-live-04' }
    if ($RunId -ne $expectedRunId -or $pending.Count -ne 11) { throw '须使用冻结运行标识并保留十一笔 PENDING。' }
    foreach ($prior in @('issue174-live-20260903a', 'issue174-live-02', 'issue174-live-03', 'issue174-intake-diagnostic-01', 'issue174-intake-diagnostic-02', 'issue174-intake-diagnostic-03', 'issue174-intake-diagnostic-04', 'issue215-intake-diagnostic-01', 'issue215-intake-diagnostic-02', 'issue215-intake-diagnostic-03', 'issue215-intake-diagnostic-04')) {
        $amount = if ($prior -in @('issue174-live-20260903a', 'issue174-live-02', 'issue174-live-03')) { 1000000 } else { 100000 }
        if (@($pending | Where-Object { $_.phase -eq $prior -and $_.reserved_micro_cny -eq $amount }).Count -ne 1) {
            throw '发布复验账本预留身份或金额不符。'
        }
    }
}
if ($settledBefore -ne $expectedPriorMicroCny -or $pending.Count -ne $expectedPendingCount) {
    throw "共享账本未处于冻结起点: settled=$settledBefore pending=$($pending.Count)"
}
$pendingBeforeMicroCny = [long](($pending | Measure-Object reserved_micro_cny -Sum).Sum)
$budgetBasisBeforeMicroCny = $settledBefore + $pendingBeforeMicroCny
if (-not $IntakeDiagnostic) {
    $billing = Get-Content (Join-Path $PSScriptRoot '../docs/delivery/issue-174-billing-reconciliation.json') -Raw | ConvertFrom-Json
    if ($billing.source -ne 'USER_REPORTED_PROVIDER_TOTAL' -or
        $billing.legacyEstimatedUpperMicroCny -ne $settledBefore -or
        $billing.legacyPendingReservedMicroCny -ne $pendingBeforeMicroCny -or
        @(Compare-Object @($billing.coveredPendingPhases) @($pending.phase)).Count -ne 0) {
        throw '费用核对点与历史账本不符，禁止遗漏新消费。'
    }
    $budgetBasisBeforeMicroCny = [long]$billing.historicalPaidUpperMicroCny
    if ($runReservationMicroCny -gt [long]$billing.userReportedAvailableMicroCny) {
        throw '本轮预留超过用户确认的当前可用额度。'
    }
}
if ($budgetBasisBeforeMicroCny + $runReservationMicroCny -gt $projectLimitMicroCny) {
    throw '共享预算不足以预留本次运行上限。'
}
if ($ledger.phases.PSObject.Properties.Name -contains $RunId) { throw 'RunId 已存在，禁止覆盖。' }

$repoRoot = Split-Path -Parent $PSScriptRoot
$head = (git rev-parse HEAD).Trim()
$base = (git rev-parse origin/main).Trim()
$projectName = "customer-agent-$RunId"
$imageTag = "gate-$RunId"
$evidenceDir = Join-Path $repoRoot ".local/gate-evidence/$RunId"
$reportPath = Join-Path $repoRoot $(if ($InvestigationDiagnostic) { 'docs/delivery/issue-174-investigation-diagnostic-01-report.json' } else { 'docs/delivery/issue-174-live-report-04.json' })
$formalPath = Join-Path $evidenceDir 'formal-metrics.json'
$overridePath = Join-Path ([IO.Path]::GetTempPath()) "$RunId.override.yaml"
$catalogPath = Join-Path $repoRoot 'docs/implementation/issue-174-live-scenarios.json'
$gate = $null
$completed = $false
$artifactsAvailable = $false
$imagesBuilt = $false
$providerMayHaveRun = $false
$reservationWritten = $false
$scenarioCount = 0
$scenarioDurations = [ordered]@{}
$cleanupFailures = @()
$runFailure = $null
$priorEnvironment = @{}
$environmentNames = @(
    'COMPOSE_PROJECT_NAME', 'COMPOSE_DISABLE_ENV_FILE', 'CUSTOMER_AGENT_IMAGE_TAG',
    'CUSTOMER_AGENT_FRONTEND_PORT', 'KNOWLEDGE_MODEL_HOST_PATH', 'DEEPSEEK_API_KEY',
    'DEEPSEEK_MODEL', 'INVESTIGATION_MODEL_MODE', 'AGENT_INVESTIGATION_MODEL_MODE',
    'AGENT_INVESTIGATION_ACTION_MODEL_MODE', 'AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE',
    'AGENT_INVESTIGATION_SHADOW_MODE', 'AGENT_INVESTIGATION_MAX_ACTIONS',
    'AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS', 'AGENT_INVESTIGATION_MAX_TOKENS',
    'AGENT_INVESTIGATION_MAX_COST_MICROS', 'AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS',
    'AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS'
)
foreach ($name in $environmentNames) {
    $priorEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Invoke-Compose([object[]]$Arguments) {
    & docker compose -f (Join-Path $repoRoot 'compose.yaml') -f $overridePath --project-name $projectName @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose 失败: $($Arguments -join ' ')" }
}

function Assert-FrozenCatalog {
    $catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
    $reservations = $catalog.liveFreeze.limitsByScenario.scenarioReservationsMicroCny
    if (
        $catalog.status -ne 'FROZEN_AUTHORIZED_NOT_RUN' -or
        $catalog.executionAuthorized -ne $true -or
        $catalog.revision -ne 4 -or
        $catalog.liveFreeze.promptVersionsBySeam.intake -ne 'intake-v3' -or
        $catalog.liveFreeze.model -ne 'deepseek-v4-flash' -or
        [int]$catalog.liveFreeze.logicalCallLimit -ne $logicalCallLimit -or
        [int]$catalog.liveFreeze.providerAttemptLimit -ne $providerAttemptLimit -or
        [int]$catalog.liveFreeze.tokenLimit -ne $knownTokenLimit -or
        @($catalog.scenarios).Count -ne 5 -or
        @($catalog.scenarios | Where-Object { $_.status -ne 'FROZEN_NOT_RUN' -or @($_.pending).Count -ne 0 }).Count -ne 0 -or
        [long](($reservations.PSObject.Properties.Value | Measure-Object -Sum).Sum) -ne $runReservationMicroCny -or
        [long]$reservations.'L174-01' -ne 220000 -or [long]$reservations.'L174-02' -ne 120000 -or
        [long]$reservations.'L174-03' -ne 260000 -or [long]$reservations.'L174-04' -ne 280000 -or
        [long]$reservations.'L174-05' -ne 120000
    ) { throw '调用前场景清单与 runner 冻结值不一致。' }
}

function Invoke-LiveScenario([string]$File, [string]$Title) {
    Invoke-Compose @('--profile', 'smoke', 'run', '--rm', '--no-deps', 'browser-acceptance',
        '--workers=1', '--max-failures=1', '--trace', 'off', '--grep', $Title, $File)
}

function Wait-NoActiveGenerations {
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        $result = Invoke-Compose @('exec', '--no-TTY', 'postgres', 'psql', '--username', 'postgres',
            '--dbname', 'customer_agent', '--tuples-only', '--no-align', '--command',
            "select count(*) from agent_processing_generation where status='ACTIVE';")
        $active = [int](($result | Where-Object { $_ -match '^\s*\d+\s*$' } | Select-Object -Last 1).Trim())
        if ($active -eq 0) { return }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw '等待真实生成终态超时。'
}

function Export-BrowserAcceptanceArtifacts {
    $volume = "${projectName}_browser-artifacts"
    $container = "${projectName}-artifact-export"
    $destination = Join-Path $evidenceDir 'browser'
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    docker create --name $container --volume "${volume}:/artifacts" "customer-agent/frontend-browser-test:$imageTag" sh -c true | Out-Null
    try {
        docker cp "${container}:/artifacts/." $destination
        if ($LASTEXITCODE -ne 0) { throw '浏览器证据导出失败。' }
    } finally {
        docker rm --force $container | Out-Null
    }
}

function Get-LiveUsage {
    Invoke-Compose @('--profile', 'formal', 'run', '--rm', '--volume', "${evidenceDir}:/evidence",
        '--entrypoint', 'python', 'formal-mode-smoke', '-m', 'baseline_agent.formal_mode_metrics',
        '--report-path', '/evidence/formal-metrics.json') | Out-Host
    $formal = Get-Content -LiteralPath $formalPath -Raw | ConvertFrom-Json
    $database = Invoke-Compose @('exec', '--no-TTY', 'postgres', 'psql', '--username', 'postgres',
        '--dbname', 'customer_agent', '--tuples-only', '--no-align', '--command',
        "select json_build_object('intakeCalls',(select count(*) from customer_intake)+(select count(*) from customer_intake_message),'generationCount',(select count(*) from agent_processing_generation where thread_id is not null),'activeGenerations',(select count(*) from agent_processing_generation where status='ACTIVE'),'supportCalls',(select count(*) from support_assistance_request),'supportAttempts',(select sum((model_audit->>'attempts')::int) from support_assistance_request),'supportInputTokens',(select sum((model_audit->>'input_tokens')::int) from support_assistance_request),'supportOutputTokens',(select sum((model_audit->>'output_tokens')::int) from support_assistance_request),'supportUnknownUsage',(select count(*) from support_assistance_request where model_audit is null or model_audit->>'attempts' is null or ((model_audit->>'attempts')::int>0 and (model_audit->>'input_tokens' is null or model_audit->>'output_tokens' is null))),'supportWrongProtocol',(select count(*) from support_assistance_request where model_audit->>'model'<>'deepseek-v4-flash' or model_audit->>'protocol'<>'support-assistance-answer-v2'),'maxGenerationMs',(select coalesce(max(extract(epoch from (completed_at-created_at))*1000)::bigint,0) from agent_processing_generation where completed_at is not null),'maxFirstDeltaMs',(select coalesce(max(extract(epoch from (e.first_at-g.created_at))*1000)::bigint,0) from agent_processing_generation g join lateral (select min(occurred_at) first_at from customer_public_event where ticket_id=g.ticket_id and agent_generation=g.generation_number and event_type='AGENT_REPLY_CONTENT_DELTA') e on e.first_at is not null));")
    $databaseMetrics = ($database | Where-Object { $_ -match '^\{' } | Select-Object -Last 1) | ConvertFrom-Json
    $logicalCalls = [int]$formal.totalLogicalCalls + [int]$databaseMetrics.intakeCalls + [int]$databaseMetrics.supportCalls
    $supportAttempts = if ($null -eq $databaseMetrics.supportAttempts) { 0 } else { [int]$databaseMetrics.supportAttempts }
    $supportInputTokens = if ($null -eq $databaseMetrics.supportInputTokens) { 0 } else { [int]$databaseMetrics.supportInputTokens }
    $supportOutputTokens = if ($null -eq $databaseMetrics.supportOutputTokens) { 0 } else { [int]$databaseMetrics.supportOutputTokens }
    $providerAttempts = [int]$formal.totalProviderAttempts + [int]$databaseMetrics.intakeCalls + $supportAttempts
    $knownTokens = [int]$formal.totalTokens + $supportInputTokens + $supportOutputTokens
    $chargedMicroCny = [long]$formal.estimatedCostMicros * 7 +
        [long]$supportInputTokens * 3 +
        [long]$supportOutputTokens * 9 +
        [long]$databaseMetrics.intakeCalls * $intakeCallUpperMicroCny
    [pscustomobject]@{
        Formal = $formal
        Database = $databaseMetrics
        LogicalCalls = $logicalCalls
        ProviderAttempts = $providerAttempts
        KnownTokens = $knownTokens
        ChargedMicroCny = $chargedMicroCny
        UsageTrusted = $formal.usageTrusted -eq $true -and [int]$databaseMetrics.supportUnknownUsage -eq 0
    }
}

function Assert-LiveUsage($Usage, [switch]$RequireAllSeams) {
    if (-not $Usage.UsageTrusted) { throw '存在供应商尝试但 usage 未确认，保留预算预留并停止。' }
    if ($Usage.LogicalCalls -gt $logicalCallLimit -or $Usage.ProviderAttempts -gt $providerAttemptLimit) {
        throw '真实调用次数超过冻结上限。'
    }
    if ($Usage.KnownTokens -gt $knownTokenLimit) { throw '已持久化 token 数超过冻结上限。' }
    if ($Usage.ChargedMicroCny -gt $runReservationMicroCny) { throw '真实费用上界超过本次预留。' }
    if ($RequireAllSeams) {
        $failureCount = @($Usage.Formal.failureClassifications.PSObject.Properties).Count
        if (
            [int]$Usage.Database.activeGenerations -ne 0 -or
            [int]$Usage.Formal.observedGenerationCount -ne [int]$Usage.Database.generationCount -or
            [int]$Usage.Database.intakeCalls -le 0 -or
            [int]$Usage.Formal.action.logicalCalls -le 0 -or
            [int]$Usage.Formal.action.providerAttempts -le 0 -or
            [int]$Usage.Formal.judgment.logicalCalls -le 0 -or
            [int]$Usage.Formal.judgment.providerAttempts -le 0 -or
            [int]$Usage.Formal.customerCommunication.logicalCalls -le 0 -or
            [int]$Usage.Formal.customerCommunication.providerAttempts -le 0 -or
            $Usage.Formal.action.promptVersion -ne 'investigation-action-v3' -or
            $Usage.Formal.action.schemaVersion -ne 'investigation-action-v3' -or
            $Usage.Formal.judgment.promptVersion -ne 'investigation-judgment-v1' -or
            $Usage.Formal.judgment.schemaVersion -ne 'investigation-judgment-v1' -or
            [int]$Usage.Database.supportAttempts -le 0 -or
            [int]$Usage.Database.supportWrongProtocol -ne 0 -or
            $failureCount -ne 0
        ) { throw '全部生成接缝的真实模型、终态、协议或失败分类证据不闭合。' }
    }
}

function Settle-SharedLedger($Usage, [string]$Status) {
    if (-not $Usage.UsageTrusted) { throw 'usage 未确认，禁止结算共享账本。' }
    $current = Read-SharedLedger
    $entry = @($current.attempts | Where-Object phase -eq $RunId)
    if ($entry.Count -ne 1 -or $entry[0].status -ne 'PENDING') { throw '共享账本预留身份不唯一。' }
    $entry[0].status = 'SETTLED'
    $entry[0] | Add-Member -NotePropertyName charged_upper_micro_cny -NotePropertyValue $Usage.ChargedMicroCny -Force
    $current.phases.$RunId.status = $Status
    $current | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $LedgerPath -Encoding utf8
}

try {
    if (-not $IntakeDiagnostic -and -not $InvestigationDiagnostic) { Assert-FrozenCatalog }
    $gate = Enter-TestGateLock -Issue 174 -RunId $RunId -CommandType 'deepseek-live' `
        -BaseSha $base -HeadSha $head -ComposeProject $projectName -ImageTag $imageTag
    $ledger = Read-SharedLedger
    $pendingNow = @($ledger.attempts | Where-Object status -eq 'PENDING')
    if (@($pending | Where-Object { $priorEntry = $_; @($pendingNow | Where-Object { $_.phase -eq $priorEntry.phase -and $_.reserved_micro_cny -eq $priorEntry.reserved_micro_cny }).Count -ne 1 }).Count -ne 0) {
        throw '获得门禁锁后既有预留记录发生变化。'
    }
    if ((Get-SettledMicroCny $ledger) -ne $settledBefore -or $pendingNow.Count -ne $expectedPendingCount -or
        [long](($pendingNow | Measure-Object reserved_micro_cny -Sum).Sum) -ne $pendingBeforeMicroCny -or
        ($IntakeDiagnostic -and (@($pendingNow | Where-Object phase -eq 'issue174-live-20260903a').Count -ne 1 -or
            @($pendingNow | Where-Object phase -eq 'issue174-intake-diagnostic-01').Count -ne 1 -or
            @($pendingNow | Where-Object phase -eq 'issue174-intake-diagnostic-02').Count -ne 1))) {
        throw '获得门禁锁后共享账本起点发生变化。'
    }
    $ledger.phases | Add-Member -NotePropertyName $RunId -NotePropertyValue ([pscustomobject]@{
        status = 'RUNNING'
        dataset = $(if ($InvestigationDiagnostic) { 'issue174-investigation-diagnostic-v1' } elseif ($IntakeDiagnostic) { 'issue174-intake-diagnostic-v1' } else { 'issue-174-live-scenarios-v1' })
    })
    $ledger.attempts += [pscustomobject]@{
        phase = $RunId
        query_id = $(if ($InvestigationDiagnostic) { 'issue174-browser-investigation-diagnostic' } else { 'issue174-browser-release' })
        status = 'PENDING'
        reserved_micro_cny = $runReservationMicroCny
    }
    $ledger | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $LedgerPath -Encoding utf8
    $reservationWritten = $true
    New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
    @"
services:
  agent-server:
    environment:
      INVESTIGATION_MODEL_MODE: deepseek-formal
"@ | Set-Content -LiteralPath $overridePath -Encoding utf8
    if ($InvestigationDiagnostic) {
        # 仅运行时诊断副本：保留每条校验与异常，只打印受控分类及原文件行号。
        $diagnosticSourcePath = Join-Path $evidenceDir 'deepseek_investigation_action_model.py'
        $diagnosticSource = Get-Content (Join-Path $repoRoot 'agent/src/baseline_agent/deepseek_investigation_action_model.py') -Raw
        if (-not $diagnosticSource.Contains('raise _DeepSeekActionResponseFailure(')) { throw '未找到冻结解析诊断位置。' }
        $diagnosticSource = $diagnosticSource.Replace('raise _DeepSeekActionResponseFailure(', 'raise _diagnostic_response_failure(')
        $diagnosticSource += @'


def _diagnostic_response_failure(classification):
    import sys
    print("ISSUE174_PARSE_FAILURE line=" + str(sys._getframe(1).f_lineno) + " class=" + classification.value, flush=True)
    return _DeepSeekActionResponseFailure(classification)
'@
        [IO.File]::WriteAllText($diagnosticSourcePath, $diagnosticSource)
        @"
    volumes:
      - type: bind
        source: $($diagnosticSourcePath.Replace('\', '/'))
        target: /app/src/baseline_agent/deepseek_investigation_action_model.py
        read_only: true
"@ | Add-Content -LiteralPath $overridePath -Encoding utf8
    }

    $env:COMPOSE_PROJECT_NAME = $projectName
    $env:COMPOSE_DISABLE_ENV_FILE = 'true'
    $env:CUSTOMER_AGENT_IMAGE_TAG = $imageTag
    $port = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $port.Start()
    $env:CUSTOMER_AGENT_FRONTEND_PORT = [string]$port.LocalEndpoint.Port
    $port.Stop()
    $env:KNOWLEDGE_MODEL_HOST_PATH = $KnowledgeModelPath
    $env:DEEPSEEK_API_KEY = $providerKey
    $env:DEEPSEEK_MODEL = 'deepseek-v4-flash'
    $env:INVESTIGATION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_INVESTIGATION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_INVESTIGATION_ACTION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_INVESTIGATION_SHADOW_MODE = 'disabled'
    $env:AGENT_INVESTIGATION_MAX_ACTIONS = '8'
    $env:AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS = '120000'
    $env:AGENT_INVESTIGATION_MAX_TOKENS = '16000'
    $env:AGENT_INVESTIGATION_MAX_COST_MICROS = '10000'
    $env:AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS = '8'
    $env:AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS = '0'

    $sourceFingerprint = Get-GateSourceFingerprint -RepoRoot $repoRoot
    $imagesBuilt = $true
    Invoke-GateImageBuilds -RepoRoot $repoRoot -RunId $RunId -SourceFingerprint $sourceFingerprint | Out-Null
    Invoke-Compose @('up', '--detach', '--no-build', '--force-recreate', '--wait')
    Invoke-Compose @('--profile', 'smoke', 'up', '--detach', '--no-build', '--no-deps', '--wait', 'browser-frontend')
    $artifactsAvailable = $true

    if ($IntakeDiagnostic) {
        Invoke-Compose @('--profile', 'smoke', 'run', '--rm', '--no-deps', 'browser-acceptance',
            '--list', 'e2e/issue174.intake-diagnostic.spec.ts')
    }
    $providerMayHaveRun = $true
    if ($IntakeDiagnostic) {
        try {
        Invoke-Compose @('--profile', 'smoke', 'run', '--rm', '--no-deps',
            '--volume', "${evidenceDir}:/diagnostics", 'browser-acceptance',
            '--workers=1', '--max-failures=1', '--trace', 'off', 'e2e/issue174.intake-diagnostic.spec.ts')
        } finally {
            # 不保存原始日志；仅在内存中匹配固定异常名和固定消息。
            $rawLog = (Invoke-Compose @('logs', '--no-color', 'agent-server') 2>&1 | Out-String)
            $classes = [ordered]@{}
            foreach ($kind in @('HTTPStatusError', 'JSONDecodeError', 'KeyError', 'ValueError', 'ReadTimeout', 'ConnectError')) {
                $classes[$kind] = [regex]::Matches($rawLog, "\b$kind\b").Count
            }
            $known = [ordered]@{}
            foreach ($message in @('incomplete provider response', 'invalid provider response', 'invalid provider output', 'model selected a non-visible order')) {
                $known[$message] = $rawLog.Contains($message)
            }
            $httpCodes = @([regex]::Matches($rawLog, "(?:Client|Server) error '([0-9]{3})") | ForEach-Object { [int]$_.Groups[1].Value } | Sort-Object -Unique)
            $rawLog = $null
            $dbSummary = Invoke-Compose @('exec', '--no-TTY', 'postgres', 'psql', '--username', 'postgres',
                '--dbname', 'customer_agent', '--tuples-only', '--no-align', '--command',
                "select json_build_object('agentUnavailableAssistance',(select count(*) from intake_assistance_request where reason_code='AGENT_UNAVAILABLE'),'intakes',(select count(*) from customer_intake),'messages',(select count(*) from customer_intake_message),'visibleOrderCount',(select count(*) from synthetic_order where customer_id='customer-demo'),'candidatePresent',(select bool_or(candidate_order_reference is not null) from customer_intake),'pendingKinds',(select json_agg(case when issue_kind in ('DUPLICATE_CHARGE','PACKAGE_NOT_RECEIVED','LOGISTICS_DELAY') then issue_kind else 'OTHER' end order by ordinal) from customer_intake_pending_issue));")
            [ordered]@{ exceptionNameOccurrences = $classes; knownFailureMessages = $known; providerHttpCodes = $httpCodes;
                database = (($dbSummary | Where-Object { $_ -match '^\{' } | Select-Object -Last 1) | ConvertFrom-Json)
            } | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $evidenceDir 'intake-error-classification.json') -Encoding utf8
        }
        $current = Read-SharedLedger
        $current.phases.$RunId.status = 'DIAGNOSTIC_COMPLETED_PENDING_USAGE'
        $current | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $LedgerPath -Encoding utf8
    } elseif ($InvestigationDiagnostic) {
        try {
            Invoke-LiveScenario 'e2e/issue173.full-stack.spec.ts' 'Issue #173 A：'
        } finally {
            $diagnosticWaitFailure = $null
            try { Wait-NoActiveGenerations } catch { $diagnosticWaitFailure = 'GENERATION_WAIT_TIMEOUT_OR_QUERY_FAILURE' }
            $diagnosticLog = (Invoke-Compose @('logs', '--no-color', 'agent-server') 2>&1 | Out-String)
            $parseFailures = @([regex]::Matches($diagnosticLog, 'ISSUE174_PARSE_FAILURE line=(\d+) class=([A-Z_]+)') | ForEach-Object {
                [ordered]@{ sourceLine = [int]$_.Groups[1].Value; classification = $_.Groups[2].Value }
            })
            $diagnosticLog = $null
            $diagnosticUsage = Get-LiveUsage
            [ordered]@{
                status = 'DIAGNOSTIC_OBSERVATION'; releaseAcceptance = $false; runId = $RunId; testedHead = $head
                parseFailures = $parseFailures; formalMetrics = $diagnosticUsage.Formal
                generationWaitFailure = $diagnosticWaitFailure
                reservationMicroCny = $runReservationMicroCny; pending = $true
            } | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $evidenceDir 'investigation-diagnostic.json') -Encoding utf8
            if ($diagnosticWaitFailure) { throw $diagnosticWaitFailure }
            Assert-LiveUsage $diagnosticUsage
            if ($diagnosticUsage.ProviderAttempts -gt 30 -or $diagnosticUsage.ChargedMicroCny -gt $runReservationMicroCny) {
                throw '调查诊断超出冻结尝试或估算费用上限。'
            }
        }
        $current = Read-SharedLedger
        $current.phases.$RunId.status = 'DIAGNOSTIC_COMPLETED_PENDING_USAGE'
        $current | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $LedgerPath -Encoding utf8
    } else {
    $cumulativeScenarioBudget = 0
    foreach ($scenario in @(
        [pscustomobject]@{ Id = 'L174-01'; File = 'e2e/issue173.full-stack.spec.ts'; Title = 'Issue #173 A：'; Budget = 220000 },
        [pscustomobject]@{ Id = 'L174-02'; File = 'e2e/issue173.full-stack.spec.ts'; Title = 'Issue #173 D：'; Budget = 120000 },
        [pscustomobject]@{ Id = 'L174-03'; File = 'e2e/issue173.full-stack.spec.ts'; Title = 'Issue #173 B：'; Budget = 260000 },
        [pscustomobject]@{ Id = 'L174-04'; File = 'e2e/issue174.live-deepseek.spec.ts'; Title = 'Issue #174 L174-04：'; Budget = 280000 },
        [pscustomobject]@{ Id = 'L174-05'; File = 'e2e/issue174.live-deepseek.spec.ts'; Title = 'Issue #174 L174-05：'; Budget = 120000 }
    )) {
        $usageBefore = if ($scenarioCount -eq 0) { [pscustomobject]@{ ChargedMicroCny = 0 } } else { Get-LiveUsage }
        if ($scenarioCount -gt 0) { Assert-LiveUsage $usageBefore }
        if ($usageBefore.ChargedMicroCny + $scenario.Budget -gt $runReservationMicroCny) {
            throw "下一场景预算准入失败: $($scenario.Id)"
        }
        $watch = [Diagnostics.Stopwatch]::StartNew()
        Invoke-LiveScenario $scenario.File $scenario.Title
        Wait-NoActiveGenerations
        $watch.Stop()
        $scenarioCount += 1
        $scenarioDurations[$scenario.Id] = [math]::Round($watch.Elapsed.TotalMilliseconds)
        $cumulativeScenarioBudget += $scenario.Budget
        $usage = Get-LiveUsage
        Assert-LiveUsage $usage
        if ($usage.ChargedMicroCny -gt $cumulativeScenarioBudget) {
            throw "场景累计费用超过调用前冻结的分段预留: $($scenario.Id)"
        }
    }

    Assert-LiveUsage $usage -RequireAllSeams

    $report = [ordered]@{
        schema = 'issue-174-live-release-v1'
        status = 'PASS'
        runId = $RunId
        testedHead = $head
        base = $base
        model = 'deepseek-v4-flash'
        execution = [ordered]@{
            browser = 'Chromium'; scenarios = 5; result = 'PASS'
            scenarioDurationMs = $scenarioDurations
        }
        calls = [ordered]@{
            logical = $usage.LogicalCalls
            providerAttempts = $usage.ProviderAttempts
            limits = [ordered]@{ logical = $logicalCallLimit; providerAttempts = $providerAttemptLimit }
        }
        tokens = [ordered]@{
            knownTotal = $usage.KnownTokens
            knownLimit = $knownTokenLimit
            investigationTotal = $usage.Formal.totalTokens
            supportInput = [int]$usage.Database.supportInputTokens
            supportOutput = [int]$usage.Database.supportOutputTokens
            intake = $null
            intakeNote = '产品受理接缝未持久化 provider usage；费用按每次20000 micro-CNY保守上界结算。'
        }
        cost = [ordered]@{
            projectLimitMicroCny = $projectLimitMicroCny
            settledBeforeMicroCny = $settledBefore
            runReservedMicroCny = $runReservationMicroCny
            chargedUpperMicroCny = $usage.ChargedMicroCny
            settledAfterMicroCny = $settledBefore + $usage.ChargedMicroCny
            runPending = 0
            priorPendingCount = $expectedPendingCount
            priorReservedMicroCny = $pendingBeforeMicroCny
            budgetBasis = 'USER_REPORTED_PROVIDER_TOTAL_PLUS_NEW_RUN_ESTIMATE'
            historicalPaidUpperMicroCny = $budgetBasisBeforeMicroCny
            providerVerifiedByAgent = $false
            totalCommittedUpperMicroCny = $budgetBasisBeforeMicroCny + $usage.ChargedMicroCny
        }
        layeredEvidence = [ordered]@{
            retrieval = 'PASS_64_OF_64'
            customerAnswer = [ordered]@{
                status = 'ACCEPTED_WITH_KNOWN_LIMITATIONS'; semanticPassed = 35; denominator = 48
                answerablePassed = 28; answerableDenominator = 36
                refusalPassed = 7; refusalDenominator = 12; refusalRecall = 0.5833333333
                refusalPrecision = $null
            }
            supportAnswer = [ordered]@{ status = 'NOT_EVALUATED_KNOWN_LIMITATION' }
        }
        releaseEvidence = [ordered]@{
            structure = [ordered]@{
                passed = $usage.LogicalCalls; denominator = $usage.LogicalCalls; rate = 1
                basis = '五个浏览器场景全部通过产品 strict schema 解析与 Spring 接受，且 failure classifications 为空。'
            }
            customerKnowledge = [ordered]@{ semantic = 'NOT_EVALUATED_KNOWN_LIMITATION'; canonicalCitation = 'PASS'; bodySanity = 'PASS' }
            supportKnowledge = [ordered]@{ semantic = 'NOT_EVALUATED_KNOWN_LIMITATION'; canonicalCitation = 'PASS'; bodySanity = 'PASS' }
            failureClassifications = $usage.Formal.failureClassifications
            latencyMs = [ordered]@{
                maxGenerationTerminal = [long]$usage.Database.maxGenerationMs
                maxFirstPublicDelta = [long]$usage.Database.maxFirstDeltaMs
                supportProvider = 'NOT_PERSISTED'
            }
            realSeams = [ordered]@{
                intakeCalls = [int]$usage.Database.intakeCalls
                action = $usage.Formal.action
                judgment = $usage.Formal.judgment
                customerCommunication = $usage.Formal.customerCommunication
                supportAttempts = [int]$usage.Database.supportAttempts
                model = 'deepseek-v4-flash'
                supportProtocol = 'support-assistance-answer-v2'
            }
        }
        safety = [ordered]@{
            modelApprovalOrExecutionAuthority = $false
            assistancePublishedAutomatically = $false
            safeHandoffWithoutCompensation = $true
        }
        productionScope = 'NOT_EVALUATED'
    }
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding utf8

    Settle-SharedLedger $usage 'PASS'
    $completed = $true
    }
} catch {
    $runFailure = $_
    if (-not $IntakeDiagnostic -and $reservationWritten -and $providerMayHaveRun -and $artifactsAvailable) {
        try {
            $usage = Get-LiveUsage
            $failureReport = [ordered]@{
                schema = $(if ($InvestigationDiagnostic) { 'issue174-investigation-diagnostic-v1' } else { 'issue-174-live-release-v1' }); status = 'INCOMPLETE'; runId = $RunId
                releaseAcceptance = -not $InvestigationDiagnostic
                testedHead = $head; base = $base; model = 'deepseek-v4-flash'
                completedScenarios = $scenarioCount; failure = $runFailure.Exception.Message
                calls = [ordered]@{ logical = $usage.LogicalCalls; providerAttempts = $usage.ProviderAttempts }
                tokens = [ordered]@{ knownTotal = $usage.KnownTokens; intake = $null }
                cost = [ordered]@{
                    observedUpperMicroCny = $usage.ChargedMicroCny
                    reservedMicroCny = $runReservationMicroCny
                    pending = 1
                    note = '任一场景失败都可能包含未持久化的受理尝试；保留整轮预留，禁止再次使用。'
                }
                productionScope = 'NOT_EVALUATED'
            }
            $failureReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
        } catch {
            $metricsFailure = $_.Exception.Message
            $failureReport = [ordered]@{
                schema = $(if ($InvestigationDiagnostic) { 'issue174-investigation-diagnostic-v1' } else { 'issue-174-live-release-v1' }); status = 'INCOMPLETE'; runId = $RunId
                releaseAcceptance = -not $InvestigationDiagnostic
                testedHead = $head; base = $base; model = 'deepseek-v4-flash'
                completedScenarios = $scenarioCount; failure = $runFailure.Exception.Message
                metricsCollection = $metricsFailure
                cost = [ordered]@{ pending = 1; note = 'usage 未确认，保留整轮预留，禁止再次使用。' }
                productionScope = 'NOT_EVALUATED'
            }
            $failureReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
            $runFailure = "运行失败且费用无法完整结算，保留 PENDING 并停止: $($runFailure.Exception.Message); metrics=$metricsFailure"
        }
    } elseif ($reservationWritten -and -not $providerMayHaveRun) {
        $current = Read-SharedLedger
        $current.attempts = @($current.attempts | Where-Object phase -ne $RunId)
        $current.phases.PSObject.Properties.Remove($RunId)
        $current | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $LedgerPath -Encoding utf8
    }
} finally {
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $overridePath) {
        $native = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
        if ($artifactsAvailable) {
            try { Export-BrowserAcceptanceArtifacts } catch { $cleanupFailures += $_.Exception.Message }
        }
        & docker compose -f (Join-Path $repoRoot 'compose.yaml') -f $overridePath --project-name $projectName --profile smoke down --volumes --remove-orphans 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { $cleanupFailures += 'docker compose down 失败。' }
        $PSNativeCommandUseErrorActionPreference = $native
        try { Assert-ComposeProjectResourcesEmpty -ProjectName $projectName -Phase '清理后' } catch { $cleanupFailures += $_.Exception.Message }
        try { Remove-Item -LiteralPath $overridePath -Force } catch { $cleanupFailures += $_.Exception.Message }
    }
    if ($imagesBuilt) {
        try {
            Remove-GateImages -RunId $RunId
            Assert-GateImagesAbsent -RunId $RunId
        } catch { $cleanupFailures += $_.Exception.Message }
    }
    if ($gate) { try { Exit-TestGateLock $gate } catch { $cleanupFailures += $_.Exception.Message } }
    foreach ($name in $priorEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $priorEnvironment[$name], 'Process')
    }
}

if ($runFailure) {
    $cleanup = if ($cleanupFailures.Count -eq 0) { '' } else { "; cleanup=$($cleanupFailures -join ' | ')" }
    throw "$runFailure$cleanup"
}
if ($cleanupFailures.Count -ne 0) { throw "Issue #174 运行通过但资源清理失败: $($cleanupFailures -join ' | ')" }

if ($InvestigationDiagnostic) {
    Write-Host "调查诊断完成，非发布验收；预留保留。证据：$evidenceDir/investigation-diagnostic.json"
} elseif ($IntakeDiagnostic) {
    Write-Host "受理诊断已结束（最多两次请求），非发布验收；预留保留 PENDING。证据：$evidenceDir/intake-diagnostic.json"
} else {
    Write-Host "Issue #174 真实 DeepSeek/Chromium 发布验收通过：run=$RunId report=$reportPath"
}
