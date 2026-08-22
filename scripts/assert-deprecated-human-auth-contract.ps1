$ErrorActionPreference = "Stop"

$legacyHeaders = 'X-Synthetic-(Customer|Support|Approver)-Id'
$runtimeMatches = & rg -n -i $legacyHeaders backend/src/main agent frontend/src `
    --glob '!*.test.ts' --glob '!*.test.tsx'
if ($LASTEXITCODE -eq 0) {
    throw "产品运行路径仍包含已废弃的合成人工身份头：`n$($runtimeMatches -join "`n")"
}
if ($LASTEXITCODE -ne 1) {
    throw "扫描产品运行路径失败，rg exit code: $LASTEXITCODE"
}

$legacyEntryMatches = & rg -n -i '/api/demo|synthetic-demo-session' README.md agent backend/src/main frontend/src docs/demo
if ($LASTEXITCODE -eq 0) {
    throw "产品、演示或入口文档仍包含旧合成人工身份入口：`n$($legacyEntryMatches -join "`n")"
}
if ($LASTEXITCODE -ne 1) {
    throw "扫描旧身份入口失败，rg exit code: $LASTEXITCODE"
}

Write-Host "PASS: 产品运行路径、演示与入口文档不再接受旧合成人工身份契约"
