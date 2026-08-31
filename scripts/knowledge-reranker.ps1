param(
    [Parameter(Mandatory)][ValidateSet('preflight', 'prepare', 'development')][string]$Phase,
    [Parameter(Mandatory)][string]$RunId,
    [string]$Uv = 'uv',
    [string]$ModelDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) '.local/models/bge-reranker-base')
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/test-gate-lock.ps1"
if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') { throw '需要唯一RunId。' }
$root = Split-Path -Parent $PSScriptRoot
$headSha = git -C $root rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw '无法读取源码SHA。' }
$baseSha = git -C $root rev-parse origin/main
if ($LASTEXITCODE -ne 0) { throw '无法读取main基线。' }
if (git -C $root status --porcelain) { throw '须先提交固定方法、数据引用和源码。' }
$commonDir = git -C $root rev-parse --path-format=absolute --git-common-dir
if ($LASTEXITCODE -ne 0) { throw '无法确定共享实验记录目录。' }
$output = if ($Phase -eq 'development') {
    # 所有worktree共用一个阶段记录；不提供续跑/强制覆盖开关。
    Join-Path (Split-Path -Parent $commonDir.Trim()) '.local/issue190-reranker-v1/development.json'
} else {
    Join-Path $root ".local/gate-evidence/$RunId/reranker-$Phase.json"
}
$holder = Enter-TestGateLock -Issue 190 -RunId $RunId -CommandType "reranker-$Phase" -HeadSha $headSha -BaseSha $baseSha
try {
    if (Test-Path -LiteralPath $output) { throw '本阶段记录已存在，不重启或覆盖。' }
    if ($Phase -eq 'development') {
        $env:HF_HUB_OFFLINE = '1'
        $env:TRANSFORMERS_OFFLINE = '1'
    }
    $env:UV_OFFLINE = '1'
    [string[]]$runnerArgs = @(
        $Phase, '--run-id', $RunId, '--head-sha', $headSha.Trim(), '--base-sha', $baseSha.Trim(),
        '--model-directory', [System.IO.Path]::GetFullPath($ModelDirectory), '--output', $output
    )
    Push-Location (Join-Path $root 'agent')
    try {
        & $Uv run --frozen --no-sync python -m baseline_agent.knowledge_reranker_run @runnerArgs
        if ($LASTEXITCODE -ne 0) { throw "阶段停止，保留$output；不重选或自动重跑。" }
        Write-Host "阶段记录：$output；不代表独立质量或产品交付PASS。"
    } finally { Pop-Location }
} finally { Exit-TestGateLock $holder }
