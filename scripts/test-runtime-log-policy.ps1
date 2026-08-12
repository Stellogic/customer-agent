$ErrorActionPreference = 'Stop'
$validator = Join-Path $PSScriptRoot 'assert-runtime-log-policy.ps1'

function Assert-Passes([string]$Name, [string[]]$LogLines) {
    try {
        & $validator -LogLines $LogLines
        Write-Host "PASS: $Name"
    } catch {
        throw "FAIL: $Name 应通过，但被拒绝：$($_.Exception.Message)"
    }
}

function Assert-Rejected([string]$Name, [string[]]$LogLines) {
    try {
        & $validator -LogLines $LogLines
    } catch {
        if ($_.Exception.Message -notmatch '应用正文包含禁止进入产品日志') {
            throw "FAIL: $Name 由非策略错误中断：$($_.Exception.Message)"
        }
        Write-Host "PASS: $Name"
        return
    }
    throw "FAIL: $Name 应被拒绝，但通过了扫描"
}

Assert-Passes 'Compose agent-server 服务前缀属于基础设施元数据' @(
    'agent-server  | application started',
    'agent-server-1  | application started'
)

Assert-Rejected '应用日志正文中的 agent-server 被拒绝' @(
    'spring  | forwarding request to agent-server'
)

Assert-Rejected '应用日志正文中的 agent:2024 被拒绝' @(
    'spring  | internal image agent:2024 selected'
)

foreach ($internalLabel in @('local-spring', 'local-agent', 'local-executor', 'local-postgres')) {
    Assert-Rejected "应用日志正文中的 $internalLabel 被拒绝" @(
        "spring  | connected to $internalLabel"
    )
}

Assert-Rejected '应用日志正文中的 postgresql URI 被拒绝' @(
    'spring  | database=postgresql://app:secret@postgres/customer_agent'
)

Assert-Rejected '既有 contentPatterns 继续拒绝产品日志内容' @(
    'spring  | rawPrompt must not be logged'
)

Assert-Passes '合法 Compose 元数据与应用日志正文通过' @(
    'local-agent  | application started',
    'postgres  | database system is ready to accept connections',
    'spring  | customer ticket projection refreshed',
    'plain legal application log without Compose prefix'
)
