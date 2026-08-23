param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "../docs/specs"),
    [string]$SyncedOn = (Get-Date).ToString("yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"

$issueJson = gh issue list `
    --state all `
    --limit 1000 `
    --json number,title,state,body,url,createdAt,updatedAt,closedAt

if ($LASTEXITCODE -ne 0) {
    throw "Failed to list specification issues from GitHub"
}

$specIssues = @($issueJson |
    ConvertFrom-Json |
    Where-Object { $_.title.StartsWith("[规格]", [System.StringComparison]::Ordinal) } |
    Sort-Object number)

if ($specIssues.Count -eq 0) {
    throw "No GitHub issues with a title starting with [规格] were found"
}

$resolvedOutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($resolvedOutputDirectory) | Out-Null
$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)

$indexEntries = foreach ($issue in $specIssues) {
    $fileName = "issue-$($issue.number).md"
    $filePath = Join-Path $resolvedOutputDirectory $fileName
    $body = $issue.body.TrimEnd()
    $createdAt = ([DateTimeOffset]$issue.createdAt).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $updatedAt = ([DateTimeOffset]$issue.updatedAt).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $document = @"
# $($issue.title)

> 来源：[$($issue.url)]($($issue.url))
> Issue 状态：$($issue.state)
> 创建时间：$createdAt
> 最后更新时间：$updatedAt
> 同步日期：$SyncedOn
> 说明：本文件是 GitHub Issue 正文的只读镜像；项目仍以 GitHub Issue 为规格事实源。

$body
"@

    [System.IO.File]::WriteAllText($filePath, "$($document.TrimEnd())`n", $utf8WithoutBom)
    "- [#$($issue.number) $($issue.title)](./$fileName) — $($issue.state)，最后更新于 $updatedAt"
}

$index = @"
# 历史规格索引

本目录保存 GitHub Issues 中已经形成的规格正文镜像，便于在仓库内检索、评审和随代码版本留档。

## 同步范围

- 包含标题以 ``[规格]`` 开头的所有 GitHub Issue，不区分 ``OPEN`` 或 ``CLOSED``。
- 镜像 Issue 正文，不合并评论、实施票据、Wayfinder 调研或原型记录。
- GitHub Issue 仍是规格事实源；本目录是按日期生成的仓库内快照。

## 规格列表

$($indexEntries -join "`n")

## 刷新方式

在已通过 GitHub CLI 认证的仓库根目录执行：

``````powershell
pwsh ./scripts/sync-spec-docs.ps1
``````
"@

$indexPath = Join-Path $resolvedOutputDirectory "README.md"
[System.IO.File]::WriteAllText($indexPath, "$($index.TrimEnd())`n", $utf8WithoutBom)

Write-Host "Synced $($specIssues.Count) specification issue(s) to $resolvedOutputDirectory"
