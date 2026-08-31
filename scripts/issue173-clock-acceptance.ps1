param(
    [Parameter(Mandatory)][string]$ProjectName
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited
Set-Location (Split-Path -Parent $PSScriptRoot)

# 仅由 issue80-acceptance.ps1 在其自有隔离栈内调用，不另建资源、不获取第二把锁。
$hadFixedInstant = Test-Path Env:DEMO_FIXED_INSTANT
$previousFixedInstant = $env:DEMO_FIXED_INSTANT
$hadPhase = Test-Path Env:ISSUE173_CLOCK_PHASE
$previousPhase = $env:ISSUE173_CLOCK_PHASE

function Restart-Issue173BackendAndProxy {
    docker compose --project-name $ProjectName up --detach --no-deps --no-build --force-recreate --wait backend
    # 现有 nginx 静态解析 backend；重建可能换 IP，重启现有代理重新解析后再进入浏览器阶段。
    docker compose --project-name $ProjectName --profile smoke restart browser-frontend
    docker compose --project-name $ProjectName --profile smoke up --detach --no-deps --no-build --no-recreate --wait browser-frontend
}

function Invoke-Issue173ClockPhase([string]$Phase, [string]$Instant) {
    $env:DEMO_FIXED_INSTANT = $Instant
    $env:ISSUE173_CLOCK_PHASE = $Phase
    Restart-Issue173BackendAndProxy
    docker compose --project-name $ProjectName --profile smoke run --rm --no-deps browser-acceptance `
        --workers=1 e2e/issue173.auto-resolution-clock.spec.ts
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #173 时钟阶段失败：$Phase，退出码 $LASTEXITCODE"
    }
}

try {
    Invoke-Issue173ClockPhase 'prepare' '2026-08-09T14:00:00Z'
    Invoke-Issue173ClockPhase 'before-due' '2026-08-09T14:04:59Z'
    Invoke-Issue173ClockPhase 'resolved' '2026-08-09T14:05:00Z'
    # 同卷、同一业务时间再次重建，验证不会重复解决或重置72小时截止。
    Invoke-Issue173ClockPhase 'resolved-restart' '2026-08-09T14:05:00Z'
    Invoke-Issue173ClockPhase 'before-close' '2026-08-12T14:04:59Z'
    Invoke-Issue173ClockPhase 'closed' '2026-08-12T14:05:00Z'
} finally {
    if ($hadFixedInstant) {
        $env:DEMO_FIXED_INSTANT = $previousFixedInstant
    } else {
        Remove-Item Env:DEMO_FIXED_INSTANT -ErrorAction SilentlyContinue
    }
    if ($hadPhase) {
        $env:ISSUE173_CLOCK_PHASE = $previousPhase
    } else {
        Remove-Item Env:ISSUE173_CLOCK_PHASE -ErrorAction SilentlyContinue
    }
    Restart-Issue173BackendAndProxy
}

Write-Host 'Issue #173：真实UI候选、到期解决、重启持久化及72小时回复边界验收通过'
