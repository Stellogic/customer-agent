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
$env:AGENT_INVESTIGATION_SHADOW_MODE = 'offline'
$frontendPort = if ($env:CUSTOMER_AGENT_FRONTEND_PORT) { $env:CUSTOMER_AGENT_FRONTEND_PORT } else { '4180' }
$suiteName = if ($Reset) { 'FULL_RESET_GATE' } else { 'PERSISTENT_RERUN_SUITE' }
Write-Host "smoke suite: $suiteName"
if (-not $Reset) {
    Write-Host 'PERSISTENT_RERUN_SUITE 覆盖 Issue #29 两链、同卷持久化、既有自动执行器结果回读、React live、产物/日志隐私与稳定排序；不等价于全量门禁。'
}

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
if (($migrationHistory -join ',') -ne '1:true,2:true,3:true,4:true,5:true,6:true,7:true,8:true,9:true,10:true,11:true,12:true,13:true,14:true,15:true,16:true,17:true,18:true,19:true,20:true,21:true') {
    throw "Spring Flyway 迁移历史不完整: $($migrationHistory -join ',')"
}

docker compose stop compensation-executor
$issue29RunNamespace = [guid]::NewGuid().ToString('N').Substring(0, 12)

function Get-Issue29EvidenceDigest([string]$ExcludedNamespace = '') {
    $namespacePredicate = if ($ExcludedNamespace) {
        "and e.order_reference not like '%-$ExcludedNamespace'"
    } else {
        ''
    }
    docker compose exec -T postgres psql -U postgres -d customer_agent -Atc "
        select count(*) || ':' || md5(coalesce(string_agg(
          e.order_reference || ':' || e.status || ':' || t.lifecycle_state || ':' ||
          (select count(*) from simulated_compensation_provider_operation where execution_id = e.id) || ':' ||
          (select count(*) from compensation_execution_result where execution_id = e.id) || ':' ||
          (select count(*) from simulated_partial_refund where execution_id = e.id) || ':' ||
          (select count(*) from public_message where ticket_id = t.id
             and body = '已完成 26.80 CNY 模拟部分退款，退回原支付方式（尾号 4242）。') || ':' ||
          coalesce((select string_agg(a.outcome, ',' order by a.started_at,
            case a.attempt_type when 'EXECUTION' then 0 when 'RECONCILIATION' then 1 end)
            from compensation_execution_attempt a where a.execution_id = e.id), ''),
          '|' order by e.order_reference), ''))
        from compensation_execution e
        join compensation_proposal_revision p on p.id = e.proposal_revision_id
        join support_ticket t on t.id = p.ticket_id
        where e.order_reference ~ '^ORDER-DELAY-E2E-(NORMAL|RECONCILIATION)-[0-9a-f]{12}$'
          $namespacePredicate"
}

$priorIssue29EvidenceDigest = Get-Issue29EvidenceDigest

function Invoke-Issue29Scenario([string]$Scenario, [string]$SimulatorScenario, [string]$PollDelay) {
    $scenarioName = $Scenario.ToUpperInvariant()
    $orderReference = "ORDER-DELAY-E2E-$scenarioName-$issue29RunNamespace"
    if ($orderReference -notmatch '^[A-Z0-9-]+$') {
        throw "Issue #29 场景 namespace 非法: $orderReference"
    }
    $fixtureTemplate = if ($Scenario -eq 'normal') {
        'ORDER-DELAY-E2E-NORMAL'
    } else {
        'ORDER-DELAY-E2E-RECONCILIATION'
    }
    docker compose exec -T postgres psql -U postgres -d customer_agent -v ON_ERROR_STOP=1 -c "
        insert into synthetic_order (
          order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
          paid, cancelled, fully_refunded, existing_compensation, policy_version,
          available_compensation_amount
        )
        select '$orderReference', customer_id, paid_amount, currency, delay_hours, delay_seconds,
          paid, cancelled, fully_refunded, existing_compensation, policy_version,
          available_compensation_amount
        from synthetic_order
        where order_reference = '$fixtureTemplate'"
    $env:VITE_E2E_SCENARIO = $Scenario
    $env:VITE_E2E_ORDER_REFERENCE = $orderReference
    $env:EXECUTOR_SIMULATION_SCENARIO = $SimulatorScenario
    $env:EXECUTOR_POLL_DELAY = $PollDelay
    docker compose up --detach --force-recreate compensation-executor
    docker compose --profile smoke run --rm --entrypoint npm frontend-acceptance `
        test -- src/Issue29.e2e.test.tsx
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #29 React 全栈验收失败 ($Scenario)，退出码: $LASTEXITCODE"
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
        for ($aggregation = 0; $aggregation -lt 5; $aggregation++) {
            $attemptEvidence = docker compose exec -T postgres psql -U postgres -d customer_agent -Atc "
                select count(distinct a.started_at) || ':' ||
                  string_agg(a.outcome, ',' order by a.started_at,
                    case a.attempt_type when 'EXECUTION' then 0 when 'RECONCILIATION' then 1 end)
                from compensation_execution_attempt a
                join compensation_execution e on e.id = a.execution_id
                where e.order_reference = '$orderReference'"
            if ($attemptEvidence -ne '1:UNKNOWN,FOUND') {
                throw "Issue #29 同时钟对账尝试链不稳定（第 $($aggregation + 1) 次聚合）: $attemptEvidence"
            }
        }
    }
    docker compose stop compensation-executor
}

Invoke-Issue29Scenario 'normal' 'SUCCESS' '0.25'
Invoke-Issue29Scenario 'reconciliation' 'AFTER_EFFECT_RESPONSE_LOST' '2'
$preservedIssue29EvidenceDigest = Get-Issue29EvidenceDigest
$preservedPriorIssue29EvidenceDigest = Get-Issue29EvidenceDigest $issue29RunNamespace
if ($preservedPriorIssue29EvidenceDigest -ne $priorIssue29EvidenceDigest) {
    throw "Issue #29 前次同卷证据发生变化: $priorIssue29EvidenceDigest -> $preservedPriorIssue29EvidenceDigest"
}
Write-Host "Issue #29 前次同卷证据保持不变: $priorIssue29EvidenceDigest；本轮后总摘要: $preservedIssue29EvidenceDigest"
Remove-Item Env:VITE_E2E_SCENARIO -ErrorAction SilentlyContinue
Remove-Item Env:VITE_E2E_ORDER_REFERENCE -ErrorAction SilentlyContinue
Remove-Item Env:EXECUTOR_SIMULATION_SCENARIO -ErrorAction SilentlyContinue
Remove-Item Env:EXECUTOR_POLL_DELAY -ErrorAction SilentlyContinue

if ($Reset) {
    docker compose --profile smoke run --rm integration-smoke
    if ($LASTEXITCODE -ne 0) {
        throw "集成 smoke 失败，退出码: $LASTEXITCODE"
    }

    $hadDemoFixedInstant = Test-Path Env:DEMO_FIXED_INSTANT
    $priorDemoFixedInstant = $env:DEMO_FIXED_INSTANT
    try {
        docker compose exec -T postgres psql -U postgres -d customer_agent `
            -f /smoke/approval_queue_time_setup.sql
        $env:DEMO_FIXED_INSTANT = ''
        docker compose up --detach --force-recreate --wait backend
        docker compose --profile smoke run --rm approval-queue-time-smoke
        if ($LASTEXITCODE -ne 0) {
            throw "审批队列权威时间锁等待 smoke 失败，退出码: $LASTEXITCODE"
        }
    } finally {
        try {
            docker compose exec -T postgres psql -U postgres -d customer_agent `
                -f /smoke/approval_queue_time_cleanup.sql
        } finally {
            if ($hadDemoFixedInstant) {
                $env:DEMO_FIXED_INSTANT = $priorDemoFixedInstant
            } else {
                Remove-Item Env:DEMO_FIXED_INSTANT -ErrorAction SilentlyContinue
            }
            docker compose up --detach --force-recreate --wait backend
        }
    }
} else {
    Write-Host 'PERSISTENT_RERUN_SUITE 排除项：要求空 fixture 的广域 integration-smoke；原因是它跨历史功能复用固定业务 fixture，不能安全清库，正式门禁由 -Reset 覆盖。'
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

$status = Invoke-RestMethod -Uri "http://127.0.0.1:$frontendPort/api/system/status"
if ($status.status -ne 'UP') {
    throw "Spring 状态投影不是 UP: $($status | ConvertTo-Json -Compress)"
}

$sensitiveRules = Get-Content "$PSScriptRoot/../frontend/src/sensitive-content-patterns.json" -Raw | ConvertFrom-Json
$frontendSensitivePattern = (@($sensitiveRules.contentPatterns) + @($sensitiveRules.internalAddressPatterns)) -join '|'
docker run --rm --entrypoint sh "customer-agent/frontend:$imageTag" -c "
    grep -R -q '/support' /usr/share/nginx/html &&
    grep -R -q '/approver' /usr/share/nginx/html &&
    ! grep -R -E '$frontendSensitivePattern' /usr/share/nginx/html"

$runtimeLogs = docker compose logs --no-color
& "$PSScriptRoot/assert-runtime-log-policy.ps1" -LogLines $runtimeLogs
Write-Host '运行日志应用正文敏感内容扫描通过（Compose 元数据已剥离）'

$versions = [ordered]@{
    node = (docker run --rm node:24.19.0-bookworm-slim node --version 2>$null)
    java = (docker run --rm --entrypoint sh "customer-agent/backend:$imageTag" -c 'java -version 2>&1 | head -n 1')
    python = (docker run --rm --entrypoint python "customer-agent/agent:$imageTag" --version 2>&1)
    postgres = (docker compose exec -T postgres postgres --version)
}

[pscustomobject]@{
    suite = $suiteName
    status = $status.status
    spring = $status.services.spring
    database = $status.services.database
    agent = $status.services.agent
    versions = $versions
} | ConvertTo-Json -Depth 4
