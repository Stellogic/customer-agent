param(
    [switch]$ConfirmProviderSpend,
    [string]$RunId = 'issue215-intake-diagnostic-04',
    [string]$EnvFile = 'D:\customer-agent\.env',
    [string]$LedgerPath = 'D:\customer-agent\.local\issue190-sufficiency\cost-ledger.json',
    [string]$KnowledgeModelPath = 'C:\Users\lizhuo\.codex\worktrees\745a\customer-agent\.local\models\bge-small-zh-v1.5'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
. "$PSScriptRoot/gate-images.ps1"
. "$PSScriptRoot/gate-resources.ps1"
if (-not $ConfirmProviderSpend) { throw '须显式授权本次真实复现。' }
if ($RunId -ne 'issue215-intake-diagnostic-04') { throw 'RunId 与本次诊断冻结不符。' }
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$project = "customer-agent-$RunId"
$tag = "gate-$RunId"
$evidence = Join-Path $repo ".local/gate-evidence/$RunId"
$override = Join-Path $evidence 'compose.override.yaml'
if (Test-Path -LiteralPath $evidence) { throw '本轮证据目录已存在，禁止重用 RunId。' }
foreach ($path in @($EnvFile, $LedgerPath, $KnowledgeModelPath)) {
    if (-not (Test-Path -LiteralPath $path)) { throw '诊断输入缺失。' }
}
function Read-FrozenLedger {
    $value = Get-Content -LiteralPath $LedgerPath -Raw | ConvertFrom-Json
    $settled = [long]$value.prior_paid_micro_cny + [long](($value.attempts | Where-Object status -eq 'SETTLED' | Measure-Object charged_upper_micro_cny -Sum).Sum)
    $pending = @($value.attempts | Where-Object status -eq 'PENDING')
    if ($value.schema -ne 'issue190-sufficiency-cost-v1' -or $settled -ne 3810222 -or
        $pending.Count -ne 9 -or [long](($pending | Measure-Object reserved_micro_cny -Sum).Sum) -ne 2700000 -or
        $value.phases.PSObject.Properties.Name -contains $RunId) { throw '共享账本与冻结起点不符。' }
    if ($settled + 2700000 + 100000 -gt 8000000) { throw '本轮预算不足。' }
    return $value
}
$null = Read-FrozenLedger
$gate = Enter-TestGateLock -Issue 215 -RunId $RunId -CommandType 'deepseek-diagnostic' `
    -BaseSha (git rev-parse origin/main).Trim() -HeadSha (git rev-parse HEAD).Trim() -ComposeProject $project -ImageTag $tag
$built = $false
$started = $false
$reserved = $false
$outcome = 'NOT_RUN'
$cleanupPassed = $false
function Invoke-DiagnosticCompose([object[]]$Arguments) {
    & docker compose -f (Join-Path $repo 'compose.yaml') -f $override -p $project @Arguments
    if ($LASTEXITCODE -ne 0) { throw '诊断 Compose 操作失败。' }
}
try {
    $null = Read-FrozenLedger
    New-Item -ItemType Directory -Path $evidence | Out-Null
    $fingerprint = Get-GateSourceFingerprint -RepoRoot $repo
    [ordered]@{
        schema = 'issue215-diagnostic-freeze-v1'; runId = $RunId
        base = (git rev-parse origin/main).Trim(); head = (git rev-parse HEAD).Trim()
        uncommittedChanges = (@(git status --porcelain).Count -gt 0); sourceFingerprint = $fingerprint
        model = 'deepseek-v4-flash'; mode = 'deepseek-formal-intake-v3'
        promptVersion = 'intake-v3'; promptSource = 'working-tree:agent/src/baseline_agent/deepseek_intake_model.py'
        schemaNames = @('customer_intake_issue_assessments', 'customer_intake_clarification', 'customer_intake_understanding')
        schemaSource = 'working-tree:agent/src/baseline_agent/deepseek_intake_model.py'
        logicalCallLimit = 4; providerAttemptLimit = 4; maxOutputTokensPerAttempt = 600
        retries = 0; reservedMicroCny = 100000; priorSettledMicroCny = 3810222
        priorPendingMicroCny = 2700000; projectLimitMicroCny = 8000000
        finalConfirmation = $true; releaseAcceptance = $false
        downstreamSubmissionPollDelayMs = 3600000
        downstreamInvestigationBudgetMicros = 0
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $evidence 'freeze.json') -Encoding utf8
    @'
services:
  backend:
    environment:
      BASELINE_AGENT_SUBMISSION_POLL_DELAY: '3600000'
  agent-server:
    environment:
      INVESTIGATION_MODEL_MODE: deepseek-formal
      AGENT_INVESTIGATION_MAX_COST_MICROS: '0'
'@ | Set-Content -LiteralPath $override -Encoding utf8
    $env:COMPOSE_DISABLE_ENV_FILE = 'true'
    $env:CUSTOMER_AGENT_IMAGE_TAG = $tag
    $env:CUSTOMER_AGENT_FRONTEND_PORT = '0'
    $env:KNOWLEDGE_MODEL_HOST_PATH = $KnowledgeModelPath
    $env:DEEPSEEK_MODEL = 'deepseek-v4-flash'
    $env:AGENT_INVESTIGATION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_INVESTIGATION_ACTION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE = 'deepseek-formal'
    $env:AGENT_INVESTIGATION_SHADOW_MODE = 'disabled'
    Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '启动前'
    $built = $true
    Invoke-GateImageBuilds -RepoRoot $repo -RunId $RunId -SourceFingerprint $fingerprint | Out-Null
    $keyLines = @(Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^\s*DEEPSEEK_API_KEY\s*=' })
    if ($keyLines.Count -ne 1) { throw '模型凭据配置数量不符。' }
    $env:DEEPSEEK_API_KEY = ($keyLines[0] -replace '^\s*DEEPSEEK_API_KEY\s*=\s*', '').Trim()
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) { throw '模型凭据为空。' }
    $config = (Invoke-DiagnosticCompose @('config', '--format', 'json') | Out-String) | ConvertFrom-Json
    Assert-ComposeResourcesOwned -ProjectName $project -EffectiveConfig $config
    if ($config.services.'agent-server'.environment.INVESTIGATION_MODEL_MODE -ne 'deepseek-formal' -or
        $config.services.'agent-server'.environment.DEEPSEEK_MODEL -ne 'deepseek-v4-flash' -or
        $config.services.'agent-server'.environment.AGENT_INVESTIGATION_MAX_COST_MICROS -ne '0' -or
        $config.services.backend.environment.BASELINE_AGENT_SUBMISSION_POLL_DELAY -ne '3600000') { throw '有效模型配置与冻结不符。' }
    $config = $null
    $ledger = Read-FrozenLedger
    $ledger.phases | Add-Member -NotePropertyName $RunId -NotePropertyValue ([pscustomobject]@{status='RUNNING';dataset='issue215-intake-diagnostic-v3'})
    $ledger.attempts += [pscustomobject]@{phase=$RunId;query_id='issue215-browser-intake';status='PENDING';reserved_micro_cny=100000}
    $ledger | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $LedgerPath -Encoding utf8
    $reserved = $true
    $started = $true
    Invoke-DiagnosticCompose @('up', '--detach', '--no-build', '--wait') | Out-Host
    Invoke-DiagnosticCompose @('--profile', 'smoke', 'up', '--detach', '--no-build', '--no-deps', '--wait', 'browser-frontend') | Out-Host
    # 浏览器错误输出可能含页面上下文，只在内存中接收，不导出。
    $native = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $browserOutput = & docker compose -f (Join-Path $repo 'compose.yaml') -f $override -p $project --profile smoke run --rm --no-deps `
            --volume "${evidence}:/diagnostics" --env ISSUE215_DIAGNOSTIC_ENABLED=1 --env ISSUE215_DIAGNOSTIC_DIR=/diagnostics `
            browser-acceptance --workers=1 --max-failures=1 --trace off e2e/issue215.intake-diagnostic.spec.ts 2>&1
        $browserExit = $LASTEXITCODE
    } finally { $PSNativeCommandUseErrorActionPreference = $native }
    $browserOutput = $null
    $outcome = if ($browserExit -eq 0) { 'INTAKE_CREATION_PASS' } else { 'DIAGNOSTIC_FAILED' }
    $logs = @(Invoke-DiagnosticCompose @('logs', '--no-color', 'backend'))
    $counts = & "$PSScriptRoot/issue215-intake-failure-summary.ps1" -LogLines $logs
    $states = @($logs | ForEach-Object {
        if ($_ -match 'INTAKE_STATE_REJECTED intent=(UNDERSTANDING|CONFIRM) status=(READY_TO_CONFIRM|NEEDS_CLARIFICATION|CONFIRMED) issues=(\d+) pending=(\d+) currentIssues=(\d+) currentPending=(\d+)') {
            [ordered]@{intent=$Matches[1];status=$Matches[2];issues=[int]$Matches[3];pending=[int]$Matches[4];currentIssues=[int]$Matches[5];currentPending=[int]$Matches[6]}
        }
    })
    $logs = $null
    [ordered]@{outcome=$outcome;browserExit=$browserExit;failureCounts=$counts;rejectedStates=$states;providerUsage=$null} |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence 'failure-classification.json') -Encoding utf8
} finally {
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    try {
        if ($started) {
            Invoke-DiagnosticCompose @('--profile', 'smoke', 'down', '--volumes', '--remove-orphans') | Out-Host
            Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '清理后'
        }
        if ($built) { Remove-GateImages -RunId $RunId; Assert-GateImagesAbsent -RunId $RunId }
        $cleanupPassed = $true
    } finally {
        if ($reserved) {
            $ledger = Get-Content -LiteralPath $LedgerPath -Raw | ConvertFrom-Json
            $ledger.phases.$RunId.status = "${outcome}_PENDING_USAGE"
            $ledger | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $LedgerPath -Encoding utf8
        }
        Exit-TestGateLock $gate
        if ($cleanupPassed) { Write-Host 'LOCK_RELEASED' }
    }
}
Write-Host "ISSUE215_DIAGNOSTIC_RESULT=$outcome"
