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

    $defaultModelPath = Join-Path $repoRoot '.local/models/bge-small-zh-v1.5'
    $modelPath = [string]$env:KNOWLEDGE_MODEL_HOST_PATH
    $modelPathConfigured = -not [string]::IsNullOrWhiteSpace($modelPath)
    if (-not $modelPathConfigured) {
        $configuredPath = Get-Content -LiteralPath $envFile |
            Where-Object { $_ -match '^\s*KNOWLEDGE_MODEL_HOST_PATH\s*=' } |
            Select-Object -Last 1
        if ($configuredPath) {
            $modelPath = ($configuredPath -split '=', 2)[1].Trim().Trim('"').Trim("'")
            $modelPathConfigured = -not [string]::IsNullOrWhiteSpace($modelPath)
        }
    }
    if ($modelPathConfigured -and -not [System.IO.Path]::IsPathRooted($modelPath)) {
        $modelPath = Join-Path $repoRoot $modelPath
    }

    $modelReady = $false
    if ($modelPathConfigured) {
        if (Test-Path -LiteralPath $modelPath -PathType Container) {
            try {
                & "$PSScriptRoot/prepare-knowledge-model.ps1" -ModelDirectory $modelPath -VerifyOnly
                $modelReady = $true
            } catch {
                Write-Host '已配置的模型目录未通过校验，将重新准备。'
            }
        }
    } else {
        $modelCandidates = @($defaultModelPath)
        $codexWorktrees = Join-Path $env:USERPROFILE '.codex/worktrees'
        if (Test-Path -LiteralPath $codexWorktrees -PathType Container) {
            $modelCandidates += Get-ChildItem -LiteralPath $codexWorktrees -Directory | ForEach-Object {
                Join-Path $_.FullName 'customer-agent/.local/models/bge-small-zh-v1.5'
            }
        }

        foreach ($candidate in ($modelCandidates | Select-Object -Unique)) {
            if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
                continue
            }
            try {
                & "$PSScriptRoot/prepare-knowledge-model.ps1" -ModelDirectory $candidate -VerifyOnly
                $modelPath = $candidate
                $modelReady = $true
                if ($candidate -ne $defaultModelPath) {
                    Write-Host "复用本机已有 BGE 模型：$candidate"
                }
                break
            } catch {
                continue
            }
        }
    }
    if (-not $modelReady) {
        if (-not $modelPathConfigured) {
            $modelPath = $defaultModelPath
        }
        Write-Host '首次启动：正在准备本地知识检索模型。'
        & "$PSScriptRoot/prepare-knowledge-model.ps1" -ModelDirectory $modelPath
        if ($LASTEXITCODE -ne 0) { throw '本地知识检索模型准备失败。' }
    }
    $env:KNOWLEDGE_MODEL_HOST_PATH = $modelPath

    . "$PSScriptRoot/test-gate-lock.ps1"
    $startupLock = Enter-TestGateLock -Issue manual -CommandType local-start -ComposeProject 'customer-agent-baseline'
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
