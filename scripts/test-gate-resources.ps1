$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'gate-resources.ps1')

$projectName = 'customer-agent-issue80-contract'
$valid = @'
{
  "name": "customer-agent-issue80-contract",
  "volumes": {
    "postgres-data": {"name": "customer-agent-issue80-contract_postgres-data"}
  },
  "networks": {
    "edge": {"name": "customer-agent-issue80-contract_edge"}
  }
}
'@ | ConvertFrom-Json
Assert-ComposeResourcesOwned -ProjectName $projectName -EffectiveConfig $valid

try {
    Get-ComposeProjectResources `
        -ProjectName $projectName `
        -Query { param($kind, $project) [pscustomobject]@{ ExitCode = 1; Values = @() } } | Out-Null
    throw 'Compose 资源查询失败未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '不能判定清理结果') { throw }
}

$shared = $valid | ConvertTo-Json -Depth 10 | ConvertFrom-Json
$shared.volumes.'postgres-data'.name = 'customer-agent-baseline_postgres-data'
try {
    Assert-ComposeResourcesOwned -ProjectName $projectName -EffectiveConfig $shared
    throw '共享卷未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '卷或网络不属于') { throw }
}

Write-Host 'Compose 阶段资源归属契约检查通过。'
