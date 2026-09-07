param(
    [switch]$ConfirmProviderSpend,
    [Parameter(Mandatory)][string]$TestedHead,
    [Parameter(Mandatory)][string]$ModelPath,
    [Parameter(Mandatory)][string]$LedgerPath,
    [Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$AuthorizationId,
    [Parameter(Mandatory)][ValidateRange(1, 3000000)][long]$LimitMicros,
    [Parameter(Mandatory)][ValidateRange(1, 10000)][int]$MaxAttempts,
    [Parameter(Mandatory)][ValidateRange(1, 10000000)][int]$MaxTokens,
    [Parameter(Mandatory)][datetimeoffset]$Deadline,
    [Parameter(Mandatory)][ValidateRange(1, 600000)][int]$InvestigationWallClockMs,
    [ValidateSet('', 'no_compensation', 'pending_approval', 'payment_handoff', 'split_recovery', 'generation_fence')][string]$Case = '',
    [ValidateSet('', '1', '2')][string]$Sample = '',
    [string]$RunId = ('issue230-real-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
)

# 先离线验证并审查冻结参数，再显式执行；本脚本不创建或重置授权账本。
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repo = Split-Path -Parent $PSScriptRoot
. "$repo/scripts/test-gate-lock.ps1"
. "$repo/scripts/gate-resources.ps1"
. "$repo/scripts/gate-images.ps1"
Set-Location $repo
if (-not $ConfirmProviderSpend) { throw '必须显式确认真实供应商费用。' }
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) { throw '当前进程缺少 DEEPSEEK_API_KEY；不会读取 .env。' }
if ($RunId -notmatch '^issue230-real-[a-z0-9-]+$') { throw 'RunId 必须使用 issue230-real- 前缀。' }
if ($TestedHead -notmatch '^[0-9a-f]{40}$' -or (git rev-parse HEAD).Trim() -ne $TestedHead -or @(git status --porcelain).Count -ne 0) {
    throw '必须使用已验证的完整提交 SHA，且工作树必须干净。'
}
function Read-AdapterVersion([string]$File, [string]$Prefix) {
    $source = Get-Content -Raw -LiteralPath (Join-Path $repo "agent/src/baseline_agent/$File")
    $prompt = [regex]::Match($source, ('(?m)^' + $Prefix + '_PROMPT_VERSION = "([^"]+)"')).Groups[1].Value
    $schema = [regex]::Match($source, ('(?m)^' + $Prefix + '_SCHEMA_VERSION = "([^"]+)"')).Groups[1].Value
    if ($Prefix -eq 'INTAKE') {
        $schema = @([regex]::Matches($source, '"name": "(customer_intake_[^"]+)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
    }
    if (-not $prompt -or -not $schema) { throw "无法从受测源码读取 $File 的 prompt/schema。" }
    return @{ prompt = $prompt; schema = $schema }
}
$ProviderVersions = @{
    intake = Read-AdapterVersion 'deepseek_intake_model.py' 'INTAKE'
    action = Read-AdapterVersion 'deepseek_investigation_action_model.py' 'ACTION'
    judgment = Read-AdapterVersion 'deepseek_investigation_model.py' 'INVESTIGATION_JUDGMENT'
    communication = Read-AdapterVersion 'deepseek_customer_communication_model.py' 'CUSTOMER_COMMUNICATION'
}
$ledgerPath = (Resolve-Path -LiteralPath $LedgerPath).Path
$ledgerDirectory = (Split-Path -Parent $ledgerPath).Replace('\', '/')
$ledgerName = Split-Path -Leaf $ledgerPath
$modelPath = (Resolve-Path -LiteralPath $ModelPath).Path.Replace('\', '/')
$ledger = Get-Content -Raw -LiteralPath $ledgerPath | ConvertFrom-Json
if ($ledger.schemaVersion -ne 'issue230-core-budget-v1' -or $ledger.currency -ne 'CNY' -or
    $ledger.model -ne 'deepseek-v4-flash' -or $ledger.authorizationId -ne $AuthorizationId -or
    $ledger.limitMicros -ne $LimitMicros -or $ledger.maxAttempts -ne $MaxAttempts -or
    $ledger.maxTokens -ne $MaxTokens -or [datetimeoffset]$ledger.deadline -ne $Deadline -or $Deadline -le [datetimeoffset]::UtcNow) {
    throw '冻结参数与现有核心账本不一致或已到期；禁止自动建立新账本。'
}
if (@($ledger.entries | Where-Object status -ne 'SETTLED').Count -ne 0) { throw '账本含 PENDING/IN_FLIGHT，必须停止，不能释放预留重跑。' }
$planPath = Join-Path $ledgerDirectory 'real-core-plan.json'
if (Test-Path -LiteralPath $planPath) { throw '此授权已冻结执行；禁止通过新 RunId 重跑场景。' }
$matrix = @(foreach ($name in @('no_compensation', 'pending_approval', 'payment_handoff', 'split_recovery', 'generation_fence')) {
    foreach ($number in 1, 2) { [ordered]@{ case = $name; sample = $number; status = 'NOT_RUN' } }
})
$project = "customer-agent-$RunId"
$tag = "gate-$RunId"
$evidence = Join-Path $repo ".local/gate-evidence/$RunId"
if (Test-Path -LiteralPath $evidence) { throw '证据目录已存在，禁止覆盖。' }
$gate = Enter-TestGateLock -Issue 230 -RunId $RunId -CommandType 'real-core-browser' `
    -BaseSha (git rev-parse origin/main).Trim() -HeadSha $TestedHead -ComposeProject $project -ImageTag $tag
$override = Join-Path $evidence 'compose.override.yaml'
$emptyEnv = Join-Path $evidence 'empty.env'
$mount = $evidence.Replace('\', '/')
$started = $false
$built = $false
$servicesReady = $false
$metricsCollected = $false
$cleanupPassed = $false
$outcome = 'NOT_RUN'
$productAcceptance = $false
function Invoke-RealCompose([object[]]$Arguments) {
    & docker compose --profile smoke --env-file $emptyEnv -f (Join-Path $repo 'compose.yaml') -f $override -p $project @Arguments
    if ($LASTEXITCODE -ne 0) { throw "真实核心入口操作失败，退出码 $LASTEXITCODE。" }
}
function Read-MatrixResults($Suite) {
    foreach ($spec in $Suite.specs) {
        if ($spec.title -match '^Issue #230 core ([a-z_]+) sample ([12])$') {
            $name = $Matches[1]; $number = [int]$Matches[2]
            $entry = $matrix | Where-Object { $_.case -eq $name -and $_.sample -eq $number }
            $results = @($spec.tests | ForEach-Object { $_.results })
            if (@($results | Where-Object status -eq 'passed').Count -eq 1) { $entry.status = 'PASS' }
            elseif (@($results | Where-Object { $_.status -in @('failed', 'timedOut', 'interrupted') }).Count -gt 0) { $entry.status = 'FAIL' }
        }
    }
    foreach ($child in $Suite.suites) { Read-MatrixResults $child }
}
try {
    Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '启动前'
    New-Item -ItemType Directory -Path $evidence, (Join-Path $evidence 'artifacts') | Out-Null
    [ordered]@{
        schemaVersion = 'issue230-real-core-plan-v1'; authorizationId = $AuthorizationId
        runId = $RunId; testedHead = $TestedHead; model = 'deepseek-v4-flash'; providerVersions = $ProviderVersions
        limitMicros = $LimitMicros; currency = 'CNY'; maxAttempts = $MaxAttempts; maxTokens = $MaxTokens
        deadline = $Deadline.ToUniversalTime().ToString('o'); investigationWallClockMs = $InvestigationWallClockMs
        denominator = 10; matrix = $matrix; selectedCase = $Case; selectedSample = $Sample; retries = 0; maxFailures = 1
        sideEffects = @('创建本轮合成订单与工单', '发布客户公开回复', '创建待审批提案；不批准或执行补偿')
        notes = @('输入预算是程序工程预留，不是供应商数学上界。', '供应商费用未知时保留预留并停止，不换账本重跑。')
    } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $planPath
    Copy-Item -LiteralPath $planPath -Destination (Join-Path $evidence 'plan.json')
    Set-Content -LiteralPath $emptyEnv -Value @('CUSTOMER_AGENT_FRONTEND_PORT=0', "KNOWLEDGE_MODEL_HOST_PATH=$modelPath")
    # API key 只由 Compose 从当前进程转交；不插入 YAML、计划或控制台。
    @"
services:
  backend:
    image: customer-agent/backend:$tag
    environment:
      SPRING_TO_AGENT_TOKEN: local-spring-to-agent
      AGENT_MACHINE_TOKEN: local-agent-machine
  spring-migrate:
    image: customer-agent/backend:$tag
  agent-server:
    image: customer-agent/agent:$tag
    volumes:
      - '${ledgerDirectory}:/core-budget'
      - type: bind
        source: '$modelPath'
        target: /models/bge-small-zh-v1.5
        read_only: true
        bind:
          create_host_path: false
    environment:
      SPRING_TO_AGENT_TOKEN: local-spring-to-agent
      AGENT_MACHINE_TOKEN: local-agent-machine
      AGENT_INVESTIGATION_MODEL_MODE: deepseek-formal
      AGENT_INVESTIGATION_ACTION_MODEL_MODE: deepseek-formal
      AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE: deepseek-formal
      AGENT_INVESTIGATION_SHADOW_MODE: disabled
      AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS: $InvestigationWallClockMs
      INVESTIGATION_MODEL_MODE: deepseek-formal
      INVESTIGATION_ACTION_MODEL_MODE: deepseek-formal
      CUSTOMER_COMMUNICATION_MODEL_MODE: deepseek-formal
      DEEPSEEK_API_KEY:
      DEEPSEEK_MODEL: deepseek-v4-flash
      CORE_VALIDATION_BUDGET_PATH: /core-budget/$ledgerName
      CORE_VALIDATION_AUTHORIZATION_ID: '$AuthorizationId'
  agent-migrate:
    image: customer-agent/agent:$tag
  core-budget-stop:
    image: customer-agent/agent:$tag
    entrypoint: [python, -c]
    command: ['import sys; from pathlib import Path; from baseline_agent.core_validation_budget import CoreValidationBudget; CoreValidationBudget.open(Path(sys.argv[1]), authorization_id=sys.argv[2]).stop(sys.argv[3])', '/core-budget/$ledgerName', '$AuthorizationId', CORE_MATRIX_FINISHED]
    volumes:
      - '${ledgerDirectory}:/core-budget'
    networks: [data]
  core-metrics:
    image: customer-agent/agent:$tag
    entrypoint: [python, -m, baseline_agent.core_validation_metrics]
    command: [--ledger-path, '/core-budget/$ledgerName', --report-path, /core-evidence/metrics.json]
    environment:
      SPRING_FORMAL_DATABASE_URI: postgresql://spring_app:local-spring-app@postgres:5432/customer_agent
      AGENT_SERVER_URL: http://agent-server:2024
      SPRING_TO_AGENT_TOKEN: local-spring-to-agent
    volumes:
      - '${ledgerDirectory}:/core-budget:ro'
      - '${mount}:/core-evidence'
    networks: [data, services]
  browser-frontend:
    image: customer-agent/frontend-browser-server:$tag
  browser-acceptance:
    image: customer-agent/frontend-browser-test:$tag
    environment:
      ISSUE230_CORE_CASE: '$Case'
      ISSUE230_CORE_SAMPLE: '$Sample'
      PLAYWRIGHT_JSON_OUTPUT_FILE: /artifacts/playwright.json
    volumes:
      - '${mount}/artifacts:/artifacts'
"@ | Set-Content -LiteralPath $override
    $config = Invoke-RealCompose @('config', '--format', 'json') | ConvertFrom-Json
    Assert-ComposeResourcesOwned -ProjectName $project -EffectiveConfig $config
    $agentEnvironment = $config.services.'agent-server'.environment
    if ($agentEnvironment.CORE_VALIDATION_BUDGET_PATH -ne "/core-budget/$ledgerName" -or
        $agentEnvironment.CORE_VALIDATION_AUTHORIZATION_ID -ne $AuthorizationId -or
        $agentEnvironment.DEEPSEEK_API_KEY -ne $env:DEEPSEEK_API_KEY -or
        $agentEnvironment.DEEPSEEK_RESPONSES_ENDPOINT -or $config.networks.'provider-egress'.internal) {
        throw '实际配置不是冻结账本与默认外部供应商。'
    }
    $effectiveLimits = [ordered]@{}
    foreach ($name in @('AGENT_INVESTIGATION_MAX_ACTIONS', 'AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS',
        'AGENT_INVESTIGATION_MAX_TOKENS', 'AGENT_INVESTIGATION_MAX_COST_MICROS',
        'AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS', 'AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS')) {
        $effectiveLimits[$name] = $agentEnvironment.$name
    }
    $plan = Get-Content -Raw -LiteralPath $planPath | ConvertFrom-Json -AsHashtable
    $plan.effectiveInvestigationLimits = $effectiveLimits
    $plan | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $planPath
    Copy-Item -LiteralPath $planPath -Destination (Join-Path $evidence 'plan.json')
    $config = $null; $agentEnvironment = $null
    $built = $true
    Invoke-RealCompose @('build', 'backend', 'agent-server', 'browser-frontend', 'browser-acceptance')
    if ($Deadline -le [datetimeoffset]::UtcNow) { throw '构建后已超过冻结截止时间，禁止开始真实调用。' }
    $started = $true
    Invoke-RealCompose @('up', '-d', '--no-build', '--wait', 'backend', 'agent-server', 'browser-frontend')
    $servicesReady = $true
    # 不启动 compensation-executor，场景也不执行审批或赔付操作。
    Invoke-RealCompose @('run', '--rm', '--no-deps', 'browser-acceptance', '--workers=1', '--retries=0', '--max-failures=1', '--reporter=json', '--output=/artifacts', 'e2e/issue230.core-matrix.spec.ts')
    $outcome = 'BROWSER_PASS'
} catch {
    $outcome = 'FAIL'
    throw
} finally {
    if ($started) {
        try {
            # 先关闭本授权的新调用入口；已发出的请求仍可返回 usage 并结算。
            Invoke-RealCompose @('run', '--rm', '--no-deps', 'core-budget-stop')
            $drainDeadline = [datetimeoffset]::UtcNow.AddSeconds(30)
            do {
                $settling = Get-Content -Raw -LiteralPath $ledgerPath | ConvertFrom-Json
                if (@($settling.entries | Where-Object status -eq 'IN_FLIGHT').Count -eq 0) { break }
                Start-Sleep -Milliseconds 500
            } while ([datetimeoffset]::UtcNow -lt $drainDeadline)
        } catch {
            $outcome = 'FAIL'
            Write-Warning '预算停止写入失败，立即停止 Agent；未结算用量保持未知。'
            try { Invoke-RealCompose @('stop', 'agent-server') } catch { Write-Warning 'Agent 停止失败，继续执行资源清理。' }
        }
    }
    if ($servicesReady) {
        try {
            Invoke-RealCompose @('run', '--rm', '--no-deps', 'core-metrics')
            $metricsCollected = $true
        } catch { $outcome = 'FAIL'; Write-Warning '计量不完整，保留账本与失败证据，不重跑。' }
    }
    try {
        if ($started) { Invoke-RealCompose @('down', '--volumes', '--remove-orphans') }
        if ($built) {
            foreach ($name in @('backend', 'agent', 'frontend-browser-server', 'frontend-browser-test')) {
                $image = "customer-agent/${name}:$tag"
                if (@(docker image ls --format '{{.Repository}}:{{.Tag}}') -contains $image) { docker image rm $image }
            }
            Assert-GateImagesAbsent -RunId $RunId
        }
        Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '清理后'
        $cleanupPassed = $true
    } finally {
        try {
            $browserReport = Join-Path $evidence 'artifacts/playwright.json'
            if (Test-Path -LiteralPath $browserReport) {
                $playwright = Get-Content -Raw -LiteralPath $browserReport | ConvertFrom-Json
                foreach ($suite in $playwright.suites) { Read-MatrixResults $suite }
            }
            if (Test-Path -LiteralPath $evidence) {
                $paidLedger = Get-Content -Raw -LiteralPath $ledgerPath | ConvertFrom-Json
                $allPassed = @($matrix | Where-Object status -eq 'PASS').Count -eq 10
                $unsettled = @($paidLedger.entries | Where-Object status -ne 'SETTLED').Count
                $metricsComplete = $false
                if ($metricsCollected) {
                    $metrics = Get-Content -Raw -LiteralPath (Join-Path $evidence 'metrics.json') | ConvertFrom-Json
                    $metricsComplete = ($metrics.missingEvidenceSources -eq 0 -and
                        $metrics.unattributedAttemptIds.Count -eq 0 -and
                        $metrics.knownProviderAttempts -eq @($paidLedger.entries).Count -and
                        $null -ne $metrics.tokens -and $null -ne $metrics.estimatedCostMicros)
                }
                $productAcceptance = ($allPassed -and $metricsComplete -and $cleanupPassed -and $unsettled -eq 0 -and $outcome -eq 'BROWSER_PASS')
                [ordered]@{
                    runId = $RunId; head = $TestedHead; authorizationId = $AuthorizationId
                    outcome = $outcome; denominator = 10; matrix = $matrix
                    metricsCollected = $metricsCollected; cleanupPassed = $cleanupPassed
                    productAcceptance = $productAcceptance
                } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $evidence 'result.json')
                Copy-Item -LiteralPath $ledgerPath -Destination (Join-Path $evidence 'ledger.final.json')
            }
        } finally {
            if ($cleanupPassed) { Exit-TestGateLock $gate; Write-Host 'LOCK_RELEASED' }
            elseif ($gate.AcquiredHere) {
                try { $gate.Mutex.ReleaseMutex() } finally { $gate.Mutex.Dispose() }
                if ($gate.PreviousToken) { $env:CUSTOMER_AGENT_TEST_GATE_TOKEN = $gate.PreviousToken }
                else { Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_TOKEN -ErrorAction SilentlyContinue }
                $script:TestGateHeldMutex = $gate.PreviousMutex
            }
        }
    }
}
if (-not $productAcceptance) { throw '核心矩阵或计量未完整通过；保留失败和未运行分母，不追加真实运行。' }
