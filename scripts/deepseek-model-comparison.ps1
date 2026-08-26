param(
    [switch]$ConfirmProviderSpend,
    [string]$ReportPath = 'docs/delivery/issue-130-model-comparison.json'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

if (-not $ConfirmProviderSpend) {
    throw '必须显式传入 -ConfirmProviderSpend 才能运行 Issue #130 真实模型比较。'
}

$envFile = 'D:\customer-agent\.env'
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw '未找到授权的 D:\customer-agent\.env；已停止且不会从其他位置读取密钥。'
}

$keyLines = @(
    Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^\s*DEEPSEEK_API_KEY\s*=' }
)
if ($keyLines.Count -ne 1) {
    throw '授权 .env 中必须恰好存在一个 DEEPSEEK_API_KEY；已停止。'
}
$providerKey = ($keyLines[0] -replace '^\s*DEEPSEEK_API_KEY\s*=\s*', '').Trim()
if (
    $providerKey.Length -ge 2 -and
    (($providerKey.StartsWith('"') -and $providerKey.EndsWith('"')) -or
    ($providerKey.StartsWith("'") -and $providerKey.EndsWith("'")))
) {
    $providerKey = $providerKey.Substring(1, $providerKey.Length - 2)
}
if ([string]::IsNullOrWhiteSpace($providerKey)) {
    throw '授权 .env 中的 DEEPSEEK_API_KEY 为空；已停止。'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$resolvedReportPath = Join-Path $repoRoot $ReportPath
$reportDirectory = Split-Path -Parent $resolvedReportPath
if (-not (Test-Path -LiteralPath $reportDirectory -PathType Container)) {
    throw "报告目录不存在：$reportDirectory"
}

$imageTag = if ($env:CUSTOMER_AGENT_IMAGE_TAG) {
    $env:CUSTOMER_AGENT_IMAGE_TAG
} else {
    'issue130-model-comparison'
}
$image = "customer-agent/agent:$imageTag"

try {
    $env:DEEPSEEK_API_KEY = $providerKey
    docker build --pull=false --target runtime --tag $image agent
    if ($LASTEXITCODE -ne 0) {
        throw 'Agent runtime image build failed；尚未调用真实模型。'
    }

    $output = docker run --rm `
        --env DEEPSEEK_API_KEY `
        --env DEEPSEEK_MODEL_COMPARISON=issue-130-authorized-flash-pro-comparison `
        --entrypoint python `
        $image `
        -m baseline_agent.deepseek_model_comparison
    $exitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    $providerKey = $null
}

$reportText = ($output -join [Environment]::NewLine).Trim()
try {
    $report = $reportText | ConvertFrom-Json -Depth 100
} catch {
    throw '真实模型比较未返回合法脱敏 JSON 报告；已停止。'
}
if ($report.schemaVersion -ne 'issue-130-deepseek-model-comparison-v1') {
    throw '真实模型比较报告 schema 不匹配；已停止。'
}
if ($report.spend.actualCny -gt 6 -or -not $report.spend.withinBudget) {
    throw '真实模型比较报告显示费用超过 6 元人民币；已停止。'
}

$reportText | Set-Content -LiteralPath $resolvedReportPath -Encoding utf8
if ($exitCode -ne 0 -or $null -ne $report.blockedReason) {
    throw "Issue #130 真实模型比较触发首错即停：$($report.blockedReason)"
}

Write-Output $reportText
