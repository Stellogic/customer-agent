param(
    [Parameter(Mandatory)][string]$ModelPath,
    [ValidateSet("normal", "missing_usage", "provider400")][string]$Mode = "normal",
    [switch]$CoreMatrix,
    [string]$RunId = ('issue230-core-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
)

if ($CoreMatrix -and $Mode -ne 'normal') { throw 'CoreMatrix 只允许 normal 离线模式。' }
$testFile = if ($CoreMatrix) { 'e2e/issue230.core-matrix.spec.ts' } else { 'e2e/issue230.full-stack.spec.ts' }
$barrierTimeout = if ($CoreMatrix) { 0 } else { 8 }
# 仅离线夹具留出数据库观测和页面发送的时间；真实供应商入口不注入此延时。
$streamPause = if ($CoreMatrix) { 5 } else { 0 }

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repo = Split-Path -Parent $PSScriptRoot
. "$repo/scripts/test-gate-lock.ps1"
. "$repo/scripts/gate-resources.ps1"
. "$repo/scripts/gate-images.ps1"
if ($RunId -notmatch '^issue230-core-[a-z0-9-]+$') { throw 'RunId 必须使用 issue230-core- 前缀和小写字母、数字或连字符。' }
$frontendPath = (Join-Path $repo 'frontend').Replace('\', '/')
$modelPath = (Resolve-Path -LiteralPath $ModelPath).Path.Replace('\', '/')
if (-not (Test-Path -LiteralPath $modelPath)) { throw '离线检索模型目录缺失。' }
Set-Location $repo
$project = "customer-agent-$RunId"
$tag = "gate-$RunId"
$evidence = Join-Path $repo ".local/gate-evidence/$RunId"
$artifacts = (Join-Path $evidence 'artifacts').Replace('\', '/')
if (Test-Path -LiteralPath $evidence) { throw '回归证据目录已存在，禁止重用本轮标识。' }
$gate = Enter-TestGateLock -Issue 230 -RunId $RunId -CommandType 'core-provider-browser' `
    -BaseSha (git rev-parse origin/main).Trim() -HeadSha (git rev-parse HEAD).Trim() -ComposeProject $project -ImageTag $tag
$override = Join-Path $evidence 'compose.override.yaml'
$emptyEnv = Join-Path $evidence 'empty.env'
$providerFixture = (Join-Path $repo 'agent/tests/support/core_provider_fixture.py').Replace('\', '/')
$ledgerDirectory = (Join-Path $evidence 'budget').Replace('\', '/')
$evidenceMount = $evidence.Replace('\', '/')
$fixtureDirectory = (Join-Path $evidence 'provider').Replace('\', '/')
$started = $false
$servicesReady = $false
$metricsCollected = $false
$built = $false
$cleanupPassed = $false
$outcome = 'NOT_RUN'
function Invoke-CoreCompose([object[]]$Arguments) {
    & docker compose --profile smoke --env-file $emptyEnv -f (Join-Path $repo 'compose.yaml') -f $override -p $project @Arguments
    if ($LASTEXITCODE -ne 0) { throw "核心回归 Compose 操作失败，退出码 $LASTEXITCODE。" }
}
try {
    Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '启动前'
    New-Item -ItemType Directory -Path $evidence | Out-Null
    New-Item -ItemType Directory -Path $artifacts, $ledgerDirectory, $fixtureDirectory | Out-Null
    Set-Content -LiteralPath $emptyEnv -Value @('CUSTOMER_AGENT_FRONTEND_PORT=0', "KNOWLEDGE_MODEL_HOST_PATH=$modelPath")
    # 离线供应商合同回归：真实四模型适配器、Spring 与 LangGraph；只连接内部夹具。
    # 账本在主机证据目录，down --volumes 不会删除；新 RunId 代表新的离线实验。
    @"
services:
  backend:
    environment:
      SPRING_TO_AGENT_TOKEN: local-spring-to-agent
      AGENT_MACHINE_TOKEN: local-agent-machine
    image: customer-agent/backend:$tag
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
      INVESTIGATION_MODEL_MODE: deepseek-formal
      INVESTIGATION_ACTION_MODEL_MODE: deepseek-formal
      CUSTOMER_COMMUNICATION_MODEL_MODE: deepseek-formal
      DEEPSEEK_API_KEY: synthetic-core-fixture-key
      DEEPSEEK_MODEL: deepseek-v4-flash
      DEEPSEEK_RESPONSES_ENDPOINT: http://core-provider:8099/responses
      no_proxy: '*'
      CORE_VALIDATION_BUDGET_PATH: /core-budget/ledger.json
      CORE_VALIDATION_AUTHORIZATION_ID: offline-$RunId
    depends_on:
      core-budget-init:
        condition: service_completed_successfully
      core-provider:
        condition: service_healthy
  core-budget-init:
    image: customer-agent/agent:$tag
    entrypoint: [python, -c]
    command:
      - "from pathlib import Path; from datetime import datetime, UTC, timedelta; from baseline_agent.core_validation_budget import CoreValidationBudget; CoreValidationBudget.create(Path('/core-budget/ledger.json'), authorization_id='offline-$RunId', limit_micros=3000000, max_attempts=60, max_tokens=240000, deadline=datetime.now(UTC)+timedelta(minutes=15))"
    volumes:
      - '${ledgerDirectory}:/core-budget'
    networks: [services]
    restart: 'no'
  core-provider:
    image: customer-agent/agent:$tag
    entrypoint: [python, /fixture/core_provider_fixture.py]
    command: [--mode, $Mode, --audit-file, /evidence/attempts.json, --action-barrier-timeout, "$barrierTimeout", --stream-pause-seconds, "$streamPause"]
    volumes:
      - '${providerFixture}:/fixture/core_provider_fixture.py:ro'
      - '${fixtureDirectory}:/evidence'
    healthcheck:
      test: [CMD, python, -c, "import httpx; httpx.get('http://127.0.0.1:8099/health').raise_for_status()"]
      interval: 2s
      timeout: 3s
      retries: 15
    networks: [services]
  core-metrics:
    image: customer-agent/agent:$tag
    entrypoint: [python, -m, baseline_agent.core_validation_metrics]
    command: [--ledger-path, /core-evidence/budget/ledger.json, --report-path, /core-evidence/metrics.json]
    environment:
      SPRING_FORMAL_DATABASE_URI: postgresql://spring_app:local-spring-app@postgres:5432/customer_agent
      AGENT_SERVER_URL: http://agent-server:2024
      SPRING_TO_AGENT_TOKEN: local-spring-to-agent
    volumes:
      - '${evidenceMount}:/core-evidence'
    networks: [data, services]
  agent-migrate:
    image: customer-agent/agent:$tag
  compensation-executor:
    image: customer-agent/agent:$tag
  browser-frontend:
    image: customer-agent/frontend-browser-server:$tag
  browser-acceptance:
    environment:
      ISSUE230_PROVIDER_MODE: $Mode
    image: customer-agent/frontend-browser-test:$tag
    volumes:
      - '${artifacts}:/artifacts'
      - '${evidenceMount}:/core-evidence:ro'
      - '${frontendPath}/src:/app/src:ro'
      - '${frontendPath}/tsconfig.json:/app/tsconfig.json:ro'
      - '${frontendPath}/vite.config.ts:/app/vite.config.ts:ro'
      - '${frontendPath}/eslint.config.js:/app/eslint.config.js:ro'
      - '${frontendPath}/.prettierrc.json:/app/.prettierrc.json:ro'
networks:
  provider-egress:
    internal: true
"@ | Set-Content -LiteralPath $override
    $config = Invoke-CoreCompose @('config', '--format', 'json') | ConvertFrom-Json
    Assert-ComposeResourcesOwned -ProjectName $project -EffectiveConfig $config
    $agentEnvironment = $config.services.'agent-server'.environment
    if ($agentEnvironment.AGENT_INVESTIGATION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.AGENT_INVESTIGATION_ACTION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.INVESTIGATION_MODEL_MODE -ne 'deepseek-formal' -or
        $agentEnvironment.DEEPSEEK_API_KEY -ne 'synthetic-core-fixture-key' -or
        $agentEnvironment.DEEPSEEK_RESPONSES_ENDPOINT -ne 'http://core-provider:8099/responses' -or
        -not $config.networks.'provider-egress'.internal) { throw '配置不是冻结的离线供应商模式。' }
    $config = $null
    $built = $true
    Invoke-CoreCompose @('build', 'backend', 'agent-server', 'browser-frontend', 'browser-acceptance')
    $started = $true
    $testFiles = @($testFile)
    Invoke-CoreCompose (@('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'prettier', '--check') + $testFiles)
    Invoke-CoreCompose (@('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'eslint', '--max-warnings', '0') + $testFiles)
    Invoke-CoreCompose @('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'tsc', '--noEmit')
    Invoke-CoreCompose @('up', '-d', '--no-build', '--wait', 'backend', 'agent-server', 'compensation-executor', 'browser-frontend')
    $servicesReady = $true
    Invoke-CoreCompose @('exec', '-T', 'agent-server', 'python', '-c', "import httpx; httpx.get('http://core-provider:8099/health', timeout=5).raise_for_status(); print('CORE_PROVIDER_REACHABLE')")
    Invoke-CoreCompose @('run', '--rm', '--no-deps', 'browser-acceptance', '--workers=1', '--output=/artifacts', $testFile)
    Invoke-CoreCompose @('run', '--rm', '--no-deps', 'core-metrics')
    $metricsCollected = $true
    $ledger = Get-Content -Raw -LiteralPath (Join-Path $ledgerDirectory 'ledger.json') | ConvertFrom-Json
    $provider = Get-Content -Raw -LiteralPath (Join-Path $fixtureDirectory 'attempts.json') | ConvertFrom-Json
    if (@($ledger.entries).Count -ne $provider.attemptCount -or
        (-not $CoreMatrix -and -not $provider.actionBarrierPassed)) { throw '供应商实收请求、持久账本或双票并发证据不一致。' }
    $report = Get-Content -Raw -LiteralPath (Join-Path $evidence 'metrics.json') | ConvertFrom-Json
    if ($report.knownProviderAttempts -ne $provider.attemptCount -or $report.inFlightReservedMicros -ne 0) {
        throw '实际产品计量与供应商请求数不一致或仍存在未完成调用。'
    }
    if ($Mode -eq 'normal') {
        if (@($ledger.entries | Where-Object status -ne 'SETTLED').Count -ne 0 -or
            $report.missingEvidenceSources -ne 0 -or $report.unattributedAttemptIds.Count -ne 0) {
            throw '正常场景存在未结算或缺失的调用证据。'
        }
        foreach ($role in @('intake', 'action', 'judgment', 'communication')) {
            if (@($ledger.entries | Where-Object role -eq $role).Count -eq 0) { throw "缺少 $role 的实际请求证据。" }
        }
    } else {
        $pending = @($ledger.entries | Where-Object status -eq 'PENDING')
        if ($pending.Count -ne 1 -or $pending[0].role -ne 'communication' -or
            $null -ne $pending[0].estimatedCostMicros -or $report.pendingReservedMicros -le 0 -or
            $null -ne $report.tokens -or $null -ne $report.estimatedCostMicros) {
            throw '故障场景没有保留未知用量与预留，不能作为故障回归通过。'
        }
    }
    $outcome = 'PASS'
} catch {
    $outcome = 'FAIL'
    throw
} finally {
    # 浏览器失败也先尽力保留实际计量，不能用采集失败跳过资源清理。
    if ($servicesReady -and -not $metricsCollected) {
        try {
            Invoke-CoreCompose @('run', '--rm', '--no-deps', 'core-metrics')
            $metricsCollected = $true
        } catch { Write-Warning '本轮计量采集失败，结果保持 FAIL；隔离资源仍按所属 project 清理。' }
    }
    try {
        if ($started) { Invoke-CoreCompose @('down', '--volumes', '--remove-orphans') }
        if ($built) {
            foreach ($name in @('backend', 'agent', 'frontend-browser-server', 'frontend-browser-test')) {
                $image = "customer-agent/${name}:$tag"
                if (@(docker image ls --format '{{.Repository}}:{{.Tag}}') -contains $image) {
                    docker image rm $image
                }
            }
            Assert-GateImagesAbsent -RunId $RunId
        }
        Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '清理后'
        $cleanupPassed = $true
    } finally {
        try {
            if (Test-Path -LiteralPath $evidence) {
                @{ runId = $RunId; head = (git rev-parse HEAD).Trim(); outcome = $outcome; cleanupPassed = $cleanupPassed; paidCalls = 0; providerMode = $Mode; coreMatrix = [bool]$CoreMatrix; metricsCollected = $metricsCollected; productAcceptance = ($Mode -eq 'normal' -and $outcome -eq 'PASS') } |
                    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'result.json')
            }
        } finally {
            if ($cleanupPassed) {
                Exit-TestGateLock $gate
                Write-Host 'LOCK_RELEASED'
            } elseif ($gate.AcquiredHere) {
                # 清理失败保留原门禁记录；下次按该 project/tag 检测残留并要求恢复。
                # 此处只释放本脚本持有的互斥量，不能调用会删除记录的 Exit-TestGateLock。
                try { $gate.Mutex.ReleaseMutex() } finally { $gate.Mutex.Dispose() }
                if ($gate.PreviousToken) {
                    $env:CUSTOMER_AGENT_TEST_GATE_TOKEN = $gate.PreviousToken
                } else {
                    Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_TOKEN -ErrorAction SilentlyContinue
                }
                $script:TestGateHeldMutex = $gate.PreviousMutex
            }
        }
    }
}
