param(
    [string]$RunId = ('issue226-confirm-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
. "$PSScriptRoot/test-gate-lock.ps1"
. "$PSScriptRoot/gate-resources.ps1"
. "$PSScriptRoot/gate-images.ps1"
if ($RunId -notmatch '^issue226-confirm-[a-z0-9-]+$') { throw 'RunId 必须使用 issue226-confirm- 前缀和小写字母、数字或连字符。' }
$repo = Split-Path -Parent $PSScriptRoot
$frontendPath = (Join-Path $repo 'frontend').Replace('\', '/')
Set-Location $repo
$project = "customer-agent-$RunId"
$tag = "gate-$RunId"
$evidence = Join-Path $repo ".local/gate-evidence/$RunId"
$artifacts = (Join-Path $evidence 'artifacts').Replace('\', '/')
if (Test-Path -LiteralPath $evidence) { throw '回归证据目录已存在，禁止重用本轮标识。' }
$gate = Enter-TestGateLock -Issue 226 -RunId $RunId -CommandType 'confirmation-regression' `
    -BaseSha (git rev-parse origin/main).Trim() -HeadSha (git rev-parse HEAD).Trim() -ComposeProject $project -ImageTag $tag
$override = Join-Path $evidence 'compose.override.yaml'
$emptyEnv = Join-Path $evidence 'empty.env'
$started = $false
$built = $false
$cleanupPassed = $false
$outcome = 'NOT_RUN'
function Invoke-ConfirmationCompose([object[]]$Arguments) {
    & docker compose --profile smoke --env-file $emptyEnv -f (Join-Path $repo 'compose.yaml') -f $override -p $project @Arguments
    if ($LASTEXITCODE -ne 0) { throw "确认回归 Compose 操作失败，退出码 $LASTEXITCODE。" }
}
try {
    Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '启动前'
    New-Item -ItemType Directory -Path $evidence | Out-Null
    New-Item -ItemType Directory -Path $artifacts | Out-Null
    Set-Content -LiteralPath $emptyEnv -Value 'CUSTOMER_AGENT_FRONTEND_PORT=0'
    # 不启动 Agent runtime，不读取真实模型密钥；仅使用测试进程的受控 HTTP 响应。
    @"
services:
  backend:
    image: customer-agent/backend:$tag
    environment:
      AGENT_SERVER_URL: http://issue226-agent:2024
      AGENT_SUBMISSION_POLL_DELAY: '3600000'
  spring-migrate:
    image: customer-agent/backend:$tag
  browser-frontend:
    image: customer-agent/frontend-browser-server:$tag
  browser-acceptance:
    image: customer-agent/frontend-browser-test:$tag
    volumes:
      - '${artifacts}:/artifacts'
      - '${frontendPath}/src:/app/src:ro'
      - '${frontendPath}/tsconfig.json:/app/tsconfig.json:ro'
      - '${frontendPath}/vite.config.ts:/app/vite.config.ts:ro'
      - '${frontendPath}/eslint.config.js:/app/eslint.config.js:ro'
      - '${frontendPath}/.prettierrc.json:/app/.prettierrc.json:ro'
    environment:
      ISSUE226_CONFIRMATION_REGRESSION: '1'
    networks:
      edge: {}
      data: {}
      services:
        aliases: [issue226-agent]
"@ | Set-Content -LiteralPath $override
    $config = Invoke-ConfirmationCompose @('config', '--format', 'json') | ConvertFrom-Json
    Assert-ComposeResourcesOwned -ProjectName $project -EffectiveConfig $config
    $built = $true
    Invoke-ConfirmationCompose @('build', 'backend', 'browser-frontend', 'browser-acceptance')
    $started = $true
    $testFiles = @('e2e/issue226.explicit-confirmation.spec.ts', 'e2e/support/issue226-node-http.d.ts')
    Invoke-ConfirmationCompose (@('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'prettier', '--check') + $testFiles)
    Invoke-ConfirmationCompose (@('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'eslint', '--max-warnings', '0') + $testFiles)
    Invoke-ConfirmationCompose @('run', '--rm', '--no-deps', '--entrypoint', 'npx', 'browser-acceptance', '--no-install', 'tsc', '--noEmit')
    Invoke-ConfirmationCompose @('up', '-d', '--no-deps', '--wait', 'postgres')
    Invoke-ConfirmationCompose @('run', '--rm', '--no-deps', 'spring-migrate')
    Invoke-ConfirmationCompose @('up', '-d', '--no-deps', '--no-build', '--wait', 'backend', 'browser-frontend')
    Invoke-ConfirmationCompose @('run', '--rm', '--no-deps', '--use-aliases', 'browser-acceptance', '--workers=1', '--output=/artifacts', 'e2e/issue226.explicit-confirmation.spec.ts')
    $outcome = 'PASS'
} catch {
    $outcome = 'FAIL'
    throw
} finally {
    try {
        if ($started) { Invoke-ConfirmationCompose @('down', '--volumes', '--remove-orphans') }
        if ($built) {
            foreach ($name in @('backend', 'frontend-browser-server', 'frontend-browser-test')) {
                $image = "customer-agent/${name}:$tag"
                if (@(docker image ls --format '{{.Repository}}:{{.Tag}}') -contains $image) {
                    docker image rm $image
                }
            }
            Assert-GateImagesAbsent -RunId $RunId
        }
        Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '清理后'
        $cleanupPassed = $true
    } finally {
        try {
            if (Test-Path -LiteralPath $evidence) {
                @{ runId = $RunId; head = (git rev-parse HEAD).Trim(); outcome = $outcome; cleanupPassed = $cleanupPassed; paidCalls = 0 } |
                    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'result.json')
            }
        } finally {
            if ($cleanupPassed) {
                Exit-TestGateLock $gate
                Write-Host 'LOCK_RELEASED'
            } elseif ($gate.AcquiredHere) {
                # 清理失败保留原门禁记录；下次按该 project/tag 检测残留并要求恢复。
                # 此处只释放本脚本持有的互斥量，不能调用会删除记录的 Exit-TestGateLock。
                try { $gate.Mutex.ReleaseMutex() } finally { $gate.Mutex.Dispose() }
                if ($gate.PreviousToken) {
                    $env:CUSTOMER_AGENT_TEST_GATE_TOKEN = $gate.PreviousToken
                } else {
                    Remove-Item Env:CUSTOMER_AGENT_TEST_GATE_TOKEN -ErrorAction SilentlyContinue
                }
                $script:TestGateHeldMutex = $gate.PreviousMutex
            }
        }
    }
}
