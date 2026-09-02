param([string]$RunId = 'issue169-ledger-release-20260902c')
$ErrorActionPreference = 'Stop'
$repo169 = Split-Path -Parent $PSScriptRoot
Set-Location $repo169
. ./scripts/test-gate-lock.ps1
$holder169 = Enter-TestGateLock -Issue 169 -RunId $RunId -CommandType 'model-ledger-release' -BaseSha (git rev-parse origin/main) -HeadSha (git rev-parse HEAD)
try {
    & 'C:/Users/lizhuo/.codex/worktrees/808f/customer-agent/agent/.venv/Scripts/python.exe' `
        '.local/issue169_release_timeout.py' `
        'D:/customer-agent/.local/issue190-sufficiency/cost-ledger.json' `
        'docs/implementation/evidence/issue169-answer-20260902b/timeout-release.json'
    if ($LASTEXITCODE -ne 0) { throw "ledger release failed: $LASTEXITCODE" }
} finally {
    Exit-TestGateLock $holder169
    Write-Output "LOCK_RELEASED issue=169 run=$RunId"
    Show-TestGateStatus
}
