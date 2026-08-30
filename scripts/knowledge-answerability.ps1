param(
    [Parameter(Mandatory)][ValidateSet('prepare', 'collect', 'fit', 'audit')][string]$Phase,
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$HoldoutSeal,
    [ValidateSet('training', 'calibration', 'holdout')][string]$Split,
    [string]$Dataset,
    [string]$TrainingReport,
    [string]$CalibrationReport,
    [string]$SafetyReport,
    [string]$Observations,
    [string]$FitReport,
    [string]$BaseUrl = 'http://localhost:8080',
    [string]$Uv = 'uv'
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/test-gate-lock.ps1"
if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') { throw '需要唯一RunId。' }
$root = Split-Path -Parent $PSScriptRoot
$holder = Enter-TestGateLock -Issue 190 -RunId $RunId -CommandType "answerability-$Phase"
try {
    $headSha = git -C $root rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw '无法读取源码SHA。' }
    $baseSha = git -C $root rev-parse origin/main
    if ($LASTEXITCODE -ne 0) { throw '无法读取main基线。' }
    if (git -C $root status --porcelain) { throw '独立开发运行要求先提交源码与数据。' }
    if ($Split -eq 'holdout' -or $Phase -eq 'audit') {
        if (-not $FitReport) { throw '打开留出前必须指定已提交的拟合报告。' }
        $fitPath = (Resolve-Path -LiteralPath $FitReport).Path
        $fitRelative = [System.IO.Path]::GetRelativePath($root, $fitPath)
        if ($fitRelative.StartsWith('..') -or [System.IO.Path]::IsPathRooted($fitRelative)) {
            throw '拟合报告须先归档并提交到本仓库。'
        }
        git -C $root ls-files --error-unmatch -- $fitRelative | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '拟合报告未纳入已提交源码，不能读取留出。' }
        git -C $root ls-files --error-unmatch -- 'backend/src/main/resources/knowledge-answerability-logistic.json' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '产品策略未提交。' }
    }
    $outputRoot = Join-Path $root ".local/gate-evidence/$RunId"
    $pythonArgs = @($Phase, '--output', (Join-Path $outputRoot "answerability-$Phase.json"),
        '--holdout-seal', (Resolve-Path -LiteralPath $HoldoutSeal).Path,
        '--run-id', $RunId, '--head-sha', $headSha, '--base-sha', $baseSha, '--base-url', $BaseUrl)
    foreach ($item in @(
        @('dataset', $Dataset), @('training-report', $TrainingReport),
        @('calibration-report', $CalibrationReport), @('safety-report', $SafetyReport),
        @('observations', $Observations), @('fit-report', $FitReport)
    )) {
        if ($item[1]) { $pythonArgs += @("--$($item[0])", (Resolve-Path -LiteralPath $item[1]).Path) }
    }
    if ($Split) { $pythonArgs += @('--split', $Split) }
    if ($Phase -eq 'prepare') { $pythonArgs += @('--corpus-output', (Join-Path $outputRoot "corpus-$Split")) }
    Push-Location (Join-Path $root 'agent')
    try {
        & $Uv run --frozen --group calibration python -m baseline_agent.knowledge_answerability_run @pythonArgs
        if ($LASTEXITCODE -ne 0) { throw "阶段失败/不可行，保留$outputRoot；不得自动重拟合、换方法或进入冻结门。" }
        Write-Host "阶段已记录：$outputRoot；不是冻结质量或完整门禁PASS。"
    } finally { Pop-Location }
} finally {
    Exit-TestGateLock $holder
}
