param(
    [switch]$SkipBuild,
    [string]$RunId,
    [string]$SourceFingerprint
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. "$PSScriptRoot/gate-images.ps1"
. "$PSScriptRoot/gate-resources.ps1"
. "$PSScriptRoot/browser-acceptance-plan.ps1"

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "issue80-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
}
if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') {
    throw 'Issue #80 RunId 只能包含小写字母、数字和连字符，且至少 8 位。'
}
if ([string]::IsNullOrWhiteSpace($SourceFingerprint)) {
    $SourceFingerprint = Get-GateSourceFingerprint -RepoRoot $repoRoot
}

$imageTag = "gate-$RunId"
$projectName = "customer-agent-issue80-$RunId"
$portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$portProbe.Start()
$frontendPort = $portProbe.LocalEndpoint.Port
$portProbe.Stop()
$env:CUSTOMER_AGENT_IMAGE_TAG = $imageTag
$env:CUSTOMER_AGENT_FRONTEND_PORT = [string]$frontendPort
$env:SESSION_COOKIE_SECURE = 'true'
$ownsImages = -not $SkipBuild

$plan = Import-PowerShellDataFile "$PSScriptRoot/browser-acceptance-plan.psd1"
$discovered = @(
    Get-ChildItem -LiteralPath (Join-Path $repoRoot 'frontend/e2e') -File -Filter '*.spec.ts' |
        ForEach-Object { "e2e/$($_.Name)" }
)
Assert-BrowserAcceptancePlan `
    -DiscoveredFiles $discovered `
    -ParallelSafe $plan.ParallelSafe `
    -Serial $plan.Serial `
    -Excluded $plan.Excluded.Keys
Assert-ParallelSafeBrowserTests -RepoRoot $repoRoot -Files $plan.ParallelSafe

$effectiveConfigJson = docker compose --project-name $projectName --profile smoke config --format json
$effectiveConfig = $effectiveConfigJson | ConvertFrom-Json
$configuredPort = [string]$effectiveConfig.services.frontend.ports[0].published
$configuredImages = @($effectiveConfig.services.PSObject.Properties.Value.image)
$expectedImages = @(
    Get-GateImageSpecifications -ImageTag $imageTag |
        Where-Object { $_.Image -notmatch 'customer-agent/(backend|agent)-test:' } |
        ForEach-Object Image
)
if (
    $effectiveConfig.name -ne $projectName -or
    $configuredPort -ne [string]$frontendPort -or
    @($expectedImages | Where-Object { $configuredImages -notcontains $_ }).Count -ne 0
) {
    throw "Issue #80 effective config 未应用唯一 project/端口/镜像标签: project=$projectName port=$frontendPort tag=$imageTag"
}
Assert-ComposeResourcesOwned -ProjectName $projectName -EffectiveConfig $effectiveConfig
Assert-ComposeProjectResourcesEmpty -ProjectName $projectName -Phase '在启动前'

if ($SkipBuild) {
    Assert-GateImages -RunId $RunId -SourceFingerprint $SourceFingerprint
} else {
    Invoke-GateImageBuilds -RepoRoot $repoRoot -RunId $RunId -SourceFingerprint $SourceFingerprint | Out-Null
}
Write-Host "Issue #80 effective config: project=$projectName port=$frontendPort tag=$imageTag fingerprint=$SourceFingerprint preflight resources=0"

$playwrightRunner = {
    param($files, $workers, $attempt)
    docker compose --project-name $projectName --profile smoke run --rm --no-deps browser-acceptance `
        "--workers=$workers" @files | Out-Host
    return $LASTEXITCODE
}

try {
    docker compose --project-name $projectName up --detach --no-build --force-recreate --wait
    docker compose --project-name $projectName exec -T postgres `
        psql -U postgres -d customer_agent -f /acceptance/issue80-browser.sql
    docker compose --project-name $projectName --profile smoke up --detach --no-build --no-deps --wait browser-frontend

    Invoke-PlaywrightGroup -Files $plan.ParallelSafe -Workers 2 -RepeatCount 3 -Runner $playwrightRunner

    $regularSerial = @($plan.Serial | Where-Object {
        $_ -notin @('e2e/issue80.session-restart-expiry.spec.ts', 'e2e/issue173.auto-resolution-clock.spec.ts')
    })
    Invoke-PlaywrightGroup -Files $regularSerial -Workers 1 -Runner $playwrightRunner

    # #173 复用本次隔离栈推进业务时钟；恢复后继续原 #80 Session 阶段。
    & "$PSScriptRoot/issue173-clock-acceptance.ps1" -ProjectName $projectName

    $sessionFile = @('e2e/issue80.session-restart-expiry.spec.ts')
    $env:ISSUE80_SESSION_PHASE = 'restart-prepare'
    Invoke-PlaywrightGroup -Files $sessionFile -Workers 1 -Runner $playwrightRunner
    docker compose --project-name $projectName restart backend
    docker compose --project-name $projectName up --detach --no-deps --wait backend
    $env:ISSUE80_SESSION_PHASE = 'restart-verify'
    Invoke-PlaywrightGroup -Files $sessionFile -Workers 1 -Runner $playwrightRunner

    $env:CUSTOMER_AGENT_SESSION_TIMEOUT = '1m'
    docker compose --project-name $projectName up --detach --no-deps --force-recreate --wait backend
    $env:ISSUE80_SESSION_PHASE = 'expiry'
    Invoke-PlaywrightGroup -Files $sessionFile -Workers 1 -Runner $playwrightRunner
} finally {
    docker compose --project-name $projectName --profile smoke down --volumes --remove-orphans
    Assert-ComposeProjectResourcesEmpty -ProjectName $projectName -Phase '在清理后'
    if ($ownsImages) {
        Remove-GateImages -RunId $RunId
        Assert-GateImagesAbsent -RunId $RunId
    }
    Remove-Item Env:CUSTOMER_AGENT_IMAGE_TAG -ErrorAction SilentlyContinue
    Remove-Item Env:CUSTOMER_AGENT_FRONTEND_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:SESSION_COOKIE_SECURE -ErrorAction SilentlyContinue
    Remove-Item Env:CUSTOMER_AGENT_SESSION_TIMEOUT -ErrorAction SilentlyContinue
    Remove-Item Env:ISSUE80_SESSION_PHASE -ErrorAction SilentlyContinue
}

Write-Host "Issue #80 真实浏览器验收通过：parallel-safe=$($plan.ParallelSafe.Count) files x3 workers=2，serial=$($plan.Serial.Count) files workers=1；隔离容器、网络与卷已回读为空。"
