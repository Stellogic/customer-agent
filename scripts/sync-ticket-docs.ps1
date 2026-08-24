param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "../docs/tickets"),
    [string]$SyncedOn = (Get-Date).ToString("yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"

$issueJson = gh issue list `
    --state all `
    --limit 1000 `
    --json number,title,state,body,url,createdAt,updatedAt,closedAt

if ($LASTEXITCODE -ne 0) {
    throw "Failed to list implementation tickets from GitHub"
}

$issues = @($issueJson | ConvertFrom-Json)
$specIssuesByNumber = @{}

foreach ($issue in $issues) {
    if ($issue.title.StartsWith("[规格]", [System.StringComparison]::Ordinal)) {
        $specIssuesByNumber[[int]$issue.number] = $issue
    }
}

function Get-ParentIssueNumber {
    param([string]$Body)

    $lines = @($Body -split "\r?\n")
    for ($lineIndex = 0; $lineIndex -lt $lines.Count; $lineIndex++) {
        if ($lines[$lineIndex].Trim() -ne "## Parent") {
            continue
        }

        for ($parentIndex = $lineIndex + 1; $parentIndex -lt $lines.Count; $parentIndex++) {
            if ([string]::IsNullOrWhiteSpace($lines[$parentIndex])) {
                continue
            }

            $parentMatch = [regex]::Match(
                $lines[$parentIndex].Trim(),
                "^(?:-\s*)?(?:Part of\s*)?#(\d+)\s*$"
            )
            if ($parentMatch.Success) {
                return [int]$parentMatch.Groups[1].Value
            }

            break
        }
    }

    $partOfMatch = [regex]::Match($Body, "(?im)^Part of #(\d+)\s*$")
    if ($partOfMatch.Success) {
        return [int]$partOfMatch.Groups[1].Value
    }

    return $null
}

function Get-MarkdownLinkLabel {
    param([string]$Text)

    return [regex]::Replace($Text, "\[([^\]]+)\]", '$1')
}

$ticketRecords = @(
    foreach ($issue in $issues) {
        $parentNumber = Get-ParentIssueNumber -Body $issue.body
        if ($null -eq $parentNumber -or -not $specIssuesByNumber.ContainsKey($parentNumber)) {
            continue
        }

        [pscustomobject]@{
            ParentNumber = $parentNumber
            Issue        = $issue
        }
    }
) | Sort-Object ParentNumber, { $_.Issue.number }

if ($ticketRecords.Count -eq 0) {
    throw "No implementation tickets with a formal [规格] parent were found"
}

$resolvedOutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($resolvedOutputDirectory) | Out-Null
$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
$expectedTicketPaths = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)

foreach ($record in $ticketRecords) {
    $issue = $record.Issue
    $parentNumber = $record.ParentNumber
    $parentIssue = $specIssuesByNumber[$parentNumber]
    $parentDisplayTitle = Get-MarkdownLinkLabel -Text $parentIssue.title
    $parentDirectory = Join-Path $resolvedOutputDirectory "spec-$parentNumber"
    [System.IO.Directory]::CreateDirectory($parentDirectory) | Out-Null

    $fileName = "issue-$($issue.number).md"
    $filePath = Join-Path $parentDirectory $fileName
    [void]$expectedTicketPaths.Add([System.IO.Path]::GetFullPath($filePath))

    $issueState = [string]$issue.state
    $issueTitle = [string]$issue.title
    $issueUrl = [string]$issue.url
    $createdAt = ([DateTimeOffset]$issue.createdAt).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $updatedAt = ([DateTimeOffset]$issue.updatedAt).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $closedAt = if ($null -eq $issue.closedAt) {
        "—"
    }
    else {
        ([DateTimeOffset]$issue.closedAt).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    }
    $body = $issue.body.TrimEnd()
    $document = @"
# $issueTitle

> 父规格：[#$parentNumber $parentDisplayTitle](../../specs/issue-$parentNumber.md)
> 来源：[$issueUrl]($issueUrl)
> Issue 状态：$issueState
> 创建时间：$createdAt
> 最后更新时间：$updatedAt
> 关闭时间：$closedAt
> 同步日期：$SyncedOn
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

$body
"@

    [System.IO.File]::WriteAllText($filePath, "$($document.TrimEnd())`n", $utf8WithoutBom)
}

foreach ($existingDirectory in Get-ChildItem -LiteralPath $resolvedOutputDirectory -Directory -Filter "spec-*") {
    foreach ($existingFile in Get-ChildItem -LiteralPath $existingDirectory.FullName -File -Filter "issue-*.md") {
        if (-not $expectedTicketPaths.Contains($existingFile.FullName)) {
            Remove-Item -LiteralPath $existingFile.FullName
        }
    }
}

$indexSections = foreach ($parentGroup in $ticketRecords | Group-Object ParentNumber | Sort-Object Name) {
    $parentNumber = [int]$parentGroup.Name
    $parentIssue = $specIssuesByNumber[$parentNumber]
    $parentDisplayTitle = Get-MarkdownLinkLabel -Text $parentIssue.title
    $entries = foreach ($record in $parentGroup.Group | Sort-Object { $_.Issue.number }) {
        $issue = $record.Issue
        $issueDisplayTitle = Get-MarkdownLinkLabel -Text $issue.title
        $updatedAt = ([DateTimeOffset]$issue.updatedAt).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        "- [#$($issue.number) $issueDisplayTitle](./spec-$parentNumber/issue-$($issue.number).md) — $($issue.state)，最后更新于 $updatedAt"
    }

    @"
## 父规格 [#$parentNumber $parentDisplayTitle](../specs/issue-$parentNumber.md)

$($entries -join "`n")
"@
}

$index = @"
# 历史实施票据索引

本目录保存明确归属于正式 ``[规格]`` 父 Issue 的 GitHub 实施与验收票据正文镜像，便于在仓库内按父规格检索交付历史。

## 同步范围

- 父级必须能从票据正文的 ``## Parent`` 或 ``Part of #...`` 声明中确定。
- 父 Issue 的标题必须以 ``[规格]`` 开头。
- 镜像票据正文，不合并评论或 PR 讨论，也不镜像没有正式父规格的普通 Issue 或临时 Bug。
- GitHub Issue 仍是票据事实源；父规格、已接受 ADR 和当前产品契约的约束优先于历史票据。

$($indexSections -join "`n`n")

## 刷新方式

在已通过 GitHub CLI 认证的仓库根目录执行：

``````powershell
pwsh ./scripts/sync-ticket-docs.ps1
``````
"@

$indexPath = Join-Path $resolvedOutputDirectory "README.md"
[System.IO.File]::WriteAllText($indexPath, "$($index.TrimEnd())`n", $utf8WithoutBom)

Write-Host "Synced $($ticketRecords.Count) implementation ticket(s) to $resolvedOutputDirectory"
