function Assert-BrowserAcceptancePlan {
    param(
        [Parameter(Mandatory)][string[]]$DiscoveredFiles,
        [Parameter(Mandatory)][string[]]$ParallelSafe,
        [Parameter(Mandatory)][string[]]$Serial,
        [Parameter(Mandatory)][string[]]$Excluded
    )

    $classified = @($ParallelSafe + $Serial + $Excluded)
    $duplicates = @($classified | Group-Object | Where-Object Count -gt 1 | ForEach-Object Name)
    if ($duplicates.Count -ne 0) {
        throw "浏览器测试重复分类: $($duplicates -join ', ')"
    }
    $unknown = @($classified | Where-Object { $DiscoveredFiles -notcontains $_ })
    if ($unknown.Count -ne 0) {
        throw "浏览器测试清单包含不存在的文件: $($unknown -join ', ')"
    }
    $unclassified = @($DiscoveredFiles | Where-Object { $classified -notcontains $_ })
    if ($unclassified.Count -ne 0) {
        throw "发现未分类的浏览器测试: $($unclassified -join ', ')"
    }
    if ($ParallelSafe.Count -lt 2) {
        throw 'parallel-safe 组至少需要两个独立文件才能证明 workers=2。'
    }
}

function Invoke-PlaywrightGroup {
    param(
        [Parameter(Mandatory)][string[]]$Files,
        [Parameter(Mandatory)][ValidateRange(1, 2)][int]$Workers,
        [ValidateRange(1, 3)][int]$RepeatCount = 1,
        [Parameter(Mandatory)][scriptblock]$Runner
    )

    for ($attempt = 1; $attempt -le $RepeatCount; $attempt++) {
        $exitCode = & $Runner $Files $Workers $attempt
        if ($exitCode -ne 0) {
            throw "Playwright 组第 $attempt 次运行失败，workers=$Workers，退出码: $exitCode"
        }
    }
}

function Assert-ParallelSafeBrowserTests {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string[]]$Files,
        [scriptblock]$ReadSource = { param($path) Get-Content -LiteralPath $path -Raw }
    )

    $forbiddenPattern = 'support/(auth|database)|\.click\s*\(|\.fill\s*\(|waitForResponse|request\(\)\.method\(\)\s*===\s*["''](?:POST|PUT|PATCH|DELETE)'
    foreach ($file in $Files) {
        $path = Join-Path (Join-Path $RepoRoot 'frontend') $file
        $source = & $ReadSource $path
        if ($source -match $forbiddenPattern) {
            throw "parallel-safe 文件包含 Session、共享数据库或写操作证据: $file"
        }
    }
}
