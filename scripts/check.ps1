param(
    [ValidateSet("all", "backend", "agent", "frontend")]
    [string]$Component = "all",
    [switch]$SkipAcceptance,
    [string]$RunId
)

$ErrorActionPreference = "Stop"
$components = if ($Component -eq "all") { @("backend", "agent", "frontend") } else { @($Component) }
$runsFullAcceptance = -not $SkipAcceptance -and $Component -eq "all"
$repoRoot = Split-Path -Parent $PSScriptRoot

if ($runsFullAcceptance) {
    . "$PSScriptRoot/gate-images.ps1"
    if ([string]::IsNullOrWhiteSpace($RunId)) {
        $RunId = "issue182-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
    }
    if ($RunId -notmatch '^[a-z0-9][a-z0-9-]{7,}$') {
        throw 'RunId 只能包含小写字母、数字和连字符，且至少 8 位。'
    }
    $imageTag = "gate-$RunId"
    $projectName = "customer-agent-$imageTag"
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
}

if ($runsFullAcceptance) {
    & "$PSScriptRoot/confirm-compose-reset-isolation.ps1"
}

& "$PSScriptRoot/test-runtime-log-policy.ps1"
& "$PSScriptRoot/test-gradle-proxy.ps1"
& "$PSScriptRoot/test-compose-network-policy.ps1"
& "$PSScriptRoot/test-compose-reset-isolation.ps1"
& "$PSScriptRoot/test-issue129-acceptance-contract.ps1"
& "$PSScriptRoot/test-gate-image-reuse.ps1"
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
        $smokeWatch.Stop()
        docker compose -p $projectName down --volumes --remove-orphans
        $remainingSmokeResources = @(
            @(docker ps --all --quiet --filter "label=com.docker.compose.project=$projectName") +
            @(docker volume ls --quiet --filter "label=com.docker.compose.project=$projectName") +
            @(docker network ls --quiet --filter "label=com.docker.compose.project=$projectName")
        )
        if ($remainingSmokeResources.Count -ne 0) {
            throw "smoke 阶段清理回读非空: $($remainingSmokeResources -join ',')"
        }

        $browserWatch = [System.Diagnostics.Stopwatch]::StartNew()
        & "$PSScriptRoot/issue80-acceptance.ps1" -SkipBuild -RunId $RunId -SourceFingerprint $sourceFingerprint
        $browserWatch.Stop()
        $completed = $true
    } finally {
        docker compose -p $projectName down --volumes --remove-orphans 2>$null | Out-Null
        if ($completed) {
            Remove-GateImages -RunId $RunId
        }
    }
    $gateWatch.Stop()
    $builtCount = @($buildResults | Where-Object { -not $_.Reused }).Count
    $reusedCount = @($buildResults | Where-Object Reused).Count
    Write-Host "Issue #182 gate evidence: run=$RunId fingerprint=$sourceFingerprint cache=shared-warm buildTargets=$builtCount reusedTargets=$reusedCount buildSeconds=$([math]::Round($buildWatch.Elapsed.TotalSeconds, 3)) smokeSeconds=$([math]::Round($smokeWatch.Elapsed.TotalSeconds, 3)) browserSeconds=$([math]::Round($browserWatch.Elapsed.TotalSeconds, 3)) totalSeconds=$([math]::Round($gateWatch.Elapsed.TotalSeconds, 3))"
}
