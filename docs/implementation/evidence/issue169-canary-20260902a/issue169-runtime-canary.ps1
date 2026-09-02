param([string]$RunId='issue169-runtime-20260901a',[switch]$Browser,[switch]$Answers,[switch]$Canary)
$ErrorActionPreference='Stop'
$repo169=Split-Path -Parent $PSScriptRoot
Set-Location $repo169
. ./scripts/test-gate-lock.ps1
. ./scripts/gate-images.ps1
. ./scripts/gate-resources.ps1
$tag169="gate-$RunId"
$project169="customer-agent-$tag169"
$out169="$repo169/docs/implementation/evidence/$RunId"
New-Item -ItemType Directory -Force $out169 | Out-Null
$holder169=Enter-TestGateLock -Issue 169 -RunId $RunId -CommandType 'customer-knowledge-http-pg' -BaseSha (git rev-parse origin/main) -HeadSha (git rev-parse HEAD) -ComposeProject $project169 -ImageTag $tag169
if(-not $holder169.AcquiredHere){throw 'This runner requires its own dedicated pwsh process and lock; inherited locks are unsupported.'}
$record169=@{run=$RunId;head=(git rev-parse HEAD);working_tree_dirty=[bool](git status --porcelain);status='FAIL';steps=@();paid_model_calls=0}
$env:COMPOSE_PROJECT_NAME=$project169
$started169=$false
function Step169([string]$Name,[string]$Exe,[string[]]$Arguments){
 & $Exe @Arguments *> "$out169/$Name.log"
 $code169=$LASTEXITCODE
 $record169.steps+=@{name=$Name;exitCode=$code169}
 Get-Content "$out169/$Name.log" -Tail 12
 if($code169 -ne 0){throw "$Name failed: $code169"}
}
try {
 Set-Location "$repo169/agent"
 try { Step169 'python-static' 'C:/Users/lizhuo/.codex/worktrees/808f/customer-agent/agent/.venv/Scripts/ruff.exe' @('check','tests/issue169_customer_knowledge_acceptance.py','tests/issue169_customer_answer_run.py') }
 finally { Set-Location $repo169 }
 $env:COMPOSE_PROJECT_NAME=$project169
 $env:CUSTOMER_AGENT_IMAGE_TAG=$tag169
 $env:CUSTOMER_AGENT_GATE_RUN_ID=$RunId
 $env:KNOWLEDGE_MODEL_HOST_PATH='C:/Users/lizhuo/.codex/worktrees/808f/customer-agent/.local/models/bge-small-zh-v1.5'
 $env:DEEPSEEK_API_KEY=''
 $env:AGENT_INVESTIGATION_ACTION_MODEL_MODE='deterministic'
 $env:AGENT_CUSTOMER_COMMUNICATION_MODEL_MODE='fixed-fake'
 if($Answers -or $Canary){
  @"
services:
  agent-server:
    volumes:
      - type: bind
        source: "D:/customer-agent/.local/issue190-sufficiency"
        target: /budget
      - type: bind
        source: "$($repo169.Replace('\','/'))"
        target: /repo
        read_only: true
"@ | Set-Content "$repo169/.local/issue169-answer-compose.yaml"
  $env:COMPOSE_FILE="$repo169/compose.yaml;$repo169/.local/issue169-answer-compose.yaml"
 }
 $port169=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
 $port169.Start();$env:CUSTOMER_AGENT_FRONTEND_PORT=[string]$port169.LocalEndpoint.Port;$port169.Stop()
 $record169.frontend_port=$env:CUSTOMER_AGENT_FRONTEND_PORT
 & ./scripts/confirm-compose-reset-isolation.ps1
 foreach($component169 in @('backend','agent','frontend')){
  Step169 "build-$component169" 'docker' @('build','--pull=false','--target','runtime','--label',"com.stellogic.customer-agent.gate.run-id=$RunId",'--tag',"customer-agent/${component169}:$tag169",$component169)
 }
 $started169=$true
 Step169 'startup' 'docker' @('compose','-p',$project169,'up','--detach','--wait','postgres','spring-migrate','agent-migrate','agent-server','backend','frontend')
 Step169 'copy-smoke' 'docker' @('compose','-p',$project169,'cp','agent/smoke.py','agent-server:/tmp/smoke.py')
 Step169 'copy-acceptance' 'docker' @('compose','-p',$project169,'cp','agent/tests/issue169_customer_knowledge_acceptance.py','agent-server:/tmp/issue169_customer_knowledge_acceptance.py')
 Step169 'http-pg' 'docker' @('compose','-p',$project169,'exec','-T','-e','SPRING_DATABASE_URI=postgresql://spring_app:local-spring-app@postgres:5432/customer_agent','-e','ISSUE169_OUTPUT=/tmp/issue169-http-pg.json','agent-server','python','/tmp/issue169_customer_knowledge_acceptance.py')
 Step169 'copy-http-pg' 'docker' @('compose','-p',$project169,'cp','agent-server:/tmp/issue169-http-pg.json',"$out169/http-pg.json")
 Step169 'copy-sql' 'docker' @('compose','-p',$project169,'cp','backend/src/test/resources/issue169_customer_knowledge_projection.sql','postgres:/tmp/issue169.sql')
 Step169 'projection-sql' 'docker' @('compose','-p',$project169,'exec','-T','postgres','psql','-U','postgres','-d','customer_agent','-f','/tmp/issue169.sql')
 if($Browser){
  $env:PATH='C:\Users\lizhuo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;'+$env:PATH
  $env:PLAYWRIGHT_BASE_URL="http://127.0.0.1:$env:CUSTOMER_AGENT_FRONTEND_PORT"
  $env:ISSUE169_BROWSER_TICKET=(Get-Content "$out169/http-pg.json" -Raw | ConvertFrom-Json).browser_ticket
  $env:ISSUE169_BROWSER_REPORT="$out169/browser.json"
  $env:ISSUE169_BROWSER_OUTPUT="$out169/browser-artifacts"
  Step169 'browser' 'node' @('frontend/node_modules/@playwright/test/cli.js','test','--config','.local/issue169-playwright.config.ts')
 }
 if($Answers -and $started169){
  Step169 'copy-answer' 'docker' @('compose','-p',$project169,'cp','agent/tests/issue169_customer_answer_run.py','agent-server:/tmp/issue169_customer_answer_run.py')
  $keyLine169=@(Get-Content D:/customer-agent/.env | Where-Object {$_ -match '^DEEPSEEK_API_KEY='})
  if($keyLine169.Count -ne 1){throw 'Missing unique DeepSeek key setting'}
  $env:DEEPSEEK_API_KEY=$keyLine169[0].Substring('DEEPSEEK_API_KEY='.Length).Trim().Trim('"').Trim("'")
  Step169 'answers' 'docker' @('compose','-p',$project169,'exec','-T','-e','DEEPSEEK_API_KEY','-e','DEEPSEEK_MODEL=deepseek-v4-flash','-e','SPRING_DATABASE_URI=postgresql://spring_app:local-spring-app@postgres:5432/customer_agent','-e','ISSUE169_REPO=/repo','-e','ISSUE169_LEDGER=/budget/cost-ledger.json','-e',"ISSUE169_RUN_ID=$RunId",'-e',"ISSUE169_HEAD=$($record169.head)",'-e','ISSUE169_OUTPUT=/tmp/issue169-answers.json','agent-server','python','/tmp/issue169_customer_answer_run.py')
  Step169 'copy-answers' 'docker' @('compose','-p',$project169,'cp','agent-server:/tmp/issue169-answers.json',"$out169/answers.json")
 }
 if($Canary -and $started169){
  Step169 'copy-canary-runner' 'docker' @('compose','-p',$project169,'cp','.local/issue169_customer_answer_canary.py','agent-server:/tmp/issue169_customer_answer_canary.py')
  Step169 'copy-canary-answer' 'docker' @('compose','-p',$project169,'cp','agent/tests/issue169_customer_answer_run.py','agent-server:/tmp/issue169_customer_answer_run.py')
  $keyLine169=@(Get-Content D:/customer-agent/.env | Where-Object {$_ -match '^DEEPSEEK_API_KEY='})
  if($keyLine169.Count -ne 1){throw 'Missing unique DeepSeek key setting'}
  $env:DEEPSEEK_API_KEY=$keyLine169[0].Substring('DEEPSEEK_API_KEY='.Length).Trim().Trim('"').Trim("'")
  Step169 'canary' 'docker' @('compose','-p',$project169,'exec','-T','-e','DEEPSEEK_API_KEY','-e','DEEPSEEK_MODEL=deepseek-v4-flash','-e','SPRING_DATABASE_URI=postgresql://spring_app:local-spring-app@postgres:5432/customer_agent','-e','ISSUE169_REPO=/repo','-e','ISSUE169_LEDGER=/budget/cost-ledger.json','-e',"ISSUE169_RUN_ID=$RunId",'-e',"ISSUE169_HEAD=$($record169.head)",'-e','ISSUE169_OUTPUT=/tmp/issue169-canary.json','agent-server','python','/tmp/issue169_customer_answer_canary.py')
  Step169 'copy-canary' 'docker' @('compose','-p',$project169,'cp','agent-server:/tmp/issue169-canary.json',"$out169/canary.json")
 }
 $record169.status='PASS'
} catch {
 $record169.error=$_.Exception.Message
 Write-Output $record169.error
} finally {
 $env:DEEPSEEK_API_KEY=''
 $cleanupComplete169=$false
 $record169.project=$project169
 $record169.image_tag=$tag169
 try {
  if($Answers -and $started169){
   docker compose -p $project169 cp 'agent-server:/tmp/issue169-answers.json' "$out169/answers.json" *> "$out169/final-copy-answers.log"
   if($LASTEXITCODE -ne 0){throw 'Answer evidence copy failed'}
   $answers169=Get-Content "$out169/answers.json" -Raw | ConvertFrom-Json
   $record169.paid_model_calls=$answers169.provider_attempt_count
   $record169.answer_quality=$answers169.status
  }
  if($Canary -and $started169){
   docker compose -p $project169 cp 'agent-server:/tmp/issue169-canary.json' "$out169/canary.json" *> "$out169/final-copy-canary.log"
   if($LASTEXITCODE -ne 0){throw 'Canary evidence copy failed'}
   $canary169=Get-Content "$out169/canary.json" -Raw | ConvertFrom-Json
   $record169.paid_model_calls=$canary169.provider_attempt_count
   $record169.answer_quality=$canary169.status
  }
  if($started169){
   docker compose -p $project169 cp 'agent-server:/tmp/issue169-http-pg.json' "$out169/http-pg.json" *> "$out169/final-copy.log"
   if($LASTEXITCODE -ne 0){throw 'HTTP evidence copy failed'}
   docker compose -p $project169 logs --tail 100 backend spring-migrate *> "$out169/services.log"
   if($LASTEXITCODE -ne 0){throw 'Service evidence capture failed'}
  }
 }catch{
  $record169.status='FAIL'
  $record169.evidence_error=$_.Exception.Message
   if($Answers -or $Canary){$record169.paid_model_calls='UNKNOWN_CHECK_ORIGINAL_LEDGER'}
 }
 try {
  if($started169){
   docker compose -p $project169 down --volumes --remove-orphans *> "$out169/cleanup.log"
   if($LASTEXITCODE -ne 0){throw 'Isolated Compose cleanup failed'}
  }
  Assert-ComposeProjectResourcesEmpty -ProjectName $project169 -Phase 'issue169 cleanup'
  Remove-GateImages -RunId $RunId
  Assert-GateImagesAbsent -RunId $RunId
  $cleanupComplete169=$true
  $record169.cleanup=if($started169){'PASS'}else{'NO_COMPOSE_START'}
 }catch{
  $record169.status='FAIL'
  $record169.cleanup='RECOVERY_REQUIRED'
  $record169.cleanup_error=$_.Exception.Message
 }finally{
  try {
   $record169 | ConvertTo-Json -Depth 8 | Set-Content "$out169/phase.json"
  }catch{
   $record169.status='FAIL'
   Write-Output "PHASE_WRITE_FAILED issue=169 run=$RunId project=$project169"
  }finally{
   if($cleanupComplete169){
    Exit-TestGateLock $holder169
    Write-Output "LOCK_RELEASED issue=169 run=$RunId"
    Show-TestGateStatus
   }else{
    # 专用pwsh进程退出后由OS释放互斥量;不删现有owner记录,交原恢复流程匹配残留。
    Write-Output "TEST_GATE_RECOVERY_REQUIRED issue=169 run=$RunId project=$project169 image=$tag169"
    exit 77
   }
  }
 }
}
if($record169.status -ne 'PASS'){exit 1}
