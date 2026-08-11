param(
    [switch]$Reset,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$imageTag = if ($env:CUSTOMER_AGENT_IMAGE_TAG) { $env:CUSTOMER_AGENT_IMAGE_TAG } else { 'local' }
$env:CUSTOMER_AGENT_IMAGE_TAG = $imageTag

if ($Reset) {
    docker compose down --volumes --remove-orphans
}

if (-not $SkipBuild) {
    docker build --build-arg "GRADLE_OPTS=$($env:CUSTOMER_AGENT_GRADLE_OPTS)" --target test --tag "customer-agent/backend-test:$imageTag" backend
    docker build --target test --tag "customer-agent/agent-test:$imageTag" agent
    docker build --target test --tag "customer-agent/frontend-test:$imageTag" frontend
    docker compose up --detach --build --force-recreate --wait
} else {
    docker compose up --detach --force-recreate --wait
}
docker compose exec -T agent-server sh -c 'test -z "${EXECUTOR_MACHINE_TOKEN+x}"'
docker compose exec -T compensation-executor sh -c 'test -z "${AGENT_MACHINE_TOKEN+x}"'

$migrationHistory = docker compose exec -T postgres psql -U postgres -d customer_agent -Atc "select version || ':' || success from flyway_schema_history order by installed_rank"
if (($migrationHistory -join ',') -ne '1:true,2:true,3:true,4:true,5:true,6:true,7:true,8:true,9:true,10:true,11:true,12:true,13:true,14:true,15:true,16:true,17:true,18:true') {
    throw "Spring Flyway 迁移历史不完整: $($migrationHistory -join ',')"
}

docker compose stop compensation-executor

function Invoke-Issue29Scenario([string]$Scenario, [string]$SimulatorScenario, [string]$PollDelay) {
    $env:VITE_E2E_SCENARIO = $Scenario
    $env:EXECUTOR_SIMULATION_SCENARIO = $SimulatorScenario
    $env:EXECUTOR_POLL_DELAY = $PollDelay
    docker compose up --detach --force-recreate compensation-executor
    docker compose --profile smoke run --rm --entrypoint npm frontend-acceptance `
        test -- src/Issue29.e2e.test.tsx
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #29 React 全栈验收失败 ($Scenario)，退出码: $LASTEXITCODE"
    }
    $orderReference = if ($Scenario -eq 'normal') {
        'ORDER-DELAY-E2E-NORMAL'
    } else {
        'ORDER-DELAY-E2E-RECONCILIATION'
    }
    $persistentEvidence = docker compose exec -T postgres psql -U postgres -d customer_agent -Atc "
        select e.status || ':' ||
          (select count(*) from compensation_execution where order_reference = '$orderReference') || ':' ||
          (select count(*) from simulated_compensation_provider_operation where execution_id = e.id) || ':' ||
          (select count(*) from compensation_execution_result where execution_id = e.id) || ':' ||
          (select count(*) from simulated_partial_refund where execution_id = e.id) || ':' ||
          t.lifecycle_state || ':' ||
          (select count(*) from public_message where ticket_id = t.id
             and body = '已完成 26.80 CNY 模拟部分退款，退回原支付方式（尾号 4242）。')
        from compensation_execution e
        join compensation_proposal_revision p on p.id = e.proposal_revision_id
        join support_ticket t on t.id = p.ticket_id
        where e.order_reference = '$orderReference'"
    if ($persistentEvidence -ne 'SUCCEEDED:1:1:1:1:RESOLVED:1') {
        throw "Issue #29 持久约束不满足 ($Scenario): $persistentEvidence"
    }
    if ($Scenario -eq 'reconciliation') {
        $attemptEvidence = docker compose exec -T postgres psql -U postgres -d customer_agent -Atc "
            select string_agg(a.outcome, ',' order by a.started_at)
            from compensation_execution_attempt a
            join compensation_execution e on e.id = a.execution_id
            where e.order_reference = '$orderReference'"
        if ($attemptEvidence -ne 'UNKNOWN,FOUND') {
            throw "Issue #29 对账尝试链不满足: $attemptEvidence"
        }
    }
    docker compose stop compensation-executor
}

Invoke-Issue29Scenario 'normal' 'SUCCESS' '0.25'
Invoke-Issue29Scenario 'reconciliation' 'AFTER_EFFECT_RESPONSE_LOST' '2'
Remove-Item Env:VITE_E2E_SCENARIO -ErrorAction SilentlyContinue
Remove-Item Env:EXECUTOR_SIMULATION_SCENARIO -ErrorAction SilentlyContinue
Remove-Item Env:EXECUTOR_POLL_DELAY -ErrorAction SilentlyContinue

docker compose --profile smoke run --rm integration-smoke
if ($LASTEXITCODE -ne 0) {
    throw "集成 smoke 失败，退出码: $LASTEXITCODE"
}
docker compose start compensation-executor
$automaticExecutorEvidence = $null
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $automaticExecutorEvidence = docker compose exec -T postgres psql -U postgres -d customer_agent -Atc "select e.status || ':' || count(c.execution_id) || ':' || t.lifecycle_state from compensation_execution e join compensation_proposal_revision p on p.id = e.proposal_revision_id join support_ticket t on t.id = p.ticket_id left join simulated_coupon c on c.execution_id = e.id where e.order_reference = 'ORDER-DELAY-EXECUTOR-AUTO' group by e.status, t.lifecycle_state"
    if ($automaticExecutorEvidence -eq 'SUCCEEDED:1:RESOLVED') { break }
    Start-Sleep -Milliseconds 250
}
if ($automaticExecutorEvidence -ne 'SUCCEEDED:1:RESOLVED') {
    throw "常驻补偿执行器未完成唯一模拟优惠券: $automaticExecutorEvidence"
}
docker compose --profile smoke run --rm frontend-acceptance
if ($LASTEXITCODE -ne 0) {
    throw "React 实时验收失败，退出码: $LASTEXITCODE"
}

$status = Invoke-RestMethod -Uri 'http://127.0.0.1:4180/api/system/status'
if ($status.status -ne 'UP') {
    throw "Spring 状态投影不是 UP: $($status | ConvertTo-Json -Compress)"
}

$sensitiveRules = Get-Content "$PSScriptRoot/../frontend/src/sensitive-content-patterns.json" -Raw | ConvertFrom-Json
$sensitiveContentPattern = $sensitiveRules.contentPatterns -join '|'
$frontendSensitivePattern = (@($sensitiveRules.contentPatterns) + @($sensitiveRules.internalAddressPatterns)) -join '|'
docker run --rm --entrypoint sh "customer-agent/frontend:$imageTag" -c "
    grep -R -q '/support' /usr/share/nginx/html &&
    grep -R -q '/approver' /usr/share/nginx/html &&
    ! grep -R -E '$frontendSensitivePattern' /usr/share/nginx/html"

$runtimeLogs = docker compose logs --no-color
$forbiddenRuntimeLog = $runtimeLogs | Select-String -Pattern $sensitiveContentPattern
if ($forbiddenRuntimeLog) {
    throw "运行日志包含禁止进入产品日志的敏感或内部标识: $($forbiddenRuntimeLog | Select-Object -First 1)"
}

$versions = [ordered]@{
    node = (docker run --rm node:24.19.0-bookworm-slim node --version 2>$null)
    java = (docker run --rm --entrypoint sh "customer-agent/backend:$imageTag" -c 'java -version 2>&1 | head -n 1')
    python = (docker run --rm --entrypoint python "customer-agent/agent:$imageTag" --version 2>&1)
    postgres = (docker compose exec -T postgres postgres --version)
}

[pscustomobject]@{
    status = $status.status
    spring = $status.services.spring
    database = $status.services.database
    agent = $status.services.agent
    versions = $versions
} | ConvertTo-Json -Depth 4
