$ErrorActionPreference = 'Stop'

$helper = Join-Path $PSScriptRoot 'browser-acceptance-plan.ps1'
. $helper

$plan = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'browser-acceptance-plan.psd1')
$discovered = @(
    Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot '..\frontend\e2e') -File -Filter '*.spec.ts' |
        ForEach-Object { "e2e/$($_.Name)" }
)
Assert-BrowserAcceptancePlan `
    -DiscoveredFiles $discovered `
    -ParallelSafe $plan.ParallelSafe `
    -Serial $plan.Serial `
    -Excluded $plan.Excluded.Keys
Assert-ParallelSafeBrowserTests -RepoRoot (Join-Path $PSScriptRoot '..') -Files $plan.ParallelSafe

try {
    Assert-ParallelSafeBrowserTests `
        -RepoRoot (Join-Path $PSScriptRoot '..') `
        -Files @('e2e/unsafe.spec.ts') `
        -ReadSource { param($path) 'import "./support/database"; page.click();' }
    throw 'parallel-safe 写操作未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '包含 Session、共享数据库或写操作') { throw }
}

foreach ($case in @(
    @{ Name = '遗漏'; Parallel = @($plan.ParallelSafe | Select-Object -Skip 1); Serial = $plan.Serial; Excluded = $plan.Excluded.Keys; Pattern = '未分类' },
    @{ Name = '重复'; Parallel = @($plan.ParallelSafe); Serial = @($plan.Serial + $plan.ParallelSafe[0]); Excluded = $plan.Excluded.Keys; Pattern = '重复分类' },
    @{ Name = '未知'; Parallel = @($plan.ParallelSafe + 'e2e/not-real.spec.ts'); Serial = $plan.Serial; Excluded = $plan.Excluded.Keys; Pattern = '不存在' }
)) {
    try {
        Assert-BrowserAcceptancePlan `
            -DiscoveredFiles $discovered `
            -ParallelSafe $case.Parallel `
            -Serial $case.Serial `
            -Excluded $case.Excluded
        throw "$($case.Name)分类未 fail closed。"
    } catch {
        if ($_.Exception.Message -notmatch $case.Pattern) { throw }
    }
}

$attempts = 0
try {
    Invoke-PlaywrightGroup `
        -Files $plan.ParallelSafe `
        -Workers 2 `
        -RepeatCount 3 `
        -Runner {
            param($files, $workers, $attempt)
            $script:attempts += 1
            Write-Output "attempt-$attempt-output"
            if ($attempt -eq 2) { return 17 }
            return 0
        }
    throw '并行组失败未阻止后续运行。'
} catch {
    if ($_.Exception.Message -notmatch '第 2 次.*退出码: 17') { throw }
}
if ($attempts -ne 2) {
    throw "并行组失败后仍继续执行，实际调用次数: $attempts"
}

Write-Host '浏览器验收清单与失败传播契约检查通过。'
