param([Parameter(Mandatory)][string]$RunId, [switch]$RedOnly)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. "$root/scripts/test-gate-lock.ps1"
$head = (git -C $root rev-parse HEAD).Trim()
$base = (git -C $root rev-parse origin/main).Trim()
$holder = Enter-TestGateLock -Issue 190 -RunId $RunId -CommandType 'c-offline-preflight' -HeadSha $head -BaseSha $base
$out = Join-Path $root ".local/gate-evidence/$RunId"
$watch = [Diagnostics.Stopwatch]::StartNew()
$record = [ordered]@{
    run_id=$RunId; head_sha=$head; base_sha=$base; status='ERROR'; phases=@();
    paid_model_calls=0; paid_model_cost_cny=0; development_replay_run=$false;
    holdout_or_frozen_evaluation_run=$false
}
function Invoke-Phase([string]$Name, [string]$Exe, [string[]]$Arguments) {
    $phaseWatch = [Diagnostics.Stopwatch]::StartNew()
    & $Exe @Arguments *> (Join-Path $out "$Name.log")
    $code = $LASTEXITCODE
    $record.phases += [ordered]@{name=$Name; exit_code=$code; elapsed_seconds=$phaseWatch.Elapsed.TotalSeconds}
    Get-Content -LiteralPath (Join-Path $out "$Name.log") -Tail 35
    if ($code -ne 0) { throw "$Name failed: $code" }
}
try {
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $env:DEEPSEEK_API_KEY = ''
    $env:KNOWLEDGE_SUFFICIENCY_EXPERIMENT = ''
    $env:DEEPSEEK_REAL_EVALUATION = ''
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    Push-Location "$root/agent"
    try {
        $python = "$root/agent/.venv/Scripts/python.exe"
        $env:SSL_CERT_FILE = "$root/agent/.venv/Lib/site-packages/certifi/cacert.pem"
        $env:NO_PROXY = '*'
        Invoke-Phase 'focused' $python @('-m','pytest','-q','tests/test_knowledge_sufficiency.py',"--junitxml=$out/focused.xml")
        if (-not $RedOnly) {
        Invoke-Phase 'format' "$root/agent/.venv/Scripts/ruff.exe" @('format','src/baseline_agent/knowledge_sufficiency.py','src/baseline_agent/knowledge_sufficiency_run.py','tests/test_knowledge_sufficiency.py')
        Invoke-Phase 'lint' "$root/agent/.venv/Scripts/ruff.exe" @('check','.')
        Invoke-Phase 'format-check' "$root/agent/.venv/Scripts/ruff.exe" @('format','--check','.')
        Invoke-Phase 'types' "$root/agent/.venv/Scripts/pyright.exe" @('--pythonpath', $python)
        Invoke-Phase 'offline-component' $python @('-m','pytest','-q','tests/test_knowledge_sufficiency.py','tests/test_deepseek_offline_contract.py',"--junitxml=$out/offline-component.xml")
        }
        $record.status = 'PASS'
    } finally { Pop-Location }
} catch {
    $record.failure = $_.Exception.Message
} finally {
    $record.elapsed_seconds = $watch.Elapsed.TotalSeconds
    $record.working_tree_changed = [bool](git -C $root status --porcelain)
    if (Test-Path -LiteralPath $out) {
        $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$out/phase.json" -Encoding utf8
    }
    Exit-TestGateLock $holder
}
if ($record.status -ne 'PASS') { exit 1 }

