$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runId = 'issue190-development-c3-20260831a'
$ledgerPath = 'D:/customer-agent/.local/issue190-sufficiency/cost-ledger.json'
if ((Get-FileHash -LiteralPath $ledgerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '0800a19d7111b2838d7131734a62cdf6a64be48dcac1fc8c9b44d3435b9646f0') { throw 'SHARED_LEDGER_CHANGED; no API call' }
$evidence = Join-Path $root ".local/gate-evidence/$runId"
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
# 只将既有项目凭据载入本进程,不打印内容或复制到证据。
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    $entry = Get-Content -LiteralPath 'D:/customer-agent/.env' | Where-Object { $_ -match '^DEEPSEEK_API_KEY=' } | Select-Object -First 1
    if ($entry) { $env:DEEPSEEK_API_KEY = $entry.Substring($entry.IndexOf('=') + 1).Trim().Trim('"').Trim("'") }
}
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) { throw 'MISSING_API_KEY；未调用供应商。' }
$env:KNOWLEDGE_SUFFICIENCY_EXPERIMENT = 'issue-190-versioned-synthetic-development'
$env:DEEPSEEK_REAL_EVALUATION = ''
$env:UV_OFFLINE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$observedDate = '2026-08-31' # 本次已由官方页面人工核对的UTC日期
$metadata = [ordered]@{
    run_id=$runId; head_sha=(git -C $root rev-parse HEAD).Trim();
    base_sha=(git -C $root rev-parse origin/main).Trim();
    started_at=[DateTimeOffset]::Now.ToString('o');
    pricing_and_context_verified_utc_date=$observedDate;
    pricing_source='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/';
    endpoint='https://api.deepseek.com/responses'; requested_model='deepseek-v4-flash';
    budget_micro_cny=6000000; maximum_attempts_per_query=1; maximum_api_requests=72; seen_development_only=$true; prior_settled_upper_micro_cny=195579;
    input_cny_per_million_upper=3; output_cny_per_million_upper=9;
    fixed_context_upper=1048576; max_output_tokens=256
}
$watch = [Diagnostics.Stopwatch]::StartNew()
try {
    & "$root/scripts/knowledge-sufficiency.ps1" -DevelopmentVersion c3 -RunId $runId -PricingAndContextVerifiedDate $observedDate -Uv "$root/.local/tools/uv/uv.exe" *> "$evidence/launch.log"
    $metadata.exit_code = $LASTEXITCODE
} catch {
    $metadata.exit_code = 1
    $metadata.launch_error_type = $_.Exception.GetType().Name
} finally {
    $metadata.elapsed_seconds = $watch.Elapsed.TotalSeconds
    $metadata.finished_at = [DateTimeOffset]::Now.ToString('o')
    $metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$evidence/launch.json" -Encoding utf8
    $env:DEEPSEEK_API_KEY = ''
}
Get-Content -LiteralPath "$evidence/launch.log" -Tail 12
exit $metadata.exit_code




