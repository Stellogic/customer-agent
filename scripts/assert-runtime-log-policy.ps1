param(
    [Parameter(Mandatory)]
    [AllowEmptyCollection()]
    [string[]]$LogLines,
    [string]$RulesPath = (Join-Path $PSScriptRoot '../frontend/src/sensitive-content-patterns.json')
)

$ErrorActionPreference = 'Stop'
$rules = Get-Content -Raw -LiteralPath $RulesPath | ConvertFrom-Json
$forbiddenPattern = (@($rules.contentPatterns) + @($rules.internalAddressPatterns)) -join '|'

for ($index = 0; $index -lt $LogLines.Count; $index++) {
    $line = $LogLines[$index]
    $applicationContent = if ($line -match '^[A-Za-z0-9][A-Za-z0-9_.-]*\s+\|\s?(?<content>.*)$') {
        $Matches.content
    } else {
        $line
    }

    if ($applicationContent -match $forbiddenPattern) {
        throw "运行日志第 $($index + 1) 行的应用正文包含禁止进入产品日志的敏感或内部标识"
    }
}
