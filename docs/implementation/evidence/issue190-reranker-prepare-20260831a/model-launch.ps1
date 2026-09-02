param([Parameter(Mandatory)][ValidateSet('prepare','development')][string]$Phase,[Parameter(Mandatory)][string]$RunId)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$out=Join-Path $root ".local/gate-evidence/$RunId"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$record=[ordered]@{run_id=$RunId;phase=$Phase;head_sha=(git -C $root rev-parse HEAD).Trim();base_sha=(git -C $root rev-parse origin/main).Trim();status='ERROR';paid_model_calls=0;paid_model_cost_cny=0}
$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    $env:DEEPSEEK_API_KEY=''
    $env:DEEPSEEK_REAL_EVALUATION=''
    $env:SSL_CERT_FILE="$root/agent/.venv/Lib/site-packages/certifi/cacert.pem"
    $env:NO_PROXY='*'
    & pwsh -NoProfile -File "$root/scripts/knowledge-reranker.ps1" -Phase $Phase -RunId $RunId -Uv "$root/.local/tools/uv/uv.exe" *> "$out/launch.log"
    $record.exit_code=$LASTEXITCODE
    Get-Content -LiteralPath "$out/launch.log" -Tail 35
    if ($LASTEXITCODE -ne 0) { throw '阶段停止，不自动重试。' }
    $record.status='PROCESS_SUCCEEDED'
} catch {
    $record.failure=$_.Exception.Message
} finally {
    $record.elapsed_seconds=$watch.Elapsed.TotalSeconds
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$out/launch.json" -Encoding utf8
}
if ($record.status -ne 'PROCESS_SUCCEEDED') { exit 1 }
