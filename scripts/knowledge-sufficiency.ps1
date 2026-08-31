param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$PricingAndContextVerifiedDate,
    [string]$Uv = 'uv',
    [switch]$DiagnoseFifthOnce,
    [switch]$DiagnoseRemainingOnce,
    [switch]$CV2WholeOnce,
    [string]$DevelopmentVersion
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/test-gate-lock.ps1"
if (([int]$DiagnoseFifthOnce.IsPresent + [int]$DiagnoseRemainingOnce.IsPresent + [int]$CV2WholeOnce.IsPresent + [int][bool]$DevelopmentVersion) -gt 1) { throw '实验阶段互斥，不能合并运行。' }
if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') { throw '需要唯一RunId。' }
if ($env:CUSTOMER_AGENT_TEST_GATE_IDENTITY) { throw '真实合成实验不能使用自定义锁身份。' }
$expectedOptIn = if ($DiagnoseFifthOnce) { 'issue-190-fifth-request-diagnostic-once' } else { 'issue-190-synthetic-sufficiency-c-once' }
if ($DiagnoseRemainingOnce) { $expectedOptIn = 'issue-190-remaining67-diagnostic-once' }
if ($CV2WholeOnce) { $expectedOptIn = 'issue-190-c-v2-whole-development-once' }
if ($DevelopmentVersion) { $expectedOptIn = 'issue-190-versioned-synthetic-development' }
if ($env:KNOWLEDGE_SUFFICIENCY_EXPERIMENT -ne $expectedOptIn) {
    throw '需要明确实验opt-in；本脚本不代表协调已放行运行窗口。'
}
# 此日期是操作者已重核官方高峰价格和上下文上限的确认,不能由脚本自动补今天。
if ($PricingAndContextVerifiedDate -ne [DateTime]::UtcNow.ToString('yyyy-MM-dd')) {
    throw '运行前须重核官方价格与上下文仍符合已提交配置，使用UTC核对日期。'
}
$root = Split-Path -Parent $PSScriptRoot
$headSha = git -C $root rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw '无法读取源码SHA。' }
$baseSha = git -C $root rev-parse origin/main
if ($LASTEXITCODE -ne 0) { throw '无法读取main基线。' }
if (git -C $root status --porcelain) { throw 'C回放要求先提交唯一合同及源码。' }
$commandType = if ($DiagnoseFifthOnce) { 'sufficiency-c-fifth-diagnostic' } else { 'sufficiency-c-development' }
if ($DiagnoseRemainingOnce) { $commandType = 'sufficiency-c-remaining67-diagnostic' }
if ($CV2WholeOnce) { $commandType = 'sufficiency-c-v2-whole-development' }
if ($DevelopmentVersion) { $commandType = "sufficiency-development-$DevelopmentVersion" }
$holder = Enter-TestGateLock -Issue 190 -RunId $RunId -CommandType $commandType -HeadSha $headSha -BaseSha $baseSha
try {
    $reportName = if ($DiagnoseFifthOnce) { 'sufficiency-fifth-diagnostic.json' } else { 'sufficiency-development.json' }
    if ($DiagnoseRemainingOnce) { $reportName = 'sufficiency-remaining-diagnostic.json' }
    if ($CV2WholeOnce) { $reportName = 'sufficiency-c-v2-development.json' }
    if ($DevelopmentVersion) { $reportName = 'sufficiency-development.json' }
    $output = Join-Path $root ".local/gate-evidence/$RunId/$reportName"
    [string[]]$modeArgs = @()
    if ($DiagnoseFifthOnce) { $modeArgs += '--diagnose-fifth-once' }
    if ($DiagnoseRemainingOnce) { $modeArgs += '--diagnose-remaining-once' }
    if ($CV2WholeOnce) { $modeArgs += '--c-v2-whole-once' }
    if ($DevelopmentVersion) { $modeArgs += @('--development-version', $DevelopmentVersion) }
    Push-Location (Join-Path $root 'agent')
    try {
        # 不在实验入口隐式安装/生成依赖;准备依赖需另外受锁且获运行授权。
        & $Uv run --frozen --no-sync python -m baseline_agent.knowledge_sufficiency_run `
            --run-id $RunId --head-sha $headSha --base-sha $baseSha `
            --pricing-and-context-verified-date $PricingAndContextVerifiedDate --output $output @modeArgs
        if ($LASTEXITCODE -ne 0) { throw "C阶段停止，证据：$output；不重试、不切方法、不进入留出或冻结门。" }
        Write-Host "实验记录：$output；不是产品或质量门PASS；单次诊断不恢复开发回放。"
    } finally { Pop-Location }
} finally {
    Exit-TestGateLock $holder
}
