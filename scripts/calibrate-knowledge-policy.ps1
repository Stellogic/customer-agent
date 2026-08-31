param(
    [Parameter(Mandatory)][string]$RunId,
    [string]$Uv = 'uv',
    [string]$ModelDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) '.local/models/bge-small-zh-v1.5')
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/test-gate-lock.ps1"
if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') { throw '独立校准需要明确的运行标识。' }
$root = Split-Path -Parent $PSScriptRoot
$holder = Enter-TestGateLock -Issue 190 -RunId $RunId -CommandType 'knowledge-calibration'
$previousModel = $env:KNOWLEDGE_MODEL_PATH
try {
    $env:KNOWLEDGE_MODEL_PATH = (Resolve-Path -LiteralPath $ModelDirectory).Path
    $headSha = git -C $root rev-parse HEAD
    $baseSha = git -C $root rev-parse origin/main
    $dirtyArgs = if (git -C $root status --porcelain) { @('--working-tree-dirty') } else { @() }
    $output = Join-Path $root ".local/gate-evidence/$RunId/knowledge-calibration-v1.json"
    Push-Location (Join-Path $root 'agent')
    try {
        & $Uv run --frozen python -m baseline_agent.knowledge_calibration `
            --output $output --run-id $RunId --head-sha $headSha --base-sha $baseSha @dirtyArgs
        if ($LASTEXITCODE -ne 0) { throw "独立校准失败；保留报告 $output，不生成替代门槛。" }
        Write-Host "独立校准已测量（不是冻结质量PASS）；请审阅报告：$output"
    } finally { Pop-Location }
} finally {
    $env:KNOWLEDGE_MODEL_PATH = $previousModel
    Exit-TestGateLock $holder
}
