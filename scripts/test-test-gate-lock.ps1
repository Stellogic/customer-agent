$ErrorActionPreference = 'Stop'
$lockScript = Join-Path $PSScriptRoot 'test-gate-lock.ps1'
$checkScript = Join-Path $PSScriptRoot 'check.ps1'
$identity = "issue195-protocol-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
$stateDir = Join-Path $env:LOCALAPPDATA "Stellogic\customer-agent\test-gate\$identity"
$holder = $null
$leftoverContainer = $null
$leftoverProject = "customer-agent-gate-$identity"

function Invoke-LockCli {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [hashtable]$Environment
    )
    $argumentList = @('-NoProfile', '-File', $lockScript, '-LockIdentity', $identity) + $Arguments
    $previous = @{}
    if ($Environment) {
        foreach ($key in $Environment.Keys) {
            $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
            Set-Item -Path "Env:$key" -Value $Environment[$key]
        }
    }
    try {
        $output = & pwsh @argumentList 2>&1 | ForEach-Object { "$_" }
        return [pscustomobject]@{
            ExitCode = $LASTEXITCODE
            Output   = ($output -join "`n")
        }
    } finally {
        if ($Environment) {
            foreach ($key in $Environment.Keys) {
                if ($null -eq $previous[$key]) {
                    Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
                } else {
                    Set-Item -Path "Env:$key" -Value $previous[$key]
                }
            }
        }
    }
}

function Start-LockHolder {
    param(
        [int]$HoldSeconds = 90,
        [string]$ComposeProject,
        [string]$ImageTag
    )
    $outFile = Join-Path $env:TEMP "test-gate-hold-$identity.out"
    $errFile = Join-Path $env:TEMP "test-gate-hold-$identity.err"
    Remove-Item -LiteralPath $outFile, $errFile -ErrorAction SilentlyContinue
    $savedToken = $env:CUSTOMER_AGENT_TEST_GATE_TOKEN
    $savedIdentity = $env:CUSTOMER_AGENT_TEST_GATE_IDENTITY
    Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_IDENTITY -ErrorAction SilentlyContinue
    $argLine = "-NoProfile -File `"$lockScript`" -Hold -LockIdentity $identity -Issue 195 -CommandType check -HoldSeconds $HoldSeconds"
    if (-not [string]::IsNullOrWhiteSpace($ComposeProject)) {
        $argLine += " -ComposeProject $ComposeProject"
    }
    if (-not [string]::IsNullOrWhiteSpace($ImageTag)) {
        $argLine += " -ImageTag $ImageTag"
    }
    $process = Start-Process -FilePath 'pwsh' -ArgumentList $argLine -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    if ($null -eq $savedToken) {
        Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_TOKEN -ErrorAction SilentlyContinue
    } else {
        $env:CUSTOMER_AGENT_TEST_GATE_TOKEN = $savedToken
    }
    if ($null -eq $savedIdentity) {
        Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_IDENTITY -ErrorAction SilentlyContinue
    } else {
        $env:CUSTOMER_AGENT_TEST_GATE_IDENTITY = $savedIdentity
    }
    $deadline = (Get-Date).AddSeconds(20)
    $text = ''
    do {
        Start-Sleep -Milliseconds 200
        if (Test-Path -LiteralPath $outFile) {
            $text = Get-Content -LiteralPath $outFile -Raw -ErrorAction SilentlyContinue
        }
        if ($text -match 'TEST_GATE_HELD') {
            break
        }
        if ($process.HasExited) {
            $err = ''
            if (Test-Path -LiteralPath $errFile) {
                $err = Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue
            }
            throw "持锁进程提前退出 $($process.ExitCode): $text $err"
        }
    } while ((Get-Date) -lt $deadline -and $text -notmatch 'TEST_GATE_HELD')
    if ($text -notmatch 'TEST_GATE_HELD') {
        throw "持锁进程未在时限内输出 TEST_GATE_HELD"
    }
    return [pscustomobject]@{
        Process = $process
        Output  = $text
        OutFile = $outFile
    }
}

function Stop-LockHolder {
    param($Started)
    if ($null -eq $Started -or $null -eq $Started.Process) {
        return
    }
    if (-not $Started.Process.HasExited) {
        Stop-Process -Id $Started.Process.Id -Force -ErrorAction SilentlyContinue
        try {
            Wait-Process -Id $Started.Process.Id -Timeout 8 -ErrorAction SilentlyContinue
        } catch {
        }
    }
}

function Assert-Pass {
    param([string]$Name)
    Write-Host "PASS: $Name"
}

try {
    $free = Invoke-LockCli -Arguments @('-Status')
    if ($free.ExitCode -ne 0 -or $free.Output -notmatch 'TEST_GATE_FREE') {
        throw "空闲状态查询失败: exit=$($free.ExitCode) $($free.Output)"
    }
    Assert-Pass '空闲时只读状态为 FREE'

    $holder = Start-LockHolder
    $busy = $null
    foreach ($ignored in 1..20) {
        $busy = Invoke-LockCli -Arguments @('-Status')
        if ($busy.ExitCode -eq 0 -and $busy.Output -match 'TEST_GATE_BUSY' -and $busy.Output -match 'issue=195' -and $busy.Output -match 'commandType=check' -and $busy.Output -match 'worktree=') {
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if ($busy.ExitCode -ne 0 -or $busy.Output -notmatch 'TEST_GATE_BUSY') {
        throw "占用状态查询失败: $($busy.Output)"
    }
    if ($busy.Output -notmatch 'issue=195' -or $busy.Output -notmatch 'commandType=check' -or $busy.Output -notmatch "worktree=") {
        throw "占用摘要缺少 Issue/命令/worktree: $($busy.Output)"
    }
    Assert-Pass '持锁后只读状态能看到正确占用者'

    $conflict = Invoke-LockCli -Arguments @('-Hold', '-HoldSeconds', '1', '-Issue', '163')
    if ($conflict.ExitCode -ne 75 -or $conflict.Output -notmatch 'TEST_GATE_BUSY') {
        throw "第二进程应立即 TEST_GATE_BUSY: exit=$($conflict.ExitCode) $($conflict.Output)"
    }
    if ($conflict.Output -match 'docker' -and $conflict.Output -match '(?i)compose up|docker build') {
        throw "冲突进程在返回 BUSY 前启动了 Docker"
    }
    Assert-Pass '第二进程在任何 Docker/构建前立即 TEST_GATE_BUSY'

    $cross = Invoke-LockCli -Arguments @('-Hold', '-HoldSeconds', '1', '-Issue', '166')
    if ($cross.ExitCode -ne 75 -or $cross.Output -notmatch 'TEST_GATE_BUSY') {
        throw "不同工作目录仍应竞争同一把锁: $($cross.Output)"
    }
    Assert-Pass '工作树 B 不能获取工作树 A 已持有的锁'

    $beforeStatus = Invoke-LockCli -Arguments @('-Status')
    $statePath = Join-Path $stateDir 'state.json'
    $beforeJson = Get-Content -LiteralPath $statePath -Raw
    $beforeBusy = Test-Path -LiteralPath $statePath
    $statusAgain = Invoke-LockCli -Arguments @('-Status')
    $afterJson = Get-Content -LiteralPath $statePath -Raw
    if ($beforeStatus.Output -notmatch 'TEST_GATE_BUSY' -or $statusAgain.Output -notmatch 'TEST_GATE_BUSY') {
        throw '重复查询应保持 BUSY'
    }
    if ($beforeJson -ne $afterJson -or -not $beforeBusy) {
        throw '只读状态查询不得修改状态记录'
    }
    Assert-Pass '只读状态查询不会改变锁或状态记录'

    $inheritedMissing = Invoke-LockCli -Arguments @('-AssertInherited')
    if ($inheritedMissing.ExitCode -ne 76 -or $inheritedMissing.Output -notmatch 'TEST_GATE_LOCK_REQUIRED') {
        throw "无令牌子脚本应 LOCK_REQUIRED: exit=$($inheritedMissing.ExitCode) $($inheritedMissing.Output)"
    }
    Assert-Pass '无令牌时 AssertInherited 返回 TEST_GATE_LOCK_REQUIRED'

    $stateRecord = Get-Content -LiteralPath (Join-Path $stateDir 'state.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $token = [string]$stateRecord.ownerToken
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "状态记录缺少 ownerToken"
    }
    $inheritedOk = Invoke-LockCli -Arguments @('-AssertInherited') -Environment @{ CUSTOMER_AGENT_TEST_GATE_TOKEN = $token }
    if ($inheritedOk.ExitCode -ne 0 -or $inheritedOk.Output -notmatch 'TEST_GATE_INHERITED') {
        throw "持锁时继承令牌应成功: $($inheritedOk.Output)"
    }
    Assert-Pass '总入口持锁时嵌套子脚本继承令牌且不自锁'

    . $lockScript
    Remove-TestGateStateIfOwner -Identity $identity -OwnerToken 'stale-other-owner'
    $stillBusy = Invoke-LockCli -Arguments @('-Status')
    if ($stillBusy.Output -notmatch 'TEST_GATE_BUSY' -or $stillBusy.Output -notmatch 'issue=195') {
        throw '较早持有者不得删除当前占用记录'
    }
    Assert-Pass '较早持有者不能删除较晚持有者的记录'

    $protectedScripts = @(
        @{ Name = 'smoke.ps1'; Args = @() },
        @{ Name = 'issue80-acceptance.ps1'; Args = @() },
        @{ Name = 'build-offline-runtime.ps1'; Args = @('-TestTag', 'local', '-RuntimeTag', 'local') },
        @{ Name = 'real-model-smoke.ps1'; Args = @() },
        @{ Name = 'synthetic-model-evaluation.ps1'; Args = @() },
        @{ Name = 'test-gradle-proxy.ps1'; Args = @() },
        @{ Name = 'confirm-compose-reset-isolation.ps1'; Args = @() },
        @{ Name = 'deepseek-real-shadow.ps1'; Args = @() },
        @{ Name = 'deepseek-clarification-retest.ps1'; Args = @() },
        @{ Name = 'deepseek-formal-acceptance.ps1'; Args = @() },
        @{ Name = 'deepseek-real-evaluation.ps1'; Args = @() },
        @{ Name = 'deepseek-b1-acceptance.ps1'; Args = @() },
        @{ Name = 'deepseek-model-comparison.ps1'; Args = @() },
        @{ Name = 'deepseek-customer-communication-acceptance.ps1'; Args = @() }
    )
    foreach ($item in $protectedScripts) {
        $scriptPath = Join-Path $PSScriptRoot $item.Name
        $cleared = @(
            'CUSTOMER_AGENT_TEST_GATE_TOKEN',
            'CUSTOMER_AGENT_TEST_GATE_IDENTITY',
            'COMPOSE_PROJECT_NAME',
            'CUSTOMER_AGENT_IMAGE_TAG',
            'CUSTOMER_AGENT_FRONTEND_PORT',
            'CUSTOMER_AGENT_GATE_RUN_ID',
            'CUSTOMER_AGENT_GATE_SOURCE_FINGERPRINT'
        )
        $previous = @{}
        foreach ($key in $cleared) {
            $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
            Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
        }
        try {
            $output = & pwsh -NoProfile -File $scriptPath @($item.Args) 2>&1 | ForEach-Object { "$_" }
            $code = $LASTEXITCODE
        } finally {
            foreach ($key in $cleared) {
                if ($null -eq $previous[$key] -or $previous[$key] -eq '') {
                    Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
                } else {
                    Set-Item -Path "Env:$key" -Value $previous[$key]
                }
            }
        }
        $text = $output -join "`n"
        if ($code -ne 76 -or $text -notmatch 'TEST_GATE_LOCK_REQUIRED') {
            throw "$($item.Name) 无令牌应 TEST_GATE_LOCK_REQUIRED，实际 exit=$code $text"
        }
        if ($text -match '(?i)docker compose up|docker build --') {
            throw "$($item.Name) 在 LOCK_REQUIRED 前启动了 Docker/构建"
        }
    }
    Assert-Pass '受保护子脚本无令牌时 TEST_GATE_LOCK_REQUIRED 且不启动 Docker/构建'

    $checkOut = Join-Path $env:TEMP "test-gate-check-$identity.out"
    $checkErr = Join-Path $env:TEMP "test-gate-check-$identity.err"
    Remove-Item -LiteralPath $checkOut, $checkErr -ErrorAction SilentlyContinue
    $previousIdentity = $env:CUSTOMER_AGENT_TEST_GATE_IDENTITY
    $env:CUSTOMER_AGENT_TEST_GATE_IDENTITY = $identity
    $checkProc = Start-Process -FilePath 'pwsh' -ArgumentList @(
        '-NoProfile', '-File', $checkScript,
        '-Component', 'backend', '-SkipAcceptance', '-Issue', '163'
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $checkOut -RedirectStandardError $checkErr
    if ($null -eq $previousIdentity) {
        Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_IDENTITY -ErrorAction SilentlyContinue
    } else {
        $env:CUSTOMER_AGENT_TEST_GATE_IDENTITY = $previousIdentity
    }
    $waited = $checkProc.WaitForExit(20000)
    if (-not $waited) {
        Stop-Process -Id $checkProc.Id -Force -ErrorAction SilentlyContinue
        throw 'check.ps1 在锁冲突时没有立即退出'
    }
    $checkText = ((Get-Content -LiteralPath $checkOut -Raw -ErrorAction SilentlyContinue) + "`n" + (Get-Content -LiteralPath $checkErr -Raw -ErrorAction SilentlyContinue))
    if ($checkProc.ExitCode -ne 75 -or $checkText -notmatch 'TEST_GATE_BUSY') {
        throw "规范化入口冲突应 TEST_GATE_BUSY: exit=$($checkProc.ExitCode) $checkText"
    }
    if ($checkText -match '(?i)docker build --target test') {
        throw '规范化入口在 BUSY 后仍启动了构建'
    }
    Assert-Pass '规范化入口在锁占用时立即 TEST_GATE_BUSY'

    Stop-LockHolder $holder
    $holder = $null
    $released = $false
    foreach ($ignored in 1..25) {
        $status = Invoke-LockCli -Arguments @('-Status')
        if ($status.Output -match 'TEST_GATE_FREE') {
            $released = $true
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not $released) {
        throw '正常结束后后续进程应能看到 FREE'
    }
    $reacquire = Invoke-LockCli -Arguments @('-Hold', '-HoldSeconds', '1', '-Issue', '195')
    if ($reacquire.ExitCode -ne 0 -or $reacquire.Output -notmatch 'TEST_GATE_HELD') {
        throw "正常释放后应能再次获取锁: $($reacquire.Output)"
    }
    Assert-Pass '正常结束后后续进程能获取锁'

    $failHolder = Start-LockHolder -HoldSeconds 90
    Stop-LockHolder $failHolder
    $failHolder = $null
    $afterKill = $null
    foreach ($ignored in 1..25) {
        $afterKill = Invoke-LockCli -Arguments @('-Status')
        if ($afterKill.Output -match 'TEST_GATE_FREE' -or $afterKill.Output -match 'TEST_GATE_RECOVERY_REQUIRED') {
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if ($afterKill.Output -notmatch 'TEST_GATE_FREE' -and $afterKill.Output -notmatch 'TEST_GATE_RECOVERY_REQUIRED') {
        throw "终止持锁进程后权威锁应释放: $($afterKill.Output)"
    }
    $afterStale = Invoke-LockCli -Arguments @('-Hold', '-HoldSeconds', '1', '-Issue', '195')
    if ($afterStale.ExitCode -ne 0 -or $afterStale.Output -notmatch 'TEST_GATE_HELD') {
        throw "陈旧 JSON 不得单独阻止新进程: $($afterStale.Output)"
    }
    Assert-Pass '进程终止后操作系统释放互斥量，陈旧 JSON 不阻止新进程'

    $recoverHolder = Start-LockHolder -ComposeProject $leftoverProject -ImageTag "gate-$identity" -HoldSeconds 90
    $recoverRecord = $null
    foreach ($ignored in 1..20) {
        $statePath = Join-Path $stateDir 'state.json'
        if (Test-Path -LiteralPath $statePath) {
            $recoverRecord = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
            if ([string]$recoverRecord.composeProject -eq $leftoverProject) {
                break
            }
        }
        Start-Sleep -Milliseconds 100
    }
    if ($null -eq $recoverRecord -or [string]$recoverRecord.composeProject -ne $leftoverProject) {
        $seen = @(Get-ChildItem -Recurse (Join-Path $env:LOCALAPPDATA 'Stellogic\customer-agent\test-gate') -ErrorAction SilentlyContinue | ForEach-Object FullName) -join '; '
        throw "持锁记录未写入 composeProject，实际=$($recoverRecord.composeProject) seen=$seen"
    }
    $recoverJson = $recoverRecord | ConvertTo-Json -Depth 8
    Stop-LockHolder $recoverHolder
    $recoverHolder = $null
    foreach ($ignored in 1..25) {
        $released = Invoke-LockCli -Arguments @('-Status')
        if ($released.Output -notmatch 'TEST_GATE_BUSY') {
            break
        }
        Start-Sleep -Milliseconds 200
    }
    $statePath = Join-Path $stateDir 'state.json'
    if (-not (Test-Path -LiteralPath $statePath)) {
        New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
        [System.IO.File]::WriteAllText($statePath, $recoverJson, [System.Text.UTF8Encoding]::new($false))
    }
    $afterCrash = Read-TestGateStateFile (Join-Path $stateDir 'state.json')
    if ($null -eq $afterCrash -or [string]$afterCrash.composeProject -ne $leftoverProject) {
        throw '异常终止后应保留旧状态记录以便残留检查'
    }
    $native = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    docker run --detach --name "$leftoverProject-probe" --label "com.docker.compose.project=$leftoverProject" alpine:3.22 sleep 120 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $PSNativeCommandUseErrorActionPreference = $native
        throw '无法创建精确匹配的残留容器'
    }
    $leftoverContainer = "$leftoverProject-probe"
    $visible = @(docker ps --all --quiet --filter "label=com.docker.compose.project=$leftoverProject")
    $PSNativeCommandUseErrorActionPreference = $native
    if ($visible.Count -lt 1) {
        throw '残留容器创建后 Docker 过滤器看不到精确匹配标签'
    }
    $recovery = Invoke-LockCli -Arguments @('-Hold', '-HoldSeconds', '1', '-Issue', '195')
    if ($recovery.ExitCode -ne 77 -or $recovery.Output -notmatch 'TEST_GATE_RECOVERY_REQUIRED') {
        throw "存在精确匹配残留时应 RECOVERY_REQUIRED: exit=$($recovery.ExitCode) $($recovery.Output)"
    }
    $stillThere = docker ps --all --quiet --filter "name=$leftoverContainer"
    if (-not $stillThere) {
        throw '恢复路径不得删除残留容器'
    }
    $statusRecovery = Invoke-LockCli -Arguments @('-Status')
    if ($statusRecovery.Output -notmatch 'TEST_GATE_RECOVERY_REQUIRED') {
        throw "只读查询在残留存在时应 RECOVERY_REQUIRED: $($statusRecovery.Output)"
    }
    Assert-Pass '异常放弃且存在精确匹配残留时 RECOVERY_REQUIRED 且不删除资源'

    $PSNativeCommandUseErrorActionPreference = $false
    docker rm --force $leftoverContainer | Out-Null
    $leftoverContainer = $null
    $PSNativeCommandUseErrorActionPreference = $true
    $recovered = Invoke-LockCli -Arguments @('-Hold', '-HoldSeconds', '1', '-Issue', '195')
    if ($recovered.ExitCode -ne 0 -or $recovered.Output -notmatch 'TEST_GATE_HELD') {
        throw "无残留后应能恢复并获取锁: $($recovered.Output)"
    }
    Assert-Pass '异常放弃且不存在残留资源时可以恢复'

    $outerToken = [string]$env:CUSTOMER_AGENT_TEST_GATE_TOKEN
    $clearSentinel = $false
    if ([string]::IsNullOrWhiteSpace($outerToken)) {
        $env:CUSTOMER_AGENT_TEST_GATE_TOKEN = 'outer-token-sentinel'
        $outerToken = 'outer-token-sentinel'
        $clearSentinel = $true
    }
    $evidenceHolder = Enter-TestGateLock -Issue '195' -RunId "issue195-$($identity.Substring($identity.Length-12))" -CommandType 'full-check' -LockIdentity $identity -BaseSha 'base-deadbeef' -HeadSha 'head-cafebabe'
    try {
        $saved = Save-TestGateFullGateEvidence -Holder $evidenceHolder -BaseSha 'base-deadbeef' -HeadSha 'head-cafebabe'
        if ($saved.issue -ne '195' -or $saved.runId -notmatch 'issue195-' -or $saved.baseSha -ne 'base-deadbeef' -or $saved.headSha -ne 'head-cafebabe') {
            throw "完整门禁证据字段不完整: $($saved | ConvertTo-Json -Compress)"
        }
        if (Test-TestGateEvidenceCurrent -LockIdentity $identity) {
            throw '与当前仓库 SHA 不符的旧证据不得继续使用'
        }
        if (Test-TestGateEvidenceCurrent -LockIdentity $identity -BaseSha 'other-base' -HeadSha 'head-cafebabe') {
            throw '基线变化后旧证据不能继续使用'
        }
    } finally {
        Exit-TestGateLock $evidenceHolder
    }
    if ([string]$env:CUSTOMER_AGENT_TEST_GATE_TOKEN -ne $outerToken) {
        throw '内层锁退出后应恢复外层所有权令牌'
    }
    if ($clearSentinel) {
        Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_TOKEN -ErrorAction SilentlyContinue
    }
    Assert-Pass '完整门禁证据包含 Issue/RunId/base/head，基线变化后旧证据失效'
} finally {
    Stop-LockHolder $holder
    if ($leftoverContainer) {
        $PSNativeCommandUseErrorActionPreference = $false
        docker rm --force $leftoverContainer 2>$null | Out-Null
    }
    if (Test-Path -LiteralPath $stateDir) {
        Remove-Item -LiteralPath $stateDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host '测试门禁锁协议检查通过。'
