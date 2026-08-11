param(
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$imageTag = if ($env:CUSTOMER_AGENT_IMAGE_TAG) { $env:CUSTOMER_AGENT_IMAGE_TAG } else { 'issue24' }
$env:CUSTOMER_AGENT_IMAGE_TAG = $imageTag

if ($Reset) {
    docker compose down --volumes --remove-orphans
}

docker build --build-arg "GRADLE_OPTS=$($env:CUSTOMER_AGENT_GRADLE_OPTS)" --target test --tag "customer-agent/backend-test:$imageTag" backend
docker build --target test --tag "customer-agent/agent-test:$imageTag" agent
docker build --target test --tag "customer-agent/frontend-test:$imageTag" frontend
docker compose up --detach --build --force-recreate --wait
docker compose exec -T agent-server sh -c 'test -z "${EXECUTOR_MACHINE_TOKEN+x}"'
docker compose exec -T compensation-executor sh -c 'test -z "${AGENT_MACHINE_TOKEN+x}"'

$migrationHistory = docker compose exec -T postgres psql -U postgres -d customer_agent -Atc "select version || ':' || success from flyway_schema_history order by installed_rank"
if (($migrationHistory -join ',') -ne '1:true,2:true,3:true,4:true,5:true,6:true,7:true,8:true,9:true,10:true,11:true,12:true,13:true') {
    throw "Spring Flyway 迁移历史不完整: $($migrationHistory -join ',')"
}

docker compose stop compensation-executor
docker compose --profile smoke run --rm integration-smoke
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

$status = Invoke-RestMethod -Uri 'http://127.0.0.1:4180/api/system/status'
if ($status.status -ne 'UP') {
    throw "Spring 状态投影不是 UP: $($status | ConvertTo-Json -Compress)"
}

docker run --rm --entrypoint sh "customer-agent/frontend:$imageTag" -c "if grep -R -E 'agent-server|agent:2024|local-(spring|agent|executor|postgres)|postgresql://' /usr/share/nginx/html; then exit 1; fi"

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
