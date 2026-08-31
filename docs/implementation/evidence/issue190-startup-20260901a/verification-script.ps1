param([string]$RunId='issue190-startup-20260901a')
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true
$root=Split-Path -Parent $PSScriptRoot
Set-Location $root
. "$root/scripts/test-gate-lock.ps1"
. "$root/scripts/gate-images.ps1"
. "$root/scripts/gate-resources.ps1"
$head=(git rev-parse HEAD).Trim()
$base=(git rev-parse origin/main).Trim()
$project="customer-agent-$RunId"
$tag="gate-$RunId"
$holder=Enter-TestGateLock -Issue 190 -RunId $RunId -CommandType 'startup-upgrade-focused' -HeadSha $head -BaseSha $base -ComposeProject $project -ImageTag $tag
$out=Join-Path $root ".local/gate-evidence/$RunId"
$report=[ordered]@{run_id=$RunId;head_sha=$head;base_sha=$base;status='ERROR';working_tree_dirty=[bool](git status --porcelain);paid_model_calls=0;model_downloads=0;quality='NOT_RUN';phases=@()}
$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    New-Item -ItemType Directory -Force -Path "$out/init" | Out-Null
    Start-Transcript -Path "$out/runtime.log" | Out-Null
    $env:COMPOSE_PROJECT_NAME=$project
    $env:CUSTOMER_AGENT_IMAGE_TAG=$tag
    $env:DEEPSEEK_API_KEY=''
    $env:AGENT_INVESTIGATION_SHADOW_MODE='offline'
    $readme=Get-Content README.md -Raw
    foreach($block in [regex]::Matches($readme,'(?s)```powershell\r?\n(.*?)```')) {
        $parseErrors=$null
        $tokens=$null
        $null=[Management.Automation.Language.Parser]::ParseInput($block.Groups[1].Value,[ref]$tokens,[ref]$parseErrors)
        if($parseErrors.Count) { throw "README PowerShell syntax: $parseErrors" }
    }
    $report.phases+='README_POWERSHELL_SYNTAX_PASS'
    Push-Location "$root/agent"
    try {
        & ./.venv/Scripts/python.exe -c 'from pathlib import Path; from baseline_agent.knowledge_embedding import verify_model_directory; print(verify_model_directory(Path("../.local/models/bge-small-zh-v1.5")))'
    } finally { Pop-Location }
    $report.phases+='EXISTING_MODEL_HASH_CHECK_PASS_NO_DOWNLOAD'
    Copy-Item infra/postgres/init/001-databases.sql "$out/init/001-databases.sql"
    $initPath=(Join-Path $out 'init').Replace('\','/')
    $override=@"
services:
  postgres:
    volumes: !override
      - postgres-data:/var/lib/postgresql
      - ${initPath}:/docker-entrypoint-initdb.d:ro
  spring-migrate:
    environment:
      SPRING_FLYWAY_TARGET: '41'
"@
    [IO.File]::WriteAllText("$out/old-volume.yaml",$override)
    $compose=@('compose','-p',$project,'-f',"$root/compose.yaml",'-f',"$out/old-volume.yaml")
    $config=(docker @compose config --format json) | ConvertFrom-Json
    Assert-ComposeResourcesOwned -ProjectName $project -EffectiveConfig $config
    Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '启动前'
    $fingerprint=Get-GateSourceFingerprint -RepoRoot $root
    $report.fingerprint=$fingerprint
    $report.builds=@(Invoke-GateImageBuilds -RepoRoot $root -RunId $RunId -SourceFingerprint $fingerprint)
    docker @compose up --detach --no-build --wait postgres
    docker @compose run --rm --no-deps spring-migrate
    docker @compose exec -T postgres psql -U postgres -d customer_agent -v ON_ERROR_STOP=1 -c "CREATE TABLE public.issue190_upgrade_marker(value text PRIMARY KEY); INSERT INTO public.issue190_upgrade_marker VALUES ('preserved-before-vector');"
    Copy-Item infra/postgres/init/002-knowledge-vector.sql "$out/init/002-knowledge-vector.sql"
    docker @compose restart postgres
    docker @compose up --detach --no-build --wait postgres
    $before=(docker @compose exec -T postgres psql -U postgres -d customer_agent -At -c "SELECT count(*) FROM pg_extension WHERE extname='vector';").Trim()
    if($before -ne '0') { throw "旧卷意外启用vector: $before" }
    $report.phases+='EXISTING_V41_VOLUME_RESTART_DOES_NOT_RUN_NEW_INIT'
    docker @compose exec -T postgres psql -U postgres -d customer_agent -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/002-knowledge-vector.sql
    docker @compose exec -T postgres psql -U postgres -d customer_agent -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/002-knowledge-vector.sql
    docker compose -p $project run --rm --no-deps spring-migrate
    $after=(docker @compose exec -T postgres psql -U postgres -d customer_agent -At -c "SELECT (SELECT count(*) FROM pg_extension WHERE extname='vector'), (SELECT value FROM public.issue190_upgrade_marker), (SELECT count(*) FROM flyway_schema_history WHERE version='42' AND success), (SELECT count(*) FROM pg_roles WHERE rolname IN ('spring_app','spring_migrator') AND rolsuper);").Trim()
    if($after -ne '1|preserved-before-vector|1|0') { throw "升级回读失败: $after" }
    $report.upgrade_readback=$after
    $report.phases+='README_ADMIN_BOOTSTRAP_IDEMPOTENT_AND_V42_MIGRATION_PASS_DATA_PRESERVED'
    $report.status='PASS'
} catch { $report.failure=$_.Exception.Message; Write-Host $report.failure } finally {
    try {
        docker compose -p $project --profile smoke down --volumes --remove-orphans
        Assert-ComposeProjectResourcesEmpty -ProjectName $project -Phase '结束清理后'
        $PSNativeCommandUseErrorActionPreference=$false
        Remove-GateImages -RunId $RunId
        $PSNativeCommandUseErrorActionPreference=$true
        Assert-GateImagesAbsent -RunId $RunId
        $report.resources='CLEANED'
    } catch { $report.cleanup_error=$_.Exception.Message; $report.status='ERROR' } finally {
        $report.elapsed_seconds=$watch.Elapsed.TotalSeconds
        $report|ConvertTo-Json -Depth 6|Set-Content "$out/phase.json" -Encoding utf8
        Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
        Exit-TestGateLock $holder
    }
}
if($report.status -ne 'PASS') { exit 1 }
