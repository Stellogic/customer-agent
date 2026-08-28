$ErrorActionPreference = 'Stop'

$validator = Join-Path $PSScriptRoot 'assert-compose-reset-isolation.ps1'

try {
    & $validator -ProjectName '' -EffectiveConfigJson '{}'
    throw '缺失显式 Compose project 时未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '必须显式提供唯一的非 baseline Compose project') {
        throw
    }
}

foreach ($reservedProject in @('customer-agent-baseline', 'customer-agent-baseline-retry')) {
    try {
        & $validator -ProjectName $reservedProject -EffectiveConfigJson '{}'
        throw "保留 Compose project $reservedProject 未 fail closed。"
    } catch {
        if ($_.Exception.Message -notmatch 'baseline Compose project 禁止执行 destructive reset') {
            throw
        }
    }
}

try {
    & $validator `
        -ProjectName 'customer-agent-gate-12345678' `
        -ImageTag 'gate-12345678' `
        -FrontendPort '43929' `
        -EffectiveConfigJson '{"name":"another-project"}'
    throw 'Compose 配置读回的 project 不一致时未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '读回配置的 project name 与显式 project 不一致') {
        throw
    }
}

try {
    & $validator `
        -ProjectName 'customer-agent-main-preview' `
        -ImageTag 'local' `
        -FrontendPort '4180' `
        -EffectiveConfigJson '{"name":"customer-agent-main-preview"}'
    throw '非专用 destructive gate namespace 未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '必须使用匹配的唯一 gate project 与镜像 tag') {
        throw
    }
}

try {
    & $validator `
        -ProjectName 'customer-agent-gate-12345678' `
        -ImageTag 'gate-12345678' `
        -FrontendPort '43929' `
        -EffectiveConfigJson '{"name":"customer-agent-gate-12345678","volumes":{"postgres-data":{"name":"customer-agent-baseline_postgres-data"}},"networks":{"services":{"name":"customer-agent-gate-12345678_services"}}}'
    throw '读回配置包含非自有卷时未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '卷或网络不属于显式 gate project') {
        throw
    }
}

$wrongImageConfig = @'
{
  "name": "customer-agent-gate-12345678",
  "services": {
    "frontend": {
      "image": "customer-agent/frontend:local",
      "ports": [{"published": "43929", "target": 8080}]
    }
  },
  "volumes": {"postgres-data": {"name": "customer-agent-gate-12345678_postgres-data"}},
  "networks": {"services": {"name": "customer-agent-gate-12345678_services"}}
}
'@
try {
    & $validator `
        -ProjectName 'customer-agent-gate-12345678' `
        -ImageTag 'gate-12345678' `
        -FrontendPort '43929' `
        -EffectiveConfigJson $wrongImageConfig
    throw '读回配置包含非自有镜像 tag 时未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '服务镜像不属于显式 gate tag') {
        throw
    }
}

$wrongPortConfig = $wrongImageConfig.Replace('customer-agent/frontend:local', 'customer-agent/frontend:gate-12345678').Replace('43929', '4180')
try {
    & $validator `
        -ProjectName 'customer-agent-gate-12345678' `
        -ImageTag 'gate-12345678' `
        -FrontendPort '43929' `
        -EffectiveConfigJson $wrongPortConfig
    throw '读回配置的前端端口不一致时未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '前端端口未显式隔离') {
        throw
    }
}

$isolatedConfig = $wrongImageConfig.Replace('customer-agent/frontend:local', 'customer-agent/frontend:gate-12345678')
& $validator `
    -ProjectName 'customer-agent-gate-12345678' `
    -ImageTag 'gate-12345678' `
    -FrontendPort '43929' `
    -EffectiveConfigJson $isolatedConfig

$emptyResourcesConfig = $isolatedConfig.Replace(
    '"volumes": {"postgres-data": {"name": "customer-agent-gate-12345678_postgres-data"}},',
    '"volumes": {},'
).Replace(
    '"networks": {"services": {"name": "customer-agent-gate-12345678_services"}}',
    '"networks": {}'
)
try {
    & $validator `
        -ProjectName 'customer-agent-gate-12345678' `
        -ImageTag 'gate-12345678' `
        -FrontendPort '43929' `
        -EffectiveConfigJson $emptyResourcesConfig
    throw '读回配置缺少卷或网络时未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '必须包含自有卷和网络') {
        throw
    }
}

$smokeSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'smoke.ps1') -Raw
$smokeGuardIndex = $smokeSource.IndexOf('confirm-compose-reset-isolation.ps1', [StringComparison]::Ordinal)
$destructiveDownIndex = $smokeSource.IndexOf(
    'docker compose -p $projectName down --volumes --remove-orphans',
    [StringComparison]::Ordinal
)
if ($smokeGuardIndex -lt 0 -or $destructiveDownIndex -le $smokeGuardIndex) {
    throw 'smoke -Reset 未在显式隔离配置读回后限定 destructive down 的 project。'
}

$checkSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'check.ps1') -Raw
$checkGuardIndex = $checkSource.IndexOf('confirm-compose-reset-isolation.ps1', [StringComparison]::Ordinal)
$firstBuildIndex = $checkSource.IndexOf('docker build', [StringComparison]::Ordinal)
if ($checkGuardIndex -lt 0 -or $firstBuildIndex -le $checkGuardIndex) {
    throw '完整规范门禁未在 Docker 构建与验收前执行隔离配置读回。'
}

$confirmationSource = Get-Content -LiteralPath (
    Join-Path $PSScriptRoot 'confirm-compose-reset-isolation.ps1'
) -Raw
if (
    $confirmationSource -notmatch 'docker compose -p \$ProjectName config --format json' -or
    $confirmationSource -notmatch 'assert-compose-reset-isolation\.ps1'
) {
    throw 'Compose reset 预检未读回有效配置并交由 fail-closed 验证器。'
}

foreach ($script in Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter '*.ps1') {
    $source = Get-Content -LiteralPath $script.FullName -Raw
    $downIndex = $source.IndexOf('docker compose down --volumes', [StringComparison]::Ordinal)
    if ($downIndex -lt 0) {
        continue
    }
    $confirmationIndex = $source.IndexOf('confirm-compose-reset-isolation.ps1', [StringComparison]::Ordinal)
    $configReadbackIndex = $source.IndexOf('config --format json', [StringComparison]::Ordinal)
    $guardIndex = [Math]::Max($confirmationIndex, $configReadbackIndex)
    if (
        $guardIndex -lt 0 -or
        $guardIndex -ge $downIndex -or
        $source -notmatch 'COMPOSE_PROJECT_NAME'
    ) {
        throw "包含 destructive reset 的脚本未先验证显式 Compose project: $($script.Name)"
    }
}

$workflowRoot = Join-Path $PSScriptRoot '..\.github\workflows'
$remoteGatePattern = 'scripts[\\/](check|smoke)\.ps1'
foreach ($forbiddenInvocation in @('./scripts/check.ps1', '.\scripts\smoke.ps1')) {
    if ($forbiddenInvocation -notmatch $remoteGatePattern) {
        throw "远端门禁 workflow 检测未覆盖路径写法: $forbiddenInvocation"
    }
}
foreach ($allowedInvocation in @('./scripts/check-doc-links.ps1', 'pwsh ./scripts/local-smoke-helper.ps1')) {
    if ($allowedInvocation -match $remoteGatePattern) {
        throw "远端门禁 workflow 检测误伤非规范化入口: $allowedInvocation"
    }
}
if (Test-Path -LiteralPath $workflowRoot) {
    foreach ($workflow in Get-ChildItem -LiteralPath $workflowRoot -File) {
        $workflowSource = Get-Content -LiteralPath $workflow.FullName -Raw
        if ($workflowSource -match $remoteGatePattern) {
            throw "GitHub Actions 自动测试已关闭，但仍发现远端门禁 workflow: $($workflow.Name)"
        }
    }
}

Write-Host 'Compose reset 隔离契约检查通过。'
