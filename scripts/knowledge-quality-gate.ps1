param([string]$RunId = $env:CUSTOMER_AGENT_GATE_RUN_ID)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited
if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') { throw '质量门需要明确的隔离运行标识。' }
$outputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) ".local/gate-evidence/$RunId"
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$containerOutput = "/tmp/knowledge-$RunId.json"
$root = Split-Path -Parent $PSScriptRoot
$headSha = git -C $root rev-parse HEAD
$baseSha = git -C $root rev-parse origin/main
$dirtyArgs = if (git -C $root status --porcelain) { @('--working-tree-dirty') } else { @() }
$nativePreference = $PSNativeCommandUseErrorActionPreference
$PSNativeCommandUseErrorActionPreference = $false
try {
    docker compose exec -T `
        -e SPRING_FIXTURE_DATABASE_URI=postgresql://spring_fixture:local-spring-fixture@postgres:5432/customer_agent `
        agent-server python -m baseline_agent.knowledge_evaluation --output $containerOutput `
        --run-id $RunId --head-sha $headSha --base-sha $baseSha `
        --protocol rag-layered-v2-retrieval @dirtyArgs
    $evaluationExit = $LASTEXITCODE
} finally { $PSNativeCommandUseErrorActionPreference = $nativePreference }
docker compose cp "agent-server:$containerOutput" (Join-Path $outputDirectory 'rag-layered-v2-retrieval-result.json')
if ($LASTEXITCODE -ne 0) { throw '冻结质量门未能保存证据，不允许交付。' }
if ($evaluationExit -ne 0) {
    throw "冻结质量门失败或运行错误，证据已保存到 $outputDirectory。#167/#169/#170 保持阻塞；不得改题或降阈值。"
}
Write-Host "rag-layered-v2 检索层 PASS（回答质量未评估）；证据：$outputDirectory/rag-layered-v2-retrieval-result.json"
