$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$runId='issue190-reranker-prepare-20260831b'
$head=(git -C $root rev-parse HEAD).Trim()
$base=(git -C $root rev-parse origin/main).Trim()
if (git -C $root status --porcelain) { throw '要求固定源码已提交。' }
. "$root/scripts/test-gate-lock.ps1"
$holder=Enter-TestGateLock -Issue 190 -RunId $runId -CommandType 'reranker-prepare-resume' -HeadSha $head -BaseSha $base
$out=Join-Path $root ".local/gate-evidence/$runId"
$model=Join-Path $root '.local/models/bge-reranker-base'
$record=[ordered]@{run_id=$runId;head_sha=$head;base_sha=$base;status='ERROR';files=@();paid_model_calls=0;paid_model_cost_cny=0;model_loaded=$false;development_started=$false}
$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $partial=Join-Path $model 'model.safetensors'
    $preserved=Join-Path $root '.local/gate-evidence/issue190-reranker-prepare-20260831a/model.safetensors.partial'
    if (Test-Path -LiteralPath $preserved) { throw '不覆盖原始部分文件。' }
    Copy-Item -LiteralPath $partial -Destination $preserved
    $record.preserved_partial_bytes=(Get-Item -LiteralPath $preserved).Length
    $fixed=Get-Content -LiteralPath "$root/agent/src/baseline_agent/knowledge_reranker_v1.json" -Raw | ConvertFrom-Json
    $record.protocol=$fixed
    foreach ($file in $fixed.files.PSObject.Properties) {
        $target=Join-Path $model $file.Name
        $before=if (Test-Path -LiteralPath $target) { (Get-Item -LiteralPath $target).Length } else { 0 }
        if ($before -eq $file.Value.size_bytes) {
            $record.files += [ordered]@{file=$file.Name;bytes_before=$before;download='PRESENT_PENDING_FINAL_HASH'}
            continue
        }
        $url="https://huggingface.co/$($fixed.model)/resolve/$($fixed.revision)/$($file.Name)"
        & C:/Windows/System32/curl.exe --silent --show-error --fail --location --proto '=https' --proto-redir '=https' --noproxy '*' --continue-at - --retry 0 --connect-timeout 30 --max-time 1200 --speed-time 120 --speed-limit 1024 --output $target --write-out 'http_code=%{http_code} downloaded_bytes=%{size_download} elapsed_seconds=%{time_total}\n' $url *> "$out/$($file.Name).download.log"
        $exitCode=$LASTEXITCODE
        Get-Content -LiteralPath "$out/$($file.Name).download.log" -Tail 8
        $record.files += [ordered]@{file=$file.Name;bytes_before=$before;exit_code=$exitCode;bytes_after=(Get-Item -LiteralPath $target).Length}
        if ($exitCode -ne 0) { throw "同一官方源续传失败: $($file.Name); 不再重试。" }
    }
    Push-Location "$root/agent"
    try {
        & "$root/agent/.venv/Scripts/python.exe" -c 'from pathlib import Path; import sys; from baseline_agent.knowledge_reranker import verify_directory; verify_directory(Path(sys.argv[1])); print("FIXED_MODEL_VERIFIED")' $model *> "$out/verify.log"
        if ($LASTEXITCODE -ne 0) { throw '固定5文件完整校验失败，不加载。' }
    } finally { Pop-Location }
    $record.status='PREPARED'
} catch {
    $record.failure=$_.Exception.Message
} finally {
    $record.elapsed_seconds=$watch.Elapsed.TotalSeconds
    if (Test-Path -LiteralPath $out) { $record | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath "$out/prepare.json" -Encoding utf8 }
    Exit-TestGateLock $holder
}
if ($record.status -ne 'PREPARED') { exit 1 }
