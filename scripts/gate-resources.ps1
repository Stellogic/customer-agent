function Get-ComposeProjectResources {
    param(
        [Parameter(Mandatory)][string]$ProjectName,
        [scriptblock]$Query = {
            param($kind, $project)
            $values = switch ($kind) {
                'containers' { @(docker ps --all --quiet --filter "label=com.docker.compose.project=$project") }
                'volumes' { @(docker volume ls --quiet --filter "label=com.docker.compose.project=$project") }
                'networks' { @(docker network ls --quiet --filter "label=com.docker.compose.project=$project") }
            }
            [pscustomobject]@{ ExitCode = $LASTEXITCODE; Values = @($values) }
        }
    )

    $resources = @()
    foreach ($kind in @('containers', 'volumes', 'networks')) {
        $result = & $Query $kind $ProjectName
        if ($result.ExitCode -ne 0) {
            throw "无法查询 Compose $kind，不能判定清理结果: project=$ProjectName"
        }
        $resources += @($result.Values)
    }
    @($resources)
}

function Assert-ComposeProjectResourcesEmpty {
    param(
        [Parameter(Mandatory)][string]$ProjectName,
        [Parameter(Mandatory)][string]$Phase
    )

    $resources = @(Get-ComposeProjectResources -ProjectName $ProjectName)
    if ($resources.Count -ne 0) {
        throw "Compose 隔离资源${Phase}非空: project=$ProjectName resources=$($resources -join ',')"
    }
}

function Assert-ComposeResourcesOwned {
    param(
        [Parameter(Mandatory)][string]$ProjectName,
        [Parameter(Mandatory)]$EffectiveConfig
    )

    $ownedPrefix = "$ProjectName`_"
    $volumes = @($EffectiveConfig.volumes.PSObject.Properties.Value)
    $networks = @($EffectiveConfig.networks.PSObject.Properties.Value)
    if ($volumes.Count -eq 0 -or $networks.Count -eq 0) {
        throw '有效 Compose 配置必须包含阶段自有卷和网络。'
    }
    foreach ($resource in @($volumes + $networks)) {
        if (-not ([string]$resource.name).StartsWith($ownedPrefix, [StringComparison]::Ordinal)) {
            throw "有效 Compose 配置的卷或网络不属于阶段 project: $ProjectName"
        }
    }
}
