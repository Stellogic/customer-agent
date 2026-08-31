param([Parameter(Mandatory)][string]$RunId)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. "$root/scripts/test-gate-lock.ps1"
$head = (git -C $root rev-parse HEAD).Trim()
$base = (git -C $root rev-parse origin/main).Trim()
$holder = Enter-TestGateLock -Issue 190 -RunId $RunId -CommandType 'reranker-offline' -HeadSha $head -BaseSha $base
$out = Join-Path $root ".local/gate-evidence/$RunId"
$watch = [Diagnostics.Stopwatch]::StartNew()
$record = [ordered]@{
    run_id=$RunId; head_sha=$head; base_sha=$base; status='ERROR'; phases=@();
    paid_model_calls=0; paid_model_cost_cny=0; model_downloaded=$false; model_loaded=$false;
    development_scoring_run=$false; holdout_or_frozen_evaluation_run=$false
}
function Invoke-Phase([string]$Name, [string]$Exe, [string[]]$Arguments) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    & $Exe @Arguments *> (Join-Path $out "$Name.log")
    $code = $LASTEXITCODE
    $record.phases += [ordered]@{name=$Name; exit_code=$code; elapsed_seconds=$timer.Elapsed.TotalSeconds}
    Get-Content -LiteralPath (Join-Path $out "$Name.log") -Tail 25
    if ($code -ne 0) { throw "$Name failed: $code" }
}
try {
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $env:DEEPSEEK_API_KEY = ''
    $env:DEEPSEEK_REAL_EVALUATION = ''
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    $env:UV_OFFLINE = '1'
    Push-Location "$root/agent"
    try {
        $python = "$root/agent/.venv/Scripts/python.exe"
        $targets = @('src/baseline_agent/knowledge_reranker.py','src/baseline_agent/knowledge_reranker_run.py','tests/test_knowledge_reranker.py')
        Invoke-Phase 'focused' $python @('-m','pytest','-q','tests/test_knowledge_reranker.py',"--junitxml=$out/focused.xml")
        Invoke-Phase 'lint' "$root/agent/.venv/Scripts/ruff.exe" (@('check') + $targets)
        Invoke-Phase 'format' "$root/agent/.venv/Scripts/ruff.exe" (@('format') + $targets)
        Invoke-Phase 'format-check' "$root/agent/.venv/Scripts/ruff.exe" (@('format','--check') + $targets)
        Invoke-Phase 'types' "$root/agent/.venv/Scripts/pyright.exe" @('--pythonpath',$python)
        Invoke-Phase 'related-components' $python @('-m','pytest','-q','tests/test_knowledge_reranker.py','tests/test_knowledge_answerability.py','tests/test_knowledge_sufficiency.py',"--junitxml=$out/components.xml")
        $record.status='PASS'
    } finally { Pop-Location }
} catch {
    $record.failure=$_.Exception.Message
} finally {
    $record.elapsed_seconds=$watch.Elapsed.TotalSeconds
    $record.working_tree_changed=[bool](git -C $root status --porcelain)
    if (Test-Path -LiteralPath $out) {
        $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$out/phase.json" -Encoding utf8
    }
    Exit-TestGateLock $holder
}
if ($record.status -ne 'PASS') { exit 1 }
