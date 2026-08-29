param(
    [ValidateSet("all", "backend", "agent", "frontend")]
    [string]$Component = "all",
    [switch]$SkipAcceptance,
    [string]$RunId,
    [string]$Issue = "manual"
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot/test-gate-lock.ps1"

$components = if ($Component -eq "all") { @("backend", "agent", "frontend") } else { @($Component) }
$runsFullAcceptance = -not $SkipAcceptance -and $Component -eq "all"
$repoRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($Issue)) {
    $Issue = "manual"
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $slug = if ($Issue -eq "manual") { "manual" } else { "issue$Issue" }
    $RunId = "$slug-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
}
if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') {
    throw 'RunId 只能包含小写字母、数字和连字符，且至少 8 位。'
}

$imageTag = $null
$projectName = $null
$baseSha = $null
$headSha = $null
$commandType = if ($runsFullAcceptance) { "full-check" } else { "check" }

if ($runsFullAcceptance) {
    $nativePref = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    git -C $repoRoot fetch origin main
    $fetchCode = $LASTEXITCODE
    $PSNativeCommandUseErrorActionPreference = $nativePref
    if ($fetchCode -ne 0) {
        throw '完整门禁开始前必须同步最新 origin/main。'
    }
    $baseSha = (git -C $repoRoot rev-parse origin/main).Trim()
    $headSha = (git -C $repoRoot rev-parse HEAD).Trim()
    $imageTag = "gate-$RunId"
    $projectName = "customer-agent-$imageTag"
}

$gateLock = Enter-TestGateLock `
    -Issue $Issue `
    -RunId $RunId `
    -CommandType $commandType `
    -BaseSha $baseSha `
    -HeadSha $headSha `
    -ComposeProject $projectName `
    -ImageTag $imageTag

try {
    if ($runsFullAcceptance) {
        . "$PSScriptRoot/gate-images.ps1"
        . "$PSScriptRoot/gate-resources.ps1"
        $portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
        $portProbe.Start()
        $frontendPort = [string]$portProbe.LocalEndpoint.Port
        $portProbe.Stop()
        $sourceFingerprint = Get-GateSourceFingerprint -RepoRoot $repoRoot
        $env:COMPOSE_PROJECT_NAME = $projectName
        $env:CUSTOMER_AGENT_IMAGE_TAG = $imageTag
        $env:CUSTOMER_AGENT_FRONTEND_PORT = $frontendPort
        $env:CUSTOMER_AGENT_GATE_RUN_ID = $RunId
        $env:CUSTOMER_AGENT_GATE_SOURCE_FINGERPRINT = $sourceFingerprint
        & "$PSScriptRoot/confirm-compose-reset-isolation.ps1"
    }

    & "$PSScriptRoot/test-test-gate-lock.ps1"
    & "$PSScriptRoot/test-runtime-log-policy.ps1"
    & "$PSScriptRoot/test-gradle-proxy.ps1"
    & "$PSScriptRoot/test-compose-network-policy.ps1"
    & "$PSScriptRoot/test-compose-reset-isolation.ps1"
    & "$PSScriptRoot/test-issue129-acceptance-contract.ps1"
    & "$PSScriptRoot/test-gate-image-reuse.ps1"
    & "$PSScriptRoot/test-gate-resources.ps1"
    & "$PSScriptRoot/test-browser-acceptance-plan.ps1"
    & "$PSScriptRoot/assert-deprecated-human-auth-contract.ps1"

    if (-not $runsFullAcceptance) {
        foreach ($current in $components) {
            docker build --target test --tag "customer-agent/${current}-test:local" $current
            if ($LASTEXITCODE -ne 0) {
                throw "$current canonical check failed"
            }
        }
    }

    if ($runsFullAcceptance) {
        $gateWatch = [System.Diagnostics.Stopwatch]::StartNew()
        $buildResults = @()
        $completed = $false
        try {
            $buildWatch = [System.Diagnostics.Stopwatch]::StartNew()
            $buildResults = @(Invoke-GateImageBuilds -RepoRoot $repoRoot -RunId $RunId -SourceFingerprint $sourceFingerprint)
            $buildWatch.Stop()

            $smokeWatch = [System.Diagnostics.Stopwatch]::StartNew()
            & "$PSScriptRoot/smoke.ps1" -Reset -SkipBuild
            if ($LASTEXITCODE -ne 0) {
                throw "smoke.ps1 失败，退出码 $LASTEXITCODE"
            }
            $smokeWatch.Stop()
            docker compose -p $projectName down --volumes --remove-orphans
            Assert-ComposeProjectResourcesEmpty -ProjectName $projectName -Phase '在 smoke 清理后'

            $browserWatch = [System.Diagnostics.Stopwatch]::StartNew()
            & "$PSScriptRoot/issue80-acceptance.ps1" -SkipBuild -RunId $RunId -SourceFingerprint $sourceFingerprint
            if ($LASTEXITCODE -ne 0) {
                throw "issue80-acceptance.ps1 失败，退出码 $LASTEXITCODE"
            }
            $browserWatch.Stop()
            $completed = $true
        } finally {
            docker compose -p $projectName down --volumes --remove-orphans 2>$null | Out-Null
            if ($completed) {
                Remove-GateImages -RunId $RunId
                Assert-GateImagesAbsent -RunId $RunId
            }
        }
        $gateWatch.Stop()
        $builtCount = @($buildResults | Where-Object { -not $_.Reused }).Count
        $reusedCount = @($buildResults | Where-Object Reused).Count
        $evidence = Save-TestGateFullGateEvidence -Holder $gateLock -BaseSha $baseSha -HeadSha $headSha
        Write-Host "Issue #$($evidence.issue) gate evidence: issue=$($evidence.issue) run=$($evidence.runId) baseSha=$($evidence.baseSha) headSha=$($evidence.headSha) fingerprint=$sourceFingerprint cache=shared-warm buildTargets=$builtCount reusedTargets=$reusedCount buildSeconds=$([math]::Round($buildWatch.Elapsed.TotalSeconds, 3)) smokeSeconds=$([math]::Round($smokeWatch.Elapsed.TotalSeconds, 3)) browserSeconds=$([math]::Round($browserWatch.Elapsed.TotalSeconds, 3)) totalSeconds=$([math]::Round($gateWatch.Elapsed.TotalSeconds, 3))"
    }
} finally {
    Exit-TestGateLock $gateLock
}
