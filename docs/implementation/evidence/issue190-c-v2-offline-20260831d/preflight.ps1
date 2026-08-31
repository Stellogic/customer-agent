param([Parameter(Mandatory)][string]$RunId, [switch]$FinalOnly)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. "$root/scripts/test-gate-lock.ps1"
$head = (git -C $root rev-parse HEAD).Trim()
$base = (git -C $root rev-parse origin/main).Trim()
$holder = Enter-TestGateLock -Issue 190 -RunId $RunId -CommandType 'c-v2-offline-preflight' -HeadSha $head -BaseSha $base
$out = Join-Path $root ".local/gate-evidence/$RunId"
$watch = [Diagnostics.Stopwatch]::StartNew()
$record = [ordered]@{
    run_id=$RunId; head_sha=$head; base_sha=$base; status='ERROR'; phases=@();
    paid_model_calls=0; paid_model_cost_cny=0; development_replay_run=$false;
    holdout_or_frozen_evaluation_run=$false
    ledger_sha_before=(Get-FileHash 'D:/customer-agent/.local/issue190-sufficiency/cost-ledger.json' -Algorithm SHA256).Hash
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
    $env:UV_OFFLINE = '1'
    $env:PYTHONPATH = "$root/agent/src"
    Push-Location "$root/agent"
    try {
        $python = "$root/agent/.venv/Scripts/python.exe"
        $env:SSL_CERT_FILE = "$root/agent/.venv/Lib/site-packages/certifi/cacert.pem"
        $env:NO_PROXY = '*'
        if (-not $FinalOnly) {
            Invoke-Phase 'materialize-requests' $python @("$root/scripts/materialize-knowledge-sufficiency-v2.py", '--output', "$out/requests.json")
            $manifest = "$root/agent/src/baseline_agent/knowledge_sufficiency_v2/requests.json"
            Copy-Item -LiteralPath "$out/requests.json" -Destination $manifest
            $hash = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLower()
            $runner = "$root/agent/src/baseline_agent/knowledge_sufficiency_run.py"
            $text = [IO.File]::ReadAllText($runner).Replace('PENDING_REQUESTS',$hash)
            [IO.File]::WriteAllText($runner,$text,[Text.UTF8Encoding]::new($false))
            Invoke-Phase 'format' "$root/agent/.venv/Scripts/ruff.exe" @('format','src/baseline_agent/knowledge_sufficiency.py','src/baseline_agent/knowledge_sufficiency_run.py','tests/test_knowledge_sufficiency_v2.py','../scripts/materialize-knowledge-sufficiency-v2.py')
        } else {
            Invoke-Phase 'entry-argv' 'pwsh' @('-NoProfile','-File',"$root/scripts/test-knowledge-sufficiency-entry.ps1",'-RunId',$RunId,'-OutputDirectory',"$out/argv",'-Uv',"$root/.local/tools/uv/uv.exe")
        }
        Invoke-Phase 'focused' $python @('-m','pytest','-q','tests/test_knowledge_sufficiency_v2.py',"--junitxml=$out/focused.xml")
        Invoke-Phase 'lint' "$root/agent/.venv/Scripts/ruff.exe" @('check','.', '../scripts/materialize-knowledge-sufficiency-v2.py')
        Invoke-Phase 'format-check' "$root/agent/.venv/Scripts/ruff.exe" @('format','--check','.', '../scripts/materialize-knowledge-sufficiency-v2.py')
        Invoke-Phase 'types' "$root/agent/.venv/Scripts/pyright.exe" @('--pythonpath', $python)
        Invoke-Phase 'offline-component' $python @('-m','pytest','-q','tests/test_knowledge_sufficiency.py','tests/test_knowledge_sufficiency_v2.py','tests/test_deepseek_offline_contract.py',"--junitxml=$out/offline-component.xml")
        $record.ledger_sha_after = (Get-FileHash 'D:/customer-agent/.local/issue190-sufficiency/cost-ledger.json' -Algorithm SHA256).Hash
        if ($record.ledger_sha_before -ne $record.ledger_sha_after) { throw 'Shared ledger changed' }
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




