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

if ((Get-ProjectContainers).Count -ne 0 -or (Get-ProjectVolumes).Count -ne 0) {
    throw "Issue #80 隔离 project 在启动前已有资源: $projectName"
}

Write-Host "Issue #80 isolated project: $projectName"
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
    $remainingContainers = Get-ProjectContainers
    $remainingVolumes = Get-ProjectVolumes
    if ($remainingContainers.Count -ne 0 -or $remainingVolumes.Count -ne 0) {
        throw "Issue #80 隔离资源清理后仍有残留: containers=$($remainingContainers -join ',') volumes=$($remainingVolumes -join ',')"
    }
    $existingImages = @(docker image ls --format '{{.Repository}}:{{.Tag}}')
    $ownedImages | Where-Object { $existingImages -contains $_ } | ForEach-Object {
        docker image rm $_ | Out-Null
    }
    $remainingImages = @(docker image ls --format '{{.Repository}}:{{.Tag}}') |
        Where-Object { $ownedImages -contains $_ }
    if ($remainingImages.Count -ne 0) {
        throw "Issue #80 隔离镜像清理后仍有残留: $($remainingImages -join ',')"
    }
    Remove-Item Env:CUSTOMER_AGENT_IMAGE_TAG -ErrorAction SilentlyContinue
    Remove-Item Env:CUSTOMER_AGENT_FRONTEND_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:SESSION_COOKIE_SECURE -ErrorAction SilentlyContinue
    Remove-Item Env:CUSTOMER_AGENT_SESSION_TIMEOUT -ErrorAction SilentlyContinue
    Remove-Item Env:ISSUE80_SESSION_PHASE -ErrorAction SilentlyContinue
}

Write-Host 'Issue #80 真实浏览器验收通过，隔离容器、合成数据卷与本次镜像标签已回读为空。'
