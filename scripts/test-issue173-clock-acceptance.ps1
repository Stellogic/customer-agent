$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/test-gate-lock.ps1"
Assert-TestGateInherited

# 仅验证编排：下面的 docker 函数记录参数，不调用 Docker，也不制造任何产品验收结果。
$helper = Join-Path $PSScriptRoot 'issue173-clock-acceptance.ps1'
foreach ($file in @($helper, (Join-Path $PSScriptRoot 'issue80-acceptance.ps1'))) {
    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -ne 0) { throw ($parseErrors.Message -join "`n") }
}

$project = 'customer-agent-issue173-offline-contract'
$expectedPhases = @('prepare', 'before-due', 'resolved', 'resolved-restart', 'before-close', 'closed')
$expectedInstants = @(
    '2026-08-09T14:00:00Z', '2026-08-09T14:04:59Z', '2026-08-09T14:05:00Z',
    '2026-08-09T14:05:00Z', '2026-08-12T14:04:59Z', '2026-08-12T14:05:00Z'
)
$savedInstant = $env:DEMO_FIXED_INSTANT
$savedPhase = $env:ISSUE173_CLOCK_PHASE
$hadInstant = Test-Path Env:DEMO_FIXED_INSTANT
$hadPhase = Test-Path Env:ISSUE173_CLOCK_PHASE

function Assert-Equal($Actual, $Expected, [string]$Message) {
    if ($Actual -cne $Expected) { throw "$Message：实际=$Actual，预期=$Expected" }
}

try {
    foreach ($case in @('success-existing-env', 'browser-failure-no-env', 'backend-failure-existing-env')) {
        $calls = [System.Collections.Generic.List[object]]::new()
        $existingEnv = $case -ne 'browser-failure-no-env'
        if ($existingEnv) {
            $env:DEMO_FIXED_INSTANT = '2026-08-08T12:00:00Z'
            $env:ISSUE173_CLOCK_PHASE = 'caller-value'
        } else {
            Remove-Item Env:DEMO_FIXED_INSTANT -ErrorAction SilentlyContinue
            Remove-Item Env:ISSUE173_CLOCK_PHASE -ErrorAction SilentlyContinue
        }
        function docker {
            $command = $args -join ' '
            $calls.Add([pscustomobject]@{
                Command = $command
                Phase = $env:ISSUE173_CLOCK_PHASE
                Instant = $env:DEMO_FIXED_INSTANT
            })
            if (-not $command.StartsWith("compose --project-name $project ")) {
                throw "编排命令没有限定本次project：$command"
            }
            $global:LASTEXITCODE = 0
            if ($case -eq 'browser-failure-no-env' -and $env:ISSUE173_CLOCK_PHASE -eq 'before-close' -and $command -match ' run ') {
                $global:LASTEXITCODE = 17
            }
            if ($case -eq 'backend-failure-existing-env' -and $env:ISSUE173_CLOCK_PHASE -eq 'before-due' -and $command.EndsWith(' backend')) {
                throw '模拟后端重建失败'
            }
        }

        $failure = $null
        try {
            & $helper -ProjectName $project 6>&1 | ForEach-Object { Write-Host "MOCK_DOCKER_HELPER: $_" }
        } catch { $failure = $_.Exception.Message }
        if ($case -eq 'success-existing-env') {
            if ($failure) { throw $failure }
        } elseif ($case -eq 'browser-failure-no-env') {
            if ($failure -notmatch 'before-close.*17') { throw "未传播浏览器阶段失败：$failure" }
        } elseif ($failure -notmatch '模拟后端重建失败') {
            throw "未传播后端重建失败：$failure"
        }

        $runs = @($calls | Where-Object { $_.Command -match ' run ' })
        $runCount = switch ($case) {
            'success-existing-env' { 6 }
            'browser-failure-no-env' { 5 }
            'backend-failure-existing-env' { 1 }
        }
        Assert-Equal $runs.Count $runCount '失败后不应再启动后续浏览器阶段'
        for ($index = 0; $index -lt $runs.Count; $index++) {
            Assert-Equal $runs[$index].Phase $expectedPhases[$index] '阶段顺序'
            Assert-Equal $runs[$index].Instant $expectedInstants[$index] '业务时钟'
            Assert-Equal $runs[$index].Command "compose --project-name $project --profile smoke run --rm --no-deps browser-acceptance --workers=1 e2e/issue173.auto-resolution-clock.spec.ts" '仅运行自有串行时钟spec'
            $position = $calls.IndexOf($runs[$index])
            if ($position -lt 3) { throw '浏览器前缺少后端与代理准备' }
            Assert-Equal $calls[$position - 3].Command "compose --project-name $project up --detach --no-deps --no-build --force-recreate --wait backend" '浏览器前重建后端'
            Assert-Equal $calls[$position - 2].Command "compose --project-name $project --profile smoke restart browser-frontend" '浏览器前刷新代理地址'
            Assert-Equal $calls[$position - 1].Command "compose --project-name $project --profile smoke up --detach --no-deps --no-build --no-recreate --wait browser-frontend" '浏览器前等待代理健康'
        }

        Assert-Equal (Test-Path Env:DEMO_FIXED_INSTANT) $existingEnv '时钟环境存在性恢复'
        Assert-Equal (Test-Path Env:ISSUE173_CLOCK_PHASE) $existingEnv '阶段环境存在性恢复'
        if ($existingEnv) {
            Assert-Equal $env:DEMO_FIXED_INSTANT '2026-08-08T12:00:00Z' '时钟原值恢复'
            Assert-Equal $env:ISSUE173_CLOCK_PHASE 'caller-value' '阶段原值恢复'
        }
        $restored = @($calls | Select-Object -Last 3)
        Assert-Equal $restored[0].Command "compose --project-name $project up --detach --no-deps --no-build --force-recreate --wait backend" 'finally恢复后端'
        Assert-Equal $restored[1].Command "compose --project-name $project --profile smoke restart browser-frontend" 'finally刷新代理'
        Assert-Equal $restored[2].Command "compose --project-name $project --profile smoke up --detach --no-deps --no-build --no-recreate --wait browser-frontend" 'finally等待代理健康'
        Assert-Equal $restored[0].Instant $env:DEMO_FIXED_INSTANT '恢复重建使用原时钟'
        Write-Host "OFFLINE_CONTRACT_PASS case=$case browserPhases=$($runs.Count) realDockerCalls=0"
    }
} finally {
    Remove-Item Function:docker -ErrorAction SilentlyContinue
    if ($hadInstant) { $env:DEMO_FIXED_INSTANT = $savedInstant } else { Remove-Item Env:DEMO_FIXED_INSTANT -ErrorAction SilentlyContinue }
    if ($hadPhase) { $env:ISSUE173_CLOCK_PHASE = $savedPhase } else { Remove-Item Env:ISSUE173_CLOCK_PHASE -ErrorAction SilentlyContinue }
}

Write-Host 'Issue #173 离线编排契约通过；不代表真实浏览器、时钟或业务验收通过。'
