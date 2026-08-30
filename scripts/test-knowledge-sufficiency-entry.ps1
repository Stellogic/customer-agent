param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [string]$Uv = 'uv'
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited

# 调用实际pwsh→uv→Python入口；故意不给key，让argparse后在任何账本/HTTP前停止。
$env:DEEPSEEK_API_KEY = ''
$env:DEEPSEEK_REAL_EVALUATION = ''
$env:UV_OFFLINE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
foreach ($mode in @('development', 'diagnostic', 'remaining', 'c-v2')) {
    $env:KNOWLEDGE_SUFFICIENCY_EXPERIMENT = if ($mode -eq 'diagnostic') {
        'issue-190-fifth-request-diagnostic-once'
    } else { 'issue-190-synthetic-sufficiency-c-once' }
    if ($mode -eq 'remaining') {
        $env:KNOWLEDGE_SUFFICIENCY_EXPERIMENT = 'issue-190-remaining67-diagnostic-once'
    }
    if ($mode -eq 'c-v2') {
        $env:KNOWLEDGE_SUFFICIENCY_EXPERIMENT = 'issue-190-c-v2-whole-development-once'
    }
    [string[]]$entryArgs = @(
        '-NoProfile', '-File', "$PSScriptRoot/knowledge-sufficiency.ps1",
        '-RunId', "$RunId-$mode", '-Uv', $Uv,
        # 仅满足离线argv测试的日期参数，不代表一次真实调用价格审批。
        '-PricingAndContextVerifiedDate', [DateTime]::UtcNow.ToString('yyyy-MM-dd')
    )
    if ($mode -eq 'diagnostic') { $entryArgs += '-DiagnoseFifthOnce' }
    if ($mode -eq 'remaining') { $entryArgs += '-DiagnoseRemainingOnce' }
    if ($mode -eq 'c-v2') { $entryArgs += '-CV2WholeOnce' }
    $log = Join-Path $OutputDirectory "$mode.log"
    & pwsh @entryArgs *> $log
    $exitCode = $LASTEXITCODE
    $observed = Get-Content -LiteralPath $log -Raw
    if ($exitCode -eq 0 -or $observed -notmatch 'SufficiencyBlocked: MISSING_API_KEY' -or
        $observed -match 'unrecognized arguments') {
        throw "实际入口argv回归失败：$mode；见$log"
    }
    if (Test-Path -LiteralPath "$root/.local/gate-evidence/$RunId-$mode") {
        throw '无key时不应进入报告/账本或HTTP阶段。'
    }
    Write-Host "PASS: $mode 实际入口参数解析通过，MISSING_API_KEY前置停止；API=0。"
}
$env:KNOWLEDGE_SUFFICIENCY_EXPERIMENT = ''
