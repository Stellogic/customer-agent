function Get-ComposeProjectResources {
    param([Parameter(Mandatory)][string]$ProjectName)

    @(
        @(docker ps --all --quiet --filter "label=com.docker.compose.project=$ProjectName") +
        @(docker volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName") +
        @(docker network ls --quiet --filter "label=com.docker.compose.project=$ProjectName")
    )
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
