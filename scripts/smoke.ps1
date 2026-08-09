param(
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ($Reset) {
    docker compose down --volumes --remove-orphans
}

docker build --build-arg "GRADLE_OPTS=$($env:CUSTOMER_AGENT_GRADLE_OPTS)" --target test --tag customer-agent/backend-test:issue13 backend
docker build --target test --tag customer-agent/agent-test:issue13 agent
docker build --target test --tag customer-agent/frontend-test:issue13 frontend
docker compose up --detach --build --force-recreate --wait
docker compose exec -T agent-server sh -c 'test -z "${EXECUTOR_MACHINE_TOKEN+x}"'

$migrationHistory = docker compose exec -T postgres psql -U postgres -d customer_agent -Atc "select version || ':' || success from flyway_schema_history order by installed_rank"
if (($migrationHistory -join ',') -ne '1:true,2:true') {
    throw "Spring Flyway 迁移历史不完整: $($migrationHistory -join ',')"
}

docker compose --profile smoke run --rm integration-smoke
docker compose --profile smoke run --rm frontend-acceptance

$status = Invoke-RestMethod -Uri 'http://127.0.0.1:4180/api/system/status'
if ($status.status -ne 'UP') {
    throw "Spring 状态投影不是 UP: $($status | ConvertTo-Json -Compress)"
}

docker run --rm --entrypoint sh customer-agent/frontend:issue13 -c "if grep -R -E 'agent-server|agent:2024|local-(spring|agent|executor|postgres)|postgresql://' /usr/share/nginx/html; then exit 1; fi"

$versions = [ordered]@{
    node = (docker run --rm node:24.19.0-bookworm-slim node --version 2>$null)
    java = (docker run --rm --entrypoint sh customer-agent/backend:issue13 -c 'java -version 2>&1 | head -n 1')
    python = (docker run --rm --entrypoint python customer-agent/agent:issue13 --version 2>&1)
    postgres = (docker compose exec -T postgres postgres --version)
}

[pscustomobject]@{
    status = $status.status
    spring = $status.services.spring
    database = $status.services.database
    agent = $status.services.agent
    versions = $versions
} | ConvertTo-Json -Depth 4
