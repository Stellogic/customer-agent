param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$runId = [guid]::NewGuid().ToString('N').Substring(0, 12)
$projectName = "customer-agent-issue80-$runId"
$imageTag = "issue80-$runId"
$portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$portProbe.Start()
$frontendPort = $portProbe.LocalEndpoint.Port
$portProbe.Stop()

$env:CUSTOMER_AGENT_IMAGE_TAG = $imageTag
$env:CUSTOMER_AGENT_FRONTEND_PORT = [string]$frontendPort
$env:SESSION_COOKIE_SECURE = 'true'
$ownedImages = @(
    "customer-agent/backend:$imageTag",
    "customer-agent/agent:$imageTag",
    "customer-agent/frontend:$imageTag",
    "customer-agent/frontend-browser-test:$imageTag",
    "customer-agent/frontend-browser-server:$imageTag"
)

function Get-ProjectContainers {
    @(docker ps --all --quiet --filter "label=com.docker.compose.project=$projectName")
}

function Get-ProjectVolumes {
    @(docker volume ls --quiet --filter "label=com.docker.compose.project=$projectName")
}

function Get-ProjectNetworks {
    @(docker network ls --quiet --filter "label=com.docker.compose.project=$projectName")
}

function Get-OwnedImages {
    $existingImages = @(docker image ls --format '{{.Repository}}:{{.Tag}}')
    @($ownedImages | Where-Object { $existingImages -contains $_ })
}

function Get-IsolatedResourceSnapshot {
    [pscustomobject]@{
        Containers = @(Get-ProjectContainers)
        Volumes    = @(Get-ProjectVolumes)
        Networks   = @(Get-ProjectNetworks)
        Images     = @(Get-OwnedImages)
    }
}

function Assert-IsolatedResourcesEmpty {
    param(
        [Parameter(Mandatory)]$Snapshot,
        [Parameter(Mandatory)][string]$Phase
    )

    if (
        $Snapshot.Containers.Count -ne 0 -or
        $Snapshot.Volumes.Count -ne 0 -or
        $Snapshot.Networks.Count -ne 0 -or
        $Snapshot.Images.Count -ne 0
    ) {
        throw "Issue #80 隔离资源${Phase}非空: project=$projectName containers=$($Snapshot.Containers -join ',') volumes=$($Snapshot.Volumes -join ',') networks=$($Snapshot.Networks -join ',') images=$($Snapshot.Images -join ',')"
    }
}

function Invoke-BoundedBuild {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $build = Start-Process -FilePath 'docker' -ArgumentList @(
                'compose', '--project-name', $projectName, '--profile', 'smoke', 'build'
            ) -NoNewWindow -PassThru
            try {
                $build | Wait-Process -Timeout 900 -ErrorAction Stop
            } catch {
                Stop-Process -Id $build.Id -Force -ErrorAction SilentlyContinue
                throw 'Issue #80 镜像构建超过 900 秒有界超时'
            }
            if ($build.ExitCode -ne 0) {
                throw "Issue #80 镜像构建退出码: $($build.ExitCode)"
            }
            return
        } catch {
            if ($attempt -eq 5) { throw }
            Write-Warning "Issue #80 镜像构建第 $attempt 次失败，将重试；浏览器测试本身不重试。"
            Start-Sleep -Seconds 2
        }
    }
}

$effectiveConfigJson = docker compose --project-name $projectName --profile smoke config --format json
if ($LASTEXITCODE -ne 0) {
    throw "Issue #80 effective config 读取失败: $projectName"
}
$effectiveConfig = $effectiveConfigJson | ConvertFrom-Json
$configuredPort = [string]$effectiveConfig.services.frontend.ports[0].published
$configuredImages = @($effectiveConfig.services.PSObject.Properties.Value.image)
if ($effectiveConfig.name -ne $projectName -or $configuredPort -ne [string]$frontendPort) {
    throw "Issue #80 effective config 未应用唯一 project/端口: project=$($effectiveConfig.name) port=$configuredPort"
}
if ($ownedImages | Where-Object { $configuredImages -notcontains $_ }) {
    throw "Issue #80 effective config 未应用唯一镜像标签: $imageTag"
}

Assert-IsolatedResourcesEmpty -Snapshot (Get-IsolatedResourceSnapshot) -Phase '在启动前'

Write-Host "Issue #80 effective config: project=$projectName port=$frontendPort tag=$imageTag volumes=$projectName`_postgres-data,$projectName`_browser-artifacts; preflight containers=0 volumes=0 networks=0 images=0"
try {
    if (-not $SkipBuild) {
        Invoke-BoundedBuild
    }
    docker compose --project-name $projectName up --detach --no-build --force-recreate --wait
    docker compose --project-name $projectName exec -T postgres `
        psql -U postgres -d customer_agent -f /acceptance/issue80-browser.sql
    docker compose --project-name $projectName --profile smoke up --detach --no-build --no-deps --wait browser-frontend
    docker compose --project-name $projectName --profile smoke run --rm --no-deps browser-acceptance `
        e2e/issue80.identity-shells.spec.ts `
        e2e/issue80.session-lifecycle.spec.ts `
        e2e/issue80.business-boundaries.spec.ts `
        e2e/issue80.approval-separation.spec.ts `
        e2e/issue98.customer-help-center.spec.ts `
        e2e/issue99.queue-layout.fake.spec.ts `
        e2e/issue99.support-workbench.spec.ts `
        e2e/issue100.approval-workbench.spec.ts `
        e2e/issue101.cross-role-acceptance.spec.ts `
        e2e/issue124.offline-fullstack-readiness.spec.ts `
        e2e/issue80.sse-revocation.spec.ts
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #80 真实浏览器验收失败，退出码: $LASTEXITCODE"
    }

    $env:ISSUE80_SESSION_PHASE = 'restart-prepare'
    docker compose --project-name $projectName --profile smoke run --rm --no-deps browser-acceptance `
        e2e/issue80.session-restart-expiry.spec.ts
    docker compose --project-name $projectName restart backend
    docker compose --project-name $projectName up --detach --no-deps --wait backend
    $env:ISSUE80_SESSION_PHASE = 'restart-verify'
    docker compose --project-name $projectName --profile smoke run --rm --no-deps browser-acceptance `
        e2e/issue80.session-restart-expiry.spec.ts

    $env:CUSTOMER_AGENT_SESSION_TIMEOUT = '1m'
    docker compose --project-name $projectName up --detach --no-deps --force-recreate --wait backend
    $env:ISSUE80_SESSION_PHASE = 'expiry'
    docker compose --project-name $projectName --profile smoke run --rm --no-deps browser-acceptance `
        e2e/issue80.session-restart-expiry.spec.ts
    if ($LASTEXITCODE -ne 0) {
        throw "Issue #80 Session 重启/超时验收失败，退出码: $LASTEXITCODE"
    }
} finally {
    docker compose --project-name $projectName --profile smoke down --volumes --remove-orphans
    Get-OwnedImages | ForEach-Object {
        docker image rm $_ | Out-Null
    }
    Assert-IsolatedResourcesEmpty -Snapshot (Get-IsolatedResourceSnapshot) -Phase '清理后'
    Remove-Item Env:CUSTOMER_AGENT_IMAGE_TAG -ErrorAction SilentlyContinue
    Remove-Item Env:CUSTOMER_AGENT_FRONTEND_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:SESSION_COOKIE_SECURE -ErrorAction SilentlyContinue
    Remove-Item Env:CUSTOMER_AGENT_SESSION_TIMEOUT -ErrorAction SilentlyContinue
    Remove-Item Env:ISSUE80_SESSION_PHASE -ErrorAction SilentlyContinue
}

Write-Host 'Issue #80 真实浏览器验收通过，隔离容器、合成数据卷与本次镜像标签已回读为空。'
