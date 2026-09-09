#Requires -Version 7.0
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot '.env'

Push-Location $repoRoot
try {
    if (-not (Test-Path -LiteralPath $envFile)) {
        Copy-Item -LiteralPath (Join-Path $repoRoot '.env.example') -Destination $envFile
        Write-Host '已从 .env.example 创建 .env。'
    }

    $modelPath = [string]$env:KNOWLEDGE_MODEL_HOST_PATH
    if ([string]::IsNullOrWhiteSpace($modelPath)) {
        $configuredPath = Get-Content -LiteralPath $envFile |
            Where-Object { $_ -match '^\s*KNOWLEDGE_MODEL_HOST_PATH\s*=' } |
            Select-Object -Last 1
        if ($configuredPath) {
            $modelPath = ($configuredPath -split '=', 2)[1].Trim().Trim('"').Trim("'")
        }
    }
    if ([string]::IsNullOrWhiteSpace($modelPath)) {
        $modelPath = Join-Path $repoRoot '.local/models/bge-small-zh-v1.5'
    } elseif (-not [System.IO.Path]::IsPathRooted($modelPath)) {
        $modelPath = Join-Path $repoRoot $modelPath
    }

    if (-not (Test-Path -LiteralPath $modelPath -PathType Container)) {
        Write-Host '首次启动：正在准备本地知识检索模型。'
        & "$PSScriptRoot/prepare-knowledge-model.ps1" -ModelDirectory $modelPath
        if ($LASTEXITCODE -ne 0) { throw '本地知识检索模型准备失败。' }
    }

    . "$PSScriptRoot/test-gate-lock.ps1"
    $startupLock = Enter-TestGateLock -Issue manual -CommandType local-start
    try {
        docker compose up --detach --wait postgres
        if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 启动失败。' }

        docker compose exec -T postgres psql -U postgres -d customer_agent -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/002-knowledge-vector.sql
        if ($LASTEXITCODE -ne 0) { throw 'vector 扩展准备失败；数据已保留。' }

        docker compose up --detach --build --wait
        if ($LASTEXITCODE -ne 0) { throw '应用启动失败。' }
    } finally {
        Exit-TestGateLock $startupLock
    }

    Write-Host '项目已启动：http://127.0.0.1:4180'
} finally {
    Pop-Location
}
