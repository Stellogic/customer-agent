$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$runId='issue190-reranker-development-20260831a'
$head=(git -C $root rev-parse HEAD).Trim()
$base=(git -C $root rev-parse origin/main).Trim()
if (git -C $root status --porcelain) { throw '要求源码已提交。' }
$common=(git -C $root rev-parse --path-format=absolute --git-common-dir).Trim()
if ($LASTEXITCODE -ne 0) { throw '无法定位共享阶段。' }
$shared=Join-Path (Split-Path -Parent $common) '.local/issue190-reranker-v1/development.json'
. "$root/scripts/test-gate-lock.ps1"
$holder=Enter-TestGateLock -Issue 190 -RunId $runId -CommandType 'reranker-development' -HeadSha $head -BaseSha $base
$out=Join-Path $root ".local/gate-evidence/$runId"
$model=Join-Path $root '.local/models/bge-reranker-base'
$record=[ordered]@{run_id=$runId;head_sha=$head;base_sha=$base;status='ERROR';manual_download_evidence='USER_PROVIDED_MODEL_VERIFIED_OUTPUT';model_reverification='NOT_RUN';development_started=$false;paid_model_calls=0;paid_model_cost_cny=0}
$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $record.shared_record_existed=Test-Path -LiteralPath $shared
    if ($record.shared_record_existed) { throw '共享development记录已存在，不覆盖或重开。' }
    $env:DEEPSEEK_API_KEY=''
    $env:DEEPSEEK_REAL_EVALUATION=''
    $env:HF_HUB_OFFLINE='1'
    $env:TRANSFORMERS_OFFLINE='1'
    $env:UV_OFFLINE='1'
    Push-Location "$root/agent"
    try {
        & "$root/agent/.venv/Scripts/python.exe" -c 'from pathlib import Path; import sys; from baseline_agent.knowledge_reranker import verify_directory; verify_directory(Path(sys.argv[1])); print("FIXED_FIVE_FILES_VERIFIED")' $model *> "$out/model-verification.log"
        if ($LASTEXITCODE -ne 0) { throw '固定5文件复核失败，不启动评分。' }
        $record.model_reverification='PASS'
        $record.development_started=$true
        [string[]]$runnerArgs=@('development','--model-directory',$model,'--output',$shared,'--run-id',$runId,'--head-sha',$head,'--base-sha',$base)
        & "$root/.local/tools/uv/uv.exe" run --frozen --no-sync python -m baseline_agent.knowledge_reranker_run @runnerArgs *> "$out/development.log"
        $record.exit_code=$LASTEXITCODE
        Get-Content -LiteralPath "$out/development.log" -Tail 30
        if (Test-Path -LiteralPath $shared) {
            Copy-Item -LiteralPath $shared -Destination "$out/development.json"
            $result=Get-Content -LiteralPath $shared -Raw | ConvertFrom-Json
            $record.status=$result.status
            $record.completed_queries=$result.completed_queries
        }
    } finally { Pop-Location }
} catch {
    $record.failure=$_.Exception.Message
} finally {
    $record.elapsed_seconds=$watch.Elapsed.TotalSeconds
    if (Test-Path -LiteralPath $out) { $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$out/launch.json" -Encoding utf8 }
    Exit-TestGateLock $holder
}
if ($record.status -ne 'DEVELOPMENT_FEASIBLE') { exit 1 }
