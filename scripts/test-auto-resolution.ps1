$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# 仅在当前完整门禁的隔离栈执行；复用已构建镜像，不建立第二套资源。
& "$PSScriptRoot/confirm-compose-reset-isolation.ps1"
$namespace = [guid]::NewGuid()
$namespaceHex = $namespace.ToString('N').ToUpperInvariant()
$scriptPath = Join-Path $repoRoot 'agent/auto_resolution_smoke.py'
$scriptMount = "${scriptPath}:/smoke/auto_resolution_smoke.py:ro"
$hadFixedInstant = Test-Path Env:DEMO_FIXED_INSTANT
$previousFixedInstant = $env:DEMO_FIXED_INSTANT
$markerDirectory = Join-Path $repoRoot ".local/auto-resolution/$($namespace.ToString('N'))"
$markerMount = "${markerDirectory}:/auto-resolution-markers"
$raceContainer = "$($env:COMPOSE_PROJECT_NAME)-auto162-$($namespace.ToString('N'))"
$raceJob = $null

function Set-AutoResolutionClock([string]$Instant) {
    $env:DEMO_FIXED_INSTANT = $Instant
    docker compose up --detach --no-deps --no-build --force-recreate --wait backend
}

function Invoke-AutoResolutionPhase([string]$Phase) {
    docker compose --profile smoke run --rm --no-deps --volume $scriptMount `
        --entrypoint python integration-smoke /smoke/auto_resolution_smoke.py `
        $Phase --namespace ($namespace.ToString())
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #162 持久化验收失败：$Phase，退出码 $LASTEXITCODE"
    }
}

try {
    New-Item -ItemType Directory -Path $markerDirectory | Out-Null
    Set-AutoResolutionClock '2026-08-09T14:00:00Z'
    # 与既有 smoke 一致，由 postgres 初始化独立合成订单；不扩展应用/fixture 权限。
    $seed = @"
INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
)
SELECT 'ORDER-AUTO162-$namespaceHex-' || upper(scenario), 'customer-demo', 268.00,
       'CNY', CASE WHEN scenario = 'completed-check' THEN 0 ELSE 23 END,
       CASE WHEN scenario = 'completed-check' THEN 0 ELSE 82800 END,
       true, false, false, false, 'delay-policy-v1', 268.00
FROM unnest(ARRAY['success', 'reply', 'cancel', 'pending', 'compensation', 'proposal', 'human',
                 'facts', 'generation', 'stream', 'partial', 'exact-race', 'completed-check', 'history']) AS scenario;
"@
    $seed | docker compose exec -T postgres psql -U postgres -d customer_agent -v ON_ERROR_STOP=1
    Invoke-AutoResolutionPhase 'prepare'

    Set-AutoResolutionClock '2026-08-09T14:04:59Z'
    Invoke-AutoResolutionPhase 'before_due'
    $raceJob = Start-Job -ScriptBlock {
        param($WorkingDirectory, $ScriptVolume, $MarkerVolume, $ContainerName, $NamespaceValue)
        $ErrorActionPreference = 'Stop'
        $PSNativeCommandUseErrorActionPreference = $true
        Set-Location $WorkingDirectory
        . (Join-Path $WorkingDirectory 'scripts/test-gate-lock.ps1')
        Assert-TestGateInherited
        docker compose --profile smoke run --rm --no-deps --name $ContainerName `
            --volume $ScriptVolume --volume $MarkerVolume --entrypoint python `
            integration-smoke /smoke/auto_resolution_smoke.py exact_race `
            --namespace $NamespaceValue --marker-directory /auto-resolution-markers 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Issue #162 精确截止验收失败，退出码 $LASTEXITCODE"
        }
    } -ArgumentList $repoRoot, $scriptMount, $markerMount, $raceContainer, ($namespace.ToString())
    $readyDeadline = [DateTime]::UtcNow.AddSeconds(45)
    while (-not (Test-Path -LiteralPath (Join-Path $markerDirectory 'ready'))) {
        if ($raceJob.State -ne 'Running') {
            Receive-Job -Job $raceJob -ErrorAction Stop
            throw 'Issue #162 调度屏障未建立，后台任务已结束'
        }
        if ([DateTime]::UtcNow -ge $readyDeadline) {
            throw 'Issue #162 调度屏障未在限定时间内建立'
        }
        Start-Sleep -Milliseconds 100
    }
    Set-AutoResolutionClock '2026-08-09T14:05:00Z'
    Set-Content -LiteralPath (Join-Path $markerDirectory 'due') -Value 'backend-at-deadline'
    $null = Wait-Job -Job $raceJob -Timeout 50
    if ($raceJob.State -ne 'Completed') {
        Receive-Job -Job $raceJob -ErrorAction Stop
        throw 'Issue #162 精确截止验收未完成'
    }
    Receive-Job -Job $raceJob -ErrorAction Stop
    if (-not (Test-Path -LiteralPath (Join-Path $markerDirectory 'done'))) {
        throw 'Issue #162 精确截止验收缺少完成标记'
    }
    Invoke-AutoResolutionPhase 'expired'
    # 同卷、同一截止时刻再次重建；不得增加解决事件或重置关闭等待期。
    Set-AutoResolutionClock '2026-08-09T14:05:00Z'
    Invoke-AutoResolutionPhase 'expired'
    Set-AutoResolutionClock '2026-08-12T14:04:59Z'
    Invoke-AutoResolutionPhase 'before_close'
    Set-AutoResolutionClock '2026-08-12T14:05:00Z'
    Invoke-AutoResolutionPhase 'closed'
} finally {
    try {
        if ($null -ne $raceJob) {
            # Stop-Job 不保证终止其 docker 客户端已启动的容器，先精确清理自有容器。
            try {
                $remainingNames = @(docker container ls --all --filter "name=$raceContainer" --format '{{.Names}}')
                if ($remainingNames -contains $raceContainer) {
                    docker container rm --force $raceContainer | Out-Null
                }
            } finally {
                if ($raceJob.State -eq 'Running') {
                    Stop-Job -Job $raceJob
                }
                Remove-Job -Job $raceJob -Force
            }
        }
    } finally {
        try {
            # 仅删本次 UUID 目录中的三个自有标记；目录有意外文件时快速失败，不递归删除。
            foreach ($marker in @('ready', 'due', 'done')) {
                $markerPath = Join-Path $markerDirectory $marker
                if (Test-Path -LiteralPath $markerPath) {
                    Remove-Item -LiteralPath $markerPath -Force
                }
            }
            if (Test-Path -LiteralPath $markerDirectory) {
                Remove-Item -LiteralPath $markerDirectory
            }
        } finally {
            if ($hadFixedInstant) {
                $env:DEMO_FIXED_INSTANT = $previousFixedInstant
            } else {
                Remove-Item Env:DEMO_FIXED_INSTANT -ErrorAction SilentlyContinue
            }
            docker compose up --detach --no-deps --no-build --force-recreate --wait backend
        }
    }
}

Write-Host 'Issue #162：持久化期限、精确截止回复优先、取消、到期重校验、重复调度与72小时关闭验收通过'
