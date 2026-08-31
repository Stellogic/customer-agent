param([Parameter(Mandatory)][string]$RunId)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$out=Join-Path $root ".local/gate-evidence/$RunId"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$head=(git -C $root rev-parse HEAD).Trim()
$base=(git -C $root rev-parse origin/main).Trim()
$modelPath=Join-Path $root '.local/models/offline preflight no weights'
$watch=[Diagnostics.Stopwatch]::StartNew()
$record=[ordered]@{run_id=$RunId;head_sha=$head;base_sha=$base;status='ERROR';model_loaded=$false;paid_model_calls=0;paid_model_cost_cny=0}
try {
    if (Test-Path -LiteralPath $modelPath) { throw '测试要求模型目录不存在，不删除或复用已有目录。' }
    & pwsh -NoProfile -File "$root/scripts/knowledge-reranker.ps1" -Phase preflight -RunId $RunId -Uv "$root/.local/tools/uv/uv.exe" -ModelDirectory $modelPath *> "$out/entry.log"
    $record.exit_code=$LASTEXITCODE
    Get-Content -LiteralPath "$out/entry.log" -Tail 25
    if ($LASTEXITCODE -ne 0) { throw '实际入口失败，保留原始输出。' }
    $result=Get-Content -LiteralPath "$out/reranker-preflight.json" -Raw | ConvertFrom-Json
    if ($result.status -ne 'PREFLIGHT_ONLY' -or $result.source_query_count -ne 72 -or $result.completed_queries -ne 0 -or $null -ne $result.metrics -or $result.model_directory -ne $modelPath -or $result.head_sha -ne $head -or $result.base_sha -ne $base) {
        throw '实际参数或仅预检报告不符。'
    }
    if (Test-Path -LiteralPath $modelPath) { throw '预检不应创建模型目录。' }
    $record.status='PASS'
} catch {
    $record.failure=$_.Exception.Message
} finally {
    $record.elapsed_seconds=$watch.Elapsed.TotalSeconds
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$out/entry-result.json" -Encoding utf8
}
if ($record.status -ne 'PASS') { exit 1 }
