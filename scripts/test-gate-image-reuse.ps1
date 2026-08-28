$ErrorActionPreference = 'Stop'

$helper = Join-Path $PSScriptRoot 'gate-images.ps1'
. $helper

$runId = 'issue182-test-1234'
$fingerprint = 'abc123fingerprint'
$specifications = @(Get-GateImageSpecifications -ImageTag "gate-$runId")
if ($specifications.Count -ne 8) {
    throw "完整门禁应声明 8 个唯一 test/runtime 镜像目标，实际为 $($specifications.Count)。"
}
if (@($specifications | ForEach-Object { "$($_.Context):$($_.Target)" } | Sort-Object -Unique).Count -ne $specifications.Count) {
    throw '完整门禁的镜像目标存在重复构建声明。'
}

$validMetadata = @{}
foreach ($specification in $specifications) {
    $validMetadata[$specification.Image] = @{
        RunId = $runId
        SourceFingerprint = $fingerprint
        Target = $specification.Target
    }
}

Assert-GateImages `
    -RunId $runId `
    -SourceFingerprint $fingerprint `
    -InspectImage { param($image) $validMetadata[$image] }

Assert-GateImagesAbsent -RunId $runId -InspectImage { param($image) $null }
try {
    Assert-GateImagesAbsent -RunId $runId -InspectImage { param($image) $validMetadata[$image] }
    throw '残留门禁镜像未 fail closed。'
} catch {
    if ($_.Exception.Message -notmatch '清理回读非空') { throw }
}

foreach ($case in @(
    @{ Name = '镜像缺失'; Mutate = { param($metadata, $image) $metadata.Remove($image) | Out-Null }; Pattern = '缺失' },
    @{ Name = '运行标识不匹配'; Mutate = { param($metadata, $image) $metadata[$image].RunId = 'another-run' }; Pattern = '运行标识不匹配' },
    @{ Name = '源码指纹不匹配'; Mutate = { param($metadata, $image) $metadata[$image].SourceFingerprint = 'stale' }; Pattern = '源码指纹不匹配' }
)) {
    $metadata = @{}
    foreach ($key in $validMetadata.Keys) { $metadata[$key] = $validMetadata[$key].Clone() }
    $firstImage = $specifications[0].Image
    & $case.Mutate $metadata $firstImage
    try {
        Assert-GateImages `
            -RunId $runId `
            -SourceFingerprint $fingerprint `
            -InspectImage { param($image) $metadata[$image] }
        throw "$($case.Name) 未 fail closed。"
    } catch {
        if ($_.Exception.Message -notmatch $case.Pattern) { throw }
    }
}

$fingerprintRoot = Join-Path ([System.IO.Path]::GetTempPath()) "issue182-fingerprint-$([guid]::NewGuid().ToString('N'))"
try {
    New-Item -ItemType Directory -Path (Join-Path $fingerprintRoot 'frontend') | Out-Null
    Set-Content -LiteralPath (Join-Path $fingerprintRoot 'frontend/Dockerfile') -Value 'FROM scratch'
    Set-Content -LiteralPath (Join-Path $fingerprintRoot 'frontend/package-lock.json') -Value '{"lockfileVersion":3}'
    $before = Get-GateSourceFingerprint -RepoRoot $fingerprintRoot -ContextPaths @('frontend')
    Set-Content -LiteralPath (Join-Path $fingerprintRoot 'frontend/package-lock.json') -Value '{"lockfileVersion":4}'
    $after = Get-GateSourceFingerprint -RepoRoot $fingerprintRoot -ContextPaths @('frontend')
    if ($before -eq $after) {
        throw '锁文件变化后源码指纹未失效。'
    }
} finally {
    Remove-Item -LiteralPath $fingerprintRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host '完整门禁镜像复用契约检查通过。'
