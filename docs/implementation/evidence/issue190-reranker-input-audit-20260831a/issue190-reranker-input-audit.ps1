$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$runId='issue190-reranker-input-audit-20260831a'
. "$root/scripts/test-gate-lock.ps1"
$head=(git -C $root rev-parse HEAD).Trim()
$base=(git -C $root rev-parse origin/main).Trim()
$holder=Enter-TestGateLock -Issue 190 -RunId $runId -CommandType 'reranker-input-audit' -HeadSha $head -BaseSha $base
$out=Join-Path $root ".local/gate-evidence/$runId"
$record=[ordered]@{run_id=$runId;head_sha=$head;base_sha=$base;status='ERROR';model_scoring_run=$false;paid_model_calls=0}
$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $env:HF_HUB_OFFLINE='1'
    $env:TRANSFORMERS_OFFLINE='1'
    Push-Location "$root/agent"
    try {
        & "$root/agent/.venv/Scripts/python.exe" "$root/.local/issue190-reranker-input-audit.py" "$root/.local/models/bge-reranker-base" "$out/input-audit.json" *> "$out/audit.log"
        $record.exit_code=$LASTEXITCODE
        Get-Content -LiteralPath "$out/audit.log" -Tail 12
        if ($LASTEXITCODE -ne 0) { throw '输入审计失败，不重评分。' }
        $record.status='PASS'
    } finally { Pop-Location }
} catch { $record.failure=$_.Exception.Message } finally {
    $record.elapsed_seconds=$watch.Elapsed.TotalSeconds
    if (Test-Path -LiteralPath $out) { $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$out/launch.json" -Encoding utf8 }
    Exit-TestGateLock $holder
}
if ($record.status -ne 'PASS') { exit 1 }
