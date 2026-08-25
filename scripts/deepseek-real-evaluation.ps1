param(
    [switch]$ConfirmProviderSpend
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

if (-not $ConfirmProviderSpend) {
    throw '必须显式传入 -ConfirmProviderSpend 才能运行 Issue #125 真实 DeepSeek 评测。'
}
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    throw '当前进程缺少 DEEPSEEK_API_KEY；脚本不会读取 .env 文件。'
}
if ($env:DEEPSEEK_MODEL -ne 'deepseek-v4-flash') {
    throw 'DEEPSEEK_MODEL 必须显式设置为 deepseek-v4-flash；不会自动切换模型。'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$imageTag = if ($env:CUSTOMER_AGENT_IMAGE_TAG) { $env:CUSTOMER_AGENT_IMAGE_TAG } else { 'local' }
$image = "customer-agent/agent:$imageTag"

docker build --target runtime --tag $image agent
if ($LASTEXITCODE -ne 0) {
    throw 'Agent runtime image build failed'
}

docker run --rm `
    --env DEEPSEEK_API_KEY `
    --env DEEPSEEK_MODEL `
    --env DEEPSEEK_REAL_EVALUATION=issue-125-authorized-real-deepseek-evaluation `
    --entrypoint python `
    $image `
    -m baseline_agent.deepseek_real_evaluation
if ($LASTEXITCODE -ne 0) {
    throw "Issue #125 真实评测未通过（退出码 $LASTEXITCODE）；不得进入真实 shadow。"
}
