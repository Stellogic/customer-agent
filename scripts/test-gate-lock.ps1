#Requires -Version 7.0
<#
.SYNOPSIS
    跨 worktree 测试门禁锁。Windows 会话级命名互斥量是唯一权威锁。

.DESCRIPTION
    供规范化入口点源持锁，或作为只读 CLI 查询状态。
    状态文件只用于展示占用者，不决定锁是否有效。

    退出码：
      0  成功 / 只读查询完成
      75 TEST_GATE_BUSY
      76 TEST_GATE_LOCK_REQUIRED
      77 TEST_GATE_RECOVERY_REQUIRED

    CLI：
      pwsh ./scripts/test-gate-lock.ps1 -Status
      pwsh ./scripts/test-gate-lock.ps1 -Hold -Issue 195 -HoldSeconds 60
      pwsh ./scripts/test-gate-lock.ps1 -AssertInherited

    环境变量：
      CUSTOMER_AGENT_TEST_GATE_TOKEN      外层入口下发的所有权令牌
      CUSTOMER_AGENT_TEST_GATE_IDENTITY   仅协议测试使用的锁身份，避免污染正式锁
#>

$ErrorActionPreference = 'Stop'
$script:TestGateLockIsDotSourced = $MyInvocation.InvocationName -eq '.'
$script:TestGateBusyExit = 75
$script:TestGateLockRequiredExit = 76
$script:TestGateRecoveryExit = 77
$script:TestGateStateVersion = 1

function Get-TestGateRepoRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-TestGateHash {
    param([Parameter(Mandatory)][string]$Text)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }
    return (([System.BitConverter]::ToString($hash) -replace '-', '')).Substring(0, 16).ToLowerInvariant()
}

function Get-TestGateSafeIdentity {
    param([Parameter(Mandatory)][string]$Raw)
    $safe = ($Raw.Trim() -replace '[^a-zA-Z0-9-]', '-').ToLowerInvariant()
    $safe = $safe -replace '-{2,}', '-'
    if ($safe.Length -gt 80) {
        $safe = $safe.Substring(0, 80).TrimEnd('-')
    }
    if ($safe -notmatch '^[a-z0-9]') {
        $safe = "id-$safe"
    }
    if ([string]::IsNullOrWhiteSpace($safe)) {
        throw '锁身份不能为空。'
    }
    return $safe
}

function Get-TestGateIdentity {
    param([string]$LockIdentity)
    if (-not [string]::IsNullOrWhiteSpace($LockIdentity)) {
        return Get-TestGateSafeIdentity $LockIdentity
    }
    if (-not [string]::IsNullOrWhiteSpace($env:CUSTOMER_AGENT_TEST_GATE_IDENTITY)) {
        return Get-TestGateSafeIdentity $env:CUSTOMER_AGENT_TEST_GATE_IDENTITY
    }
    $origin = ''
    try {
        $origin = @(git -C (Get-TestGateRepoRoot) remote get-url origin 2>$null)[0]
    } catch {
        $origin = ''
    }
    if ([string]::IsNullOrWhiteSpace($origin)) {
        $origin = 'https://github.com/Stellogic/customer-agent.git'
    }
    $normalized = $origin.Trim().ToLowerInvariant() -replace '\.git$', ''
    return "repo-$(Get-TestGateHash $normalized)"
}

function Get-TestGateMutexName {
    param([Parameter(Mandatory)][string]$Identity)
    return "Local\ca-tgl-$Identity"
}

function Get-TestGateStatePath {
    param([Parameter(Mandatory)][string]$Identity)
    return (Join-Path $env:LOCALAPPDATA "Stellogic\customer-agent\test-gate\$Identity\state.json")
}

function Get-TestGateEvidencePath {
    param([Parameter(Mandatory)][string]$Identity)
    return (Join-Path $env:LOCALAPPDATA "Stellogic\customer-agent\test-gate\$Identity\last-full-gate.json")
}

function Write-TestGateStateFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Record
    )
    $dir = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $tmp = Join-Path $dir ".state.$PID.$([guid]::NewGuid().ToString('N')).tmp"
    $json = $Record | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
    try {
        [System.IO.File]::Move($tmp, $Path, $true)
    } catch {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
        throw
    }
}

function Read-TestGateStateFile {
    param([Parameter(Mandatory)][string]$Path)
    foreach ($ignored in 1..8) {
        if (Test-Path -LiteralPath $Path) {
            try {
                $raw = [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false))
                if (-not [string]::IsNullOrWhiteSpace($raw)) {
                    return $raw | ConvertFrom-Json
                }
            } catch {
                Start-Sleep -Milliseconds 50
                continue
            }
        }
        Start-Sleep -Milliseconds 50
    }
    return $null
}

function Remove-TestGateStateIfOwner {
    param(
        [Parameter(Mandatory)][string]$Identity,
        [Parameter(Mandatory)][string]$OwnerToken
    )
    $path = Get-TestGateStatePath $Identity
    $current = Read-TestGateStateFile $path
    if ($null -eq $current) {
        return
    }
    if ([string]$current.ownerToken -ne [string]$OwnerToken) {
        return
    }
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}

function Test-TestGateMutexExists {
    param([Parameter(Mandatory)][string]$Identity)
    $name = Get-TestGateMutexName $Identity
    try {
        $existing = [System.Threading.Mutex]::OpenExisting($name)
        $existing.Dispose()
        return $true
    } catch [System.Threading.WaitHandleCannotBeOpenedException] {
        return $false
    } catch [System.UnauthorizedAccessException] {
        return $true
    }
}

function Get-TestGateGitContext {
    $root = Get-TestGateRepoRoot
    $branch = ''
    $head = ''
    try {
        $branch = @(git -C $root rev-parse --abbrev-ref HEAD 2>$null)[0]
        $head = @(git -C $root rev-parse HEAD 2>$null)[0]
    } catch {
        $branch = ''
        $head = ''
    }
    return [pscustomobject]@{
        Worktree = $root
        Branch   = $branch
        Head     = $head
    }
}

function Find-TestGateLeftovers {
    param($Record)
    if ($null -eq $Record) {
        return @()
    }
    $native = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $leftovers = [System.Collections.Generic.List[string]]::new()
        $project = [string]$Record.composeProject
        if (-not [string]::IsNullOrWhiteSpace($project)) {
            foreach ($id in @(docker ps --all --quiet --filter "label=com.docker.compose.project=$project" 2>$null)) {
                if (-not [string]::IsNullOrWhiteSpace($id)) {
                    [void]$leftovers.Add("container:$id")
                }
            }
            foreach ($id in @(docker volume ls --quiet --filter "label=com.docker.compose.project=$project" 2>$null)) {
                if (-not [string]::IsNullOrWhiteSpace($id)) {
                    [void]$leftovers.Add("volume:$id")
                }
            }
            foreach ($id in @(docker network ls --quiet --filter "label=com.docker.compose.project=$project" 2>$null)) {
                if (-not [string]::IsNullOrWhiteSpace($id)) {
                    [void]$leftovers.Add("network:$id")
                }
            }
        }
        $imageTag = [string]$Record.imageTag
        if ($imageTag -match '^gate-[a-z0-9][a-z0-9-]{7,}$') {
            foreach ($image in @(docker image ls --format '{{.Repository}}:{{.Tag}}' 2>$null)) {
                if ($image -like "*:$imageTag") {
                    [void]$leftovers.Add("image:$image")
                }
            }
        }
        return @($leftovers)
    } catch {
        if (-not [string]::IsNullOrWhiteSpace([string]$Record.composeProject) -or [string]$Record.imageTag -match '^gate-') {
            return @('query-failed:docker')
        }
        return @()
    } finally {
        $PSNativeCommandUseErrorActionPreference = $native
    }
}

function Write-TestGateProtocolOutput {
    param(
        [Parameter(Mandatory)][string]$Code,
        $Record,
        [string[]]$Leftovers,
        [string]$Message
    )
    Write-Output $Code
    Write-Output "status=$($Code -replace '^TEST_GATE_','')"
    if ($null -ne $Record) {
        Write-Output "issue=$($Record.issue)"
        Write-Output "runId=$($Record.runId)"
        Write-Output "pid=$($Record.pid)"
        Write-Output "commandType=$($Record.commandType)"
        Write-Output "branch=$($Record.branch)"
        Write-Output "worktree=$($Record.worktree)"
        Write-Output "head=$($Record.head)"
        if ($Record.baseSha) {
            Write-Output "baseSha=$($Record.baseSha)"
        }
        Write-Output "startedAt=$($Record.startedAt)"
    }
    foreach ($item in @($Leftovers)) {
        if (-not [string]::IsNullOrWhiteSpace($item)) {
            Write-Output "leftover=$item"
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($Message)) {
        Write-Output $Message
    }
}

function Get-TestGateStatus {
    param([string]$LockIdentity)
    $identity = Get-TestGateIdentity $LockIdentity
    $record = Read-TestGateStateFile (Get-TestGateStatePath $identity)
    if (Test-TestGateMutexExists $identity) {
        return [pscustomobject]@{
            Code      = 'TEST_GATE_BUSY'
            Status    = 'BUSY'
            Record    = $record
            Leftovers = @()
        }
    }
    $leftovers = @(Find-TestGateLeftovers $record)
    if ($leftovers.Count -gt 0) {
        return [pscustomobject]@{
            Code      = 'TEST_GATE_RECOVERY_REQUIRED'
            Status    = 'RECOVERY_REQUIRED'
            Record    = $record
            Leftovers = $leftovers
        }
    }
    return [pscustomobject]@{
        Code      = 'TEST_GATE_FREE'
        Status    = 'FREE'
        Record    = $record
        Leftovers = @()
    }
}

function Show-TestGateStatus {
    param([string]$LockIdentity)
    $status = Get-TestGateStatus -LockIdentity $LockIdentity
    $message = switch ($status.Status) {
        'BUSY' { '当前测试门禁被占用。并行任务可继续开发与审查，但不得启动规范化测试或构建。' }
        'RECOVERY_REQUIRED' { '权威锁空闲，但旧运行留下精确匹配资源。协调线程处理残留后再继续，脚本不会自动删除。' }
        default { '测试门禁空闲。' }
    }
    Write-TestGateProtocolOutput -Code $status.Code -Record $status.Record -Leftovers $status.Leftovers -Message $message
}

function Test-TestGateInheritedToken {
    param([string]$LockIdentity)
    $token = [string]$env:CUSTOMER_AGENT_TEST_GATE_TOKEN
    if ([string]::IsNullOrWhiteSpace($token)) {
        return $false
    }
    $identity = Get-TestGateIdentity $LockIdentity
    if (-not (Test-TestGateMutexExists $identity)) {
        return $false
    }
    $record = Read-TestGateStateFile (Get-TestGateStatePath $identity)
    if ($null -eq $record) {
        return $false
    }
    return [string]$record.ownerToken -eq $token
}

function Assert-TestGateInherited {
    param([string]$LockIdentity)
    if (Test-TestGateInheritedToken -LockIdentity $LockIdentity) {
        return
    }
    Write-TestGateProtocolOutput -Code 'TEST_GATE_LOCK_REQUIRED' -Message '重资源子脚本需要规范化入口传入的所有权令牌；直接执行会在启动 Docker、构建、测试服务或浏览器前退出。'
    exit $script:TestGateLockRequiredExit
}

function New-TestGateStateRecord {
    param(
        [Parameter(Mandatory)][string]$Identity,
        [Parameter(Mandatory)][string]$Issue,
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$CommandType,
        [Parameter(Mandatory)][string]$OwnerToken,
        [string]$BaseSha,
        [string]$HeadSha,
        [string]$ComposeProject,
        [string]$ImageTag
    )
    $git = Get-TestGateGitContext
    $head = if ($HeadSha) { $HeadSha } else { $git.Head }
    return [pscustomobject]@{
        schemaVersion  = $script:TestGateStateVersion
        repoIdentity   = $Identity
        issue          = $Issue
        runId          = $RunId
        pid            = $PID
        commandType    = $CommandType
        branch         = $git.Branch
        worktree       = $git.Worktree
        head           = $head
        baseSha        = $BaseSha
        startedAt      = [DateTimeOffset]::Now.ToString('o')
        ownerToken     = $OwnerToken
        composeProject = $ComposeProject
        imageTag       = $ImageTag
    }
}

function Enter-TestGateLock {
    param(
        [string]$Issue = 'manual',
        [string]$RunId,
        [string]$CommandType = 'check',
        [string]$LockIdentity,
        [string]$BaseSha,
        [string]$HeadSha,
        [string]$ComposeProject,
        [string]$ImageTag
    )
    if ([string]::IsNullOrWhiteSpace($Issue)) {
        $Issue = 'manual'
    }
    if ([string]::IsNullOrWhiteSpace($RunId)) {
        $slug = if ($Issue -eq 'manual') { 'manual' } else { "issue$Issue" }
        $RunId = "$slug-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
    }
    $identity = Get-TestGateIdentity $LockIdentity
    if (Test-TestGateInheritedToken -LockIdentity $identity) {
        return [pscustomobject]@{
            AcquiredHere = $false
            Identity     = $identity
            OwnerToken   = [string]$env:CUSTOMER_AGENT_TEST_GATE_TOKEN
            Mutex        = $null
            Issue        = $Issue
            RunId        = $RunId
        }
    }

    $statePath = Get-TestGateStatePath $identity
    $oldRecord = Read-TestGateStateFile $statePath
    $mutexName = Get-TestGateMutexName $identity
    $createdNew = $false
    $mutex = New-Object System.Threading.Mutex($false, $mutexName, [ref]$createdNew)
    $abandoned = $false
    $acquired = $false
    try {
        $acquired = $mutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $abandoned = $true
        $acquired = $true
    }
    if (-not $acquired) {
        $mutex.Dispose()
        Write-TestGateProtocolOutput -Code 'TEST_GATE_BUSY' -Record $oldRecord -Message '测试门禁锁正被占用；立即停止，不要排队、睡眠或循环重试。'
        exit $script:TestGateBusyExit
    }

    $shouldRecover = $abandoned -or ($null -ne $oldRecord)
    if ($shouldRecover) {
        $leftovers = @(Find-TestGateLeftovers $oldRecord)
        if ($leftovers.Count -gt 0) {
            $mutex.ReleaseMutex()
            $mutex.Dispose()
            Write-TestGateProtocolOutput -Code 'TEST_GATE_RECOVERY_REQUIRED' -Record $oldRecord -Leftovers $leftovers -Message '获取到空闲或被放弃的锁，但旧运行留下精确匹配资源。不会自动删除，请由协调线程处理。'
            exit $script:TestGateRecoveryExit
        }
    }

    $previousToken = [string]$env:CUSTOMER_AGENT_TEST_GATE_TOKEN
    $previousMutex = $script:TestGateHeldMutex
    $token = [guid]::NewGuid().ToString('N')
    $record = New-TestGateStateRecord `
        -Identity $identity `
        -Issue $Issue `
        -RunId $RunId `
        -CommandType $CommandType `
        -OwnerToken $token `
        -BaseSha $BaseSha `
        -HeadSha $HeadSha `
        -ComposeProject $ComposeProject `
        -ImageTag $ImageTag
    Write-TestGateStateFile -Path $statePath -Record $record
    $env:CUSTOMER_AGENT_TEST_GATE_TOKEN = $token
    $script:TestGateHeldMutex = $mutex
    return [pscustomobject]@{
        AcquiredHere   = $true
        Identity       = $identity
        OwnerToken     = $token
        Mutex          = $mutex
        PreviousToken  = $previousToken
        PreviousMutex  = $previousMutex
        Issue          = $Issue
        RunId          = $RunId
        Record         = $record
    }
}

function Exit-TestGateLock {
    param($Holder)
    if ($null -eq $Holder -or -not $Holder.AcquiredHere) {
        return
    }
    try {
        Remove-TestGateStateIfOwner -Identity $Holder.Identity -OwnerToken $Holder.OwnerToken
    } finally {
        if ($env:CUSTOMER_AGENT_TEST_GATE_TOKEN -eq $Holder.OwnerToken) {
            if (-not [string]::IsNullOrWhiteSpace([string]$Holder.PreviousToken)) {
                $env:CUSTOMER_AGENT_TEST_GATE_TOKEN = [string]$Holder.PreviousToken
            } else {
                Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_TOKEN -ErrorAction SilentlyContinue
            }
        }
        $mutex = $Holder.Mutex
        if ($null -eq $mutex) {
            $mutex = $script:TestGateHeldMutex
        }
        if ($null -ne $mutex) {
            try {
                $mutex.ReleaseMutex()
            } catch {
                # 进程即将退出或互斥量已被放弃时，仍须 Dispose。
            }
            $mutex.Dispose()
        }
        if ($null -ne $Holder.PreviousMutex) {
            $script:TestGateHeldMutex = $Holder.PreviousMutex
        } elseif ($script:TestGateHeldMutex -eq $mutex) {
            $script:TestGateHeldMutex = $null
        }
    }
}

function Save-TestGateFullGateEvidence {
    param(
        [Parameter(Mandatory)]$Holder,
        [Parameter(Mandatory)][string]$BaseSha,
        [Parameter(Mandatory)][string]$HeadSha
    )
    $root = Get-TestGateRepoRoot
    $dirty = @(git -C $root status --porcelain)
    $evidence = [pscustomobject]@{
        schemaVersion = $script:TestGateStateVersion
        issue         = $Holder.Issue
        runId         = $Holder.RunId
        baseSha       = $BaseSha
        headSha       = $HeadSha
        dirty         = ($dirty.Count -gt 0)
        recordedAt    = [DateTimeOffset]::Now.ToString('o')
    }
    Write-TestGateStateFile -Path (Get-TestGateEvidencePath $Holder.Identity) -Record $evidence
    return $evidence
}

function Test-TestGateEvidenceCurrent {
    param(
        [string]$LockIdentity,
        [string]$BaseSha,
        [string]$HeadSha
    )
    $identity = Get-TestGateIdentity $LockIdentity
    $evidence = Read-TestGateStateFile (Get-TestGateEvidencePath $identity)
    if ($null -eq $evidence) {
        return $false
    }
    $root = Get-TestGateRepoRoot
    $currentBase = if ($BaseSha) { $BaseSha } else { @(git -C $root rev-parse origin/main 2>$null)[0] }
    $currentHead = if ($HeadSha) { $HeadSha } else { @(git -C $root rev-parse HEAD 2>$null)[0] }
    $dirty = @(git -C $root status --porcelain)
    if ([string]$evidence.baseSha -ne [string]$currentBase) {
        return $false
    }
    if ([string]$evidence.headSha -ne [string]$currentHead) {
        return $false
    }
    if (($dirty.Count -gt 0) -ne [bool]$evidence.dirty) {
        return $false
    }
    if (($dirty.Count -gt 0) -and -not $evidence.dirty) {
        return $false
    }
    if ($dirty.Count -gt 0) {
        return $false
    }
    return $true
}

function Invoke-TestGateHold {
    param(
        [string]$Issue,
        [string]$RunId,
        [string]$CommandType,
        [string]$LockIdentity,
        [string]$ComposeProject,
        [string]$ImageTag,
        [int]$HoldSeconds = 600,
        [switch]$CrashAfterHold
    )
    $holder = Enter-TestGateLock `
        -Issue $Issue `
        -RunId $RunId `
        -CommandType $CommandType `
        -LockIdentity $LockIdentity `
        -ComposeProject $ComposeProject `
        -ImageTag $ImageTag
    try {
        Write-Output 'TEST_GATE_HELD'
        Write-Output "ownerToken=$($holder.OwnerToken)"
        Write-Output "runId=$($holder.RunId)"
        Write-Output "issue=$($holder.Issue)"
        [Console]::Out.Flush()
        if ($CrashAfterHold) {
            [System.Environment]::FailFast('TEST_GATE_CRASH')
        }
        if ($HoldSeconds -lt 1) {
            $HoldSeconds = 1
        }
        Start-Sleep -Seconds $HoldSeconds
    } finally {
        Exit-TestGateLock $holder
    }
}

function Invoke-TestGateLockCli {
    param([object[]]$CliArgs)
    $hold = $false
    $assertInherited = $false
    $help = $false
    $issue = 'manual'
    $runId = $null
    $commandType = 'check'
    $lockIdentity = $null
    $composeProject = $null
    $imageTag = $null
    $holdSeconds = 600
    $crashAfterHold = $false
    $values = @($CliArgs)
    $i = 0
    while ($i -lt $values.Count) {
        $current = [string]$values[$i]
        $next = if (($i + 1) -lt $values.Count) { [string]$values[$i + 1] } else { $null }
        switch ($current) {
            '-Status' { $i++ }
            '-Hold' { $hold = $true; $i++ }
            '-AssertInherited' { $assertInherited = $true; $i++ }
            '-Help' { $help = $true; $i++ }
            '-?' { $help = $true; $i++ }
            '-CrashAfterHold' { $crashAfterHold = $true; $i++ }
            '-Issue' { $issue = $next; $i += 2 }
            '-RunId' { $runId = $next; $i += 2 }
            '-CommandType' { $commandType = $next; $i += 2 }
            '-LockIdentity' { $lockIdentity = $next; $i += 2 }
            '-ComposeProject' { $composeProject = $next; $i += 2 }
            '-ImageTag' { $imageTag = $next; $i += 2 }
            '-HoldSeconds' { $holdSeconds = [int]$next; $i += 2 }
            default { throw "未知参数: $current。使用 -Help 查看用法。" }
        }
    }
    if ($help) {
        Get-Help $PSCommandPath -Full
        return
    }
    if ($assertInherited) {
        Assert-TestGateInherited -LockIdentity $lockIdentity
        Write-Output 'TEST_GATE_INHERITED'
        return
    }
    if ($hold) {
        Invoke-TestGateHold `
            -Issue $issue `
            -RunId $runId `
            -CommandType $commandType `
            -LockIdentity $lockIdentity `
            -ComposeProject $composeProject `
            -ImageTag $imageTag `
            -HoldSeconds $holdSeconds `
            -CrashAfterHold:$crashAfterHold
        return
    }
    Show-TestGateStatus -LockIdentity $lockIdentity
}

if (-not $script:TestGateLockIsDotSourced) {
    Invoke-TestGateLockCli -CliArgs @($args)
}
