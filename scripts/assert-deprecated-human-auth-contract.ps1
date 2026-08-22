$ErrorActionPreference = "Stop"

$legacyHeaders = 'X-Synthetic-(Customer|Support|Approver)-Id'
$headerMatches = @(& rg -n -i $legacyHeaders .)
if ($LASTEXITCODE -notin @(0, 1)) {
    throw "扫描仓库旧人工身份头失败，rg exit code: $LASTEXITCODE"
}
$negativeHeaderTestAllowlist = @(
    'backend/src/test/java/com/stellogic/customeragent/ticket/CustomerTicketPrincipalSecurityTest.java',
    'backend/src/test/java/com/stellogic/customeragent/sla/SupportSlaPrincipalSecurityTest.java',
    'backend/src/test/java/com/stellogic/customeragent/queue/SupportPrincipalSecurityTest.java',
    'backend/src/test/java/com/stellogic/customeragent/approval/ApprovalCoarseSecurityTest.java',
    'backend/src/test/java/com/stellogic/customeragent/identity/HumanApiNegativeMatrixTest.java',
    'frontend/src/App.test.tsx',
    'frontend/src/SupportWorkbench.test.tsx',
    'frontend/src/ApprovalWorkbench.test.tsx'
)
$unexpectedHeaderMatches = @($headerMatches | Where-Object {
    $normalized = ($_ -split ':', 2)[0].TrimStart('.', '/', '\').Replace('\', '/')
    $normalized -notin $negativeHeaderTestAllowlist
})
if ($unexpectedHeaderMatches.Count -gt 0) {
    throw "旧人工身份头只允许存在于明确的伪造攻击或不发送断言中：`n$($unexpectedHeaderMatches -join "`n")"
}

$legacyEntryMatches = @(& rg -n -i '/api/demo|synthetic-demo-session' .)
if ($LASTEXITCODE -notin @(0, 1)) {
    throw "扫描旧身份入口失败，rg exit code: $LASTEXITCODE"
}
$legacyEntryAllowlist = @(
    'docs/decisions/0002-static-react-shell-stack.md',
    'docs/delivery/issue-79-verification.md',
    'scripts/assert-deprecated-human-auth-contract.ps1'
)
$unexpectedLegacyEntries = @($legacyEntryMatches | Where-Object {
    $normalized = ($_ -split ':', 2)[0].TrimStart('.', '/', '\').Replace('\', '/')
    $normalized -notin $legacyEntryAllowlist
})
if ($unexpectedLegacyEntries.Count -gt 0) {
    throw "旧身份入口只允许存在于明确废弃的历史说明和扫描器自身：`n$($unexpectedLegacyEntries -join "`n")"
}

Write-Host "PASS: 产品运行路径、演示与入口文档不再接受旧合成人工身份契约"
