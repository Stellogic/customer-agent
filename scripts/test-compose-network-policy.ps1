$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $effective = docker compose config --format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw 'Compose 网络策略无法解析。'
    }

    foreach ($network in @('data', 'services')) {
        if ($effective.networks.$network.internal -ne $true) {
            throw "Compose $network 网络必须保持 internal。"
        }
    }
    if ($effective.networks.'provider-egress'.internal -eq $true) {
        throw 'Compose provider-egress 网络不能设为 internal。'
    }

    $egressConsumers = @(
        $effective.services.PSObject.Properties |
            Where-Object {
                $_.Value.networks.PSObject.Properties.Name -contains 'provider-egress'
            } |
            ForEach-Object Name
    )
    if ($egressConsumers.Count -ne 1 -or $egressConsumers[0] -ne 'agent-server') {
        throw 'Compose provider-egress 网络只能由 agent-server 使用。'
    }

    $agentNetworks = @($effective.services.'agent-server'.networks.PSObject.Properties.Name)
    foreach ($required in @('data', 'services', 'provider-egress')) {
        if ($agentNetworks -notcontains $required) {
            throw "Compose agent-server 缺少 $required 网络。"
        }
    }
} finally {
    Pop-Location
}

Write-Output 'Compose 网络策略检查通过。'
