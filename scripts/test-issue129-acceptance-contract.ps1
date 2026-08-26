$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot 'deepseek-customer-communication-acceptance.ps1'
$tokens = $null
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {
    throw 'Issue #129 正式验收器无法解析。'
}

$plan = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'issue129-acceptance-plan.psd1')
if (
    [int]$plan.LogicalCallLimit -ne 43 -or
    [int]$plan.ProviderAttemptLimit -ne 49 -or
    [int]$plan.CostLimitMicros -ne 400000 -or
    @($plan.Scenarios).Count -ne 5
) {
    throw 'Issue #129 正式验收计划未冻结批准的调用、尝试、费用或场景上限。'
}
$files = @($plan.Scenarios | ForEach-Object { $_.File })
if (
    $files -contains 'e2e/issue101.cross-role-acceptance.spec.ts' -or
    $files -notcontains 'e2e/issue124.offline-fullstack-readiness.spec.ts' -or
    $files -notcontains 'e2e/issue80.approval-separation.spec.ts' -or
    $files -notcontains 'e2e/issue129.flash-customer-communication.spec.ts'
) {
    throw 'Issue #129 正式验收场景不是批准的五条自包含路径。'
}
$approval = @($plan.Scenarios | Where-Object {
    $_.File -eq 'e2e/issue80.approval-separation.spec.ts'
})
if ($approval.Count -ne 1 -or -not $approval[0].Fixture) {
    throw 'Issue #129 审批隔离路径缺少合成 fixture。'
}

Write-Host 'Issue #129 正式验收器离线契约检查通过。'

$retestScriptPath = Join-Path $PSScriptRoot 'deepseek-clarification-retest.ps1'
$tokens = $null
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile($retestScriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {
    throw 'Issue #129 单路径复验器无法解析。'
}
$retestPlan = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'issue129-clarification-retest-plan.psd1')
if (
    [int]$retestPlan.LogicalCallLimit -ne 11 -or
    [int]$retestPlan.ProviderAttemptLimit -ne 13 -or
    [int]$retestPlan.CostLimitMicros -ne 100000 -or
    $retestPlan.File -ne 'e2e/issue124.offline-fullstack-readiness.spec.ts' -or
    $retestPlan.Title -ne '客户澄清在原工单恢复'
) {
    throw 'Issue #129 单路径复验未冻结批准的路径与硬上限。'
}
$retestSource = Get-Content -LiteralPath $retestScriptPath -Raw
if (
    $retestSource -match 'formal-mode-business-smoke' -or
    $retestSource -match 'issue80\.approval-separation' -or
    $retestSource -match 'issue129\.flash-customer-communication'
) {
    throw 'Issue #129 单路径复验器包含未批准的 smoke 或浏览器路径。'
}

Write-Host 'Issue #129 单路径复验器离线契约检查通过。'
