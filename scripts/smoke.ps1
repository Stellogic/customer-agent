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

docker build --target test --tag customer-agent/backend-test:issue12 backend
docker build --target test --tag customer-agent/agent-test:issue12 agent
docker compose up --detach --build --force-recreate --wait
docker compose --profile smoke run --rm integration-smoke

$status = Invoke-RestMethod -Uri 'http://127.0.0.1:4180/api/system/status'
if ($status.status -ne 'UP') {
    throw "Spring 状态投影不是 UP: $($status | ConvertTo-Json -Compress)"
}

docker run --rm --entrypoint sh customer-agent/frontend:issue12 -c "if grep -R -E 'agent-server|agent:2024|local-(spring|agent|executor|postgres)|postgresql://' /usr/share/nginx/html; then exit 1; fi"

$versions = [ordered]@{
    node = (docker run --rm node:24.19.0-bookworm-slim node --version 2>$null)
    java = (docker run --rm --entrypoint sh customer-agent/backend:issue12 -c 'java -version 2>&1 | head -n 1')
    python = (docker run --rm --entrypoint python customer-agent/agent:issue12 --version 2>&1)
    postgres = (docker compose exec -T postgres postgres --version)
}

[pscustomobject]@{
    status = $status.status
    spring = $status.services.spring
    database = $status.services.database
    agent = $status.services.agent
    versions = $versions
} | ConvertTo-Json -Depth 4
