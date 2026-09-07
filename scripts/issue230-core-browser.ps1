param(
    [Parameter(Mandatory)][string]$ModelPath,
    [string]$RunId = ('issue230-core-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
)

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
$fixtureDirectory = (Join-Path $evidence 'provider').Replace('\', '/')
$started = $false
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
    command: [--mode, normal, --audit-file, /evidence/attempts.json]
    volumes:
      - '${providerFixture}:/fixture/core_provider_fixture.py:ro'
      - '${fixtureDirectory}:/evidence'
    healthcheck:
      test: [CMD, python, -c, "import httpx; httpx.get('http://127.0.0.1:8099/health').raise_for_status()"]
      interval: 2s
      timeout: 3s
      retries: 15
    networks: [services]
  agent-migrate:
    image: customer-agent/agent:$tag
  compensation-executor:
    image: customer-agent/agent:$tag
  browser-frontend:
    image: customer-agent/frontend-browser-server:$tag
  browser-acceptance:
    image: customer-agent/frontend-browser-test:$tag
    volumes:
      - '${artifacts}:/artifacts'
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
    $testFiles = @('e2e/issue230.full-stack.spec.ts')
    Invoke-CoreCompose (@('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'prettier', '--check') + $testFiles)
    Invoke-CoreCompose (@('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'eslint', '--max-warnings', '0') + $testFiles)
    Invoke-CoreCompose @('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'tsc', '--noEmit')
    Invoke-CoreCompose @('up', '-d', '--no-build', '--wait', 'backend', 'agent-server', 'compensation-executor', 'browser-frontend')
    Invoke-CoreCompose @('run', '--rm', '--no-deps', 'browser-acceptance', '--workers=1', '--output=/artifacts', 'e2e/issue230.full-stack.spec.ts')
    $ledger = Get-Content -Raw -LiteralPath (Join-Path $ledgerDirectory 'ledger.json') | ConvertFrom-Json
    $provider = Get-Content -Raw -LiteralPath (Join-Path $fixtureDirectory 'attempts.json') | ConvertFrom-Json
    if (@($ledger.entries).Count -ne $provider.attemptCount -or
        @($ledger.entries | Where-Object status -ne 'SETTLED').Count -ne 0 -or
        -not $provider.actionBarrierPassed) { throw '供应商实收请求、持久账本或双票并发证据不一致。' }
    foreach ($role in @('intake', 'action', 'judgment', 'communication')) {
        if (@($ledger.entries | Where-Object role -eq $role).Count -eq 0) { throw "缺少 $role 的真实适配器请求证据。" }
    }
    $outcome = 'PASS'
} catch {
    $outcome = 'FAIL'
    throw
} finally {
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
                @{ runId = $RunId; head = (git rev-parse HEAD).Trim(); outcome = $outcome; cleanupPassed = $cleanupPassed; paidCalls = 0 } |
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


