$script:GateRunLabel = 'com.stellogic.customer-agent.gate.run-id'
$script:GateFingerprintLabel = 'com.stellogic.customer-agent.gate.source-fingerprint'
$script:GateTargetLabel = 'com.stellogic.customer-agent.gate.target'

function Get-GateImageSpecifications {
    param([Parameter(Mandatory)][string]$ImageTag)

    @(
        [pscustomobject]@{ Context = 'backend'; Target = 'test'; Image = "customer-agent/backend-test:$ImageTag" },
        [pscustomobject]@{ Context = 'agent'; Target = 'test'; Image = "customer-agent/agent-test:$ImageTag" },
        [pscustomobject]@{ Context = 'frontend'; Target = 'test'; Image = "customer-agent/frontend-test:$ImageTag" },
        [pscustomobject]@{ Context = 'backend'; Target = 'runtime'; Image = "customer-agent/backend:$ImageTag" },
        [pscustomobject]@{ Context = 'agent'; Target = 'runtime'; Image = "customer-agent/agent:$ImageTag" },
        [pscustomobject]@{ Context = 'frontend'; Target = 'runtime'; Image = "customer-agent/frontend:$ImageTag" },
        [pscustomobject]@{ Context = 'frontend'; Target = 'browser-test'; Image = "customer-agent/frontend-browser-test:$ImageTag" },
        [pscustomobject]@{ Context = 'frontend'; Target = 'browser-server'; Image = "customer-agent/frontend-browser-server:$ImageTag" }
    )
}

function Get-GateSourceFingerprint {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [string[]]$ContextPaths = @('backend', 'agent', 'frontend')
    )

    $root = [System.IO.Path]::GetFullPath($RepoRoot)
    $records = foreach ($contextPath in $ContextPaths) {
        $absoluteContext = Join-Path $root $contextPath
        if (-not (Test-Path -LiteralPath $absoluteContext)) {
            throw "门禁构建上下文不存在: $contextPath"
        }
        foreach ($file in Get-ChildItem -LiteralPath $absoluteContext -Recurse -File) {
            $relative = [System.IO.Path]::GetRelativePath($root, $file.FullName).Replace('\', '/')
            if ($relative -match '(^|/)(\.git|node_modules|build|dist|\.venv|__pycache__|test-results|playwright-report)(/|$)') {
                continue
            }
            "$relative`t$((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
        }
    }
    $payload = (@($records | Sort-Object) -join "`n")
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

function Get-GateImageMetadata {
    param([Parameter(Mandatory)][string]$Image)

    $json = docker image inspect $Image --format '{{json .Config.Labels}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($json)) {
        return $null
    }
    $labels = $json | ConvertFrom-Json -AsHashtable
    @{
        RunId = [string]$labels[$script:GateRunLabel]
        SourceFingerprint = [string]$labels[$script:GateFingerprintLabel]
        Target = [string]$labels[$script:GateTargetLabel]
    }
}

function Assert-GateImages {
    param(
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$SourceFingerprint,
        [scriptblock]$InspectImage = { param($image) Get-GateImageMetadata -Image $image }
    )

    $imageTag = "gate-$RunId"
    foreach ($specification in Get-GateImageSpecifications -ImageTag $imageTag) {
        $metadata = & $InspectImage $specification.Image
        if ($null -eq $metadata) {
            throw "SkipBuild 所需镜像缺失: $($specification.Image)"
        }
        if ([string]$metadata.RunId -cne $RunId) {
            throw "SkipBuild 镜像运行标识不匹配: $($specification.Image)"
        }
        if ([string]$metadata.SourceFingerprint -cne $SourceFingerprint) {
            throw "SkipBuild 镜像源码指纹不匹配: $($specification.Image)"
        }
        if ([string]$metadata.Target -cne $specification.Target) {
            throw "SkipBuild 镜像目标不匹配: $($specification.Image)"
        }
    }
}

function Invoke-GateImageBuilds {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$SourceFingerprint
    )

    $imageTag = "gate-$RunId"
    $results = @()
    foreach ($specification in Get-GateImageSpecifications -ImageTag $imageTag) {
        $existing = Get-GateImageMetadata -Image $specification.Image
        if (
            $null -ne $existing -and
            [string]$existing.RunId -ceq $RunId -and
            [string]$existing.SourceFingerprint -ceq $SourceFingerprint -and
            [string]$existing.Target -ceq $specification.Target
        ) {
            $results += [pscustomobject]@{
                Image = $specification.Image
                Target = $specification.Target
                Seconds = 0
                Reused = $true
            }
            continue
        }
        $arguments = @(
            'build', '--pull=false', '--target', $specification.Target,
            '--label', "$script:GateRunLabel=$RunId",
            '--label', "$script:GateFingerprintLabel=$SourceFingerprint",
            '--label', "$script:GateTargetLabel=$($specification.Target)",
            '--tag', $specification.Image
        )
        if ($specification.Context -eq 'backend' -and $env:CUSTOMER_AGENT_GRADLE_OPTS) {
            $arguments += @('--build-arg', "GRADLE_OPTS=$($env:CUSTOMER_AGENT_GRADLE_OPTS)")
        }
        $arguments += (Join-Path $RepoRoot $specification.Context)
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        & docker @arguments
        $exitCode = $LASTEXITCODE
        $watch.Stop()
        if ($exitCode -ne 0) {
            throw "门禁镜像构建失败: target=$($specification.Target) image=$($specification.Image) exit=$exitCode"
        }
        $results += [pscustomobject]@{
            Image = $specification.Image
            Target = $specification.Target
            Seconds = [math]::Round($watch.Elapsed.TotalSeconds, 3)
            Reused = $false
        }
    }
    Assert-GateImages -RunId $RunId -SourceFingerprint $SourceFingerprint
    @($results)
}

function Remove-GateImages {
    param([Parameter(Mandatory)][string]$RunId)

    foreach ($specification in Get-GateImageSpecifications -ImageTag "gate-$RunId") {
        docker image rm $specification.Image 2>$null | Out-Null
    }
}
