param(
    [AllowEmptyString()]
    [string]$ProjectName,
    [AllowEmptyString()]
    [string]$EffectiveConfigJson,
    [AllowEmptyString()]
    [string]$ImageTag,
    [AllowEmptyString()]
    [string]$FrontendPort
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectName)) {
    throw '执行 destructive Compose reset 前必须显式提供唯一的非 baseline Compose project。'
}

if ($ProjectName -match '^customer-agent-baseline(?:-|$)') {
    throw 'baseline Compose project 禁止执行 destructive reset。'
}
if (
    $ImageTag -notmatch '^gate-[a-z0-9][a-z0-9-]{7,}$' -or
    $ProjectName -cne "customer-agent-$ImageTag"
) {
    throw 'destructive reset 必须使用匹配的唯一 gate project 与镜像 tag。'
}

try {
    $effective = $EffectiveConfigJson | ConvertFrom-Json
} catch {
    throw '无法解析 docker compose config --format json 的读回配置。'
}
if ([string]$effective.name -cne $ProjectName) {
    throw '读回配置的 project name 与显式 project 不一致。'
}

$ownedResourcePrefix = "$ProjectName`_"
$volumeProperties = @($effective.volumes.PSObject.Properties)
$networkProperties = @($effective.networks.PSObject.Properties)
if ($volumeProperties.Count -eq 0 -or $networkProperties.Count -eq 0) {
    throw '读回配置必须包含自有卷和网络。'
}
foreach ($resource in @(
    @($volumeProperties.Value) +
    @($networkProperties.Value)
)) {
    if (-not ([string]$resource.name).StartsWith($ownedResourcePrefix, [StringComparison]::Ordinal)) {
        throw '读回配置的卷或网络不属于显式 gate project。'
    }
}

foreach ($service in @($effective.services.PSObject.Properties.Value)) {
    $image = [string]$service.image
    if ($image.StartsWith('customer-agent/', [StringComparison]::Ordinal) -and -not $image.EndsWith(":$ImageTag", [StringComparison]::Ordinal)) {
        throw '读回配置的服务镜像不属于显式 gate tag。'
    }
}

$publishedFrontendPort = [string]@($effective.services.frontend.ports)[0].published
if (
    $FrontendPort -notmatch '^[0-9]+$' -or
    $FrontendPort -eq '4180' -or
    $publishedFrontendPort -cne $FrontendPort
) {
    throw '读回配置的前端端口未显式隔离。'
}
