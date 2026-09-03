$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$retrieval = Get-Content -Raw -LiteralPath (Join-Path $root 'docs/implementation/evidence/issue190-final-20260901a/rag-layered-v2-retrieval-result.json') | ConvertFrom-Json
$customerRuntime = Get-Content -Raw -LiteralPath (Join-Path $root 'docs/implementation/evidence/issue169-runtime-20260902g/phase.json') | ConvertFrom-Json
$customerBrowser = Get-Content -Raw -LiteralPath (Join-Path $root 'docs/implementation/evidence/issue169-runtime-20260902g/browser.json') | ConvertFrom-Json
$customerAnswer = Get-Content -Raw -LiteralPath (Join-Path $root 'docs/implementation/evidence/issue169-answer-grounded-final-20260902k/summary.json') | ConvertFrom-Json
$humanEvidence = Get-Content -Raw -LiteralPath (Join-Path $root 'docs/implementation/issue-170-human-wiring.md')

if (
    $retrieval.evaluation_protocol -ne 'rag-layered-v2-retrieval' -or
    $retrieval.status -ne 'PASS' -or
    $retrieval.answer_quality -ne 'NOT_EVALUATED' -or
    @($retrieval.rows).Count -ne 64
) {
    throw 'Issue #173 缺少 #190 完整64题检索层PASS证据。'
}
if (
    $customerRuntime.status -ne 'PASS' -or
    $customerRuntime.cleanup -ne 'PASS' -or
    $customerBrowser.stats.expected -ne 2 -or
    $customerBrowser.stats.unexpected -ne 0
) {
    throw 'Issue #173 缺少 #169 客户来源、窄屏与断线恢复证据。'
}
if (
    $customerAnswer.quality_status -ne 'ACCEPTED_WITH_KNOWN_LIMITATIONS' -or
    $customerAnswer.structural_accepted -ne 42 -or
    $customerAnswer.structural_total -ne 48 -or
    $customerAnswer.semantic_pass -ne 35 -or
    $customerAnswer.semantic_total -ne 48 -or
    $customerAnswer.answered_semantic_pass -ne 28 -or
    $customerAnswer.answered_total -ne 36 -or
    $customerAnswer.unanswered_correct_refusal -ne 7 -or
    $customerAnswer.unanswered_total -ne 12
) {
    throw 'Issue #173 的 #169 回答证据边界或原始分母已漂移。'
}

$humanMarkers = @(
    'support-assistance-answer-v2',
    'issue170-riskfix-backend-20260902b',
    'issue170-riskfix-agent-20260902a',
    'issue170-riskfix-frontend-20260902b',
    'KNOWN_LIMITATIONS'
)
$humanFiles = @(
    'backend/src/main/java/com/stellogic/customeragent/queue/SupportAssistanceService.java',
    'agent/src/baseline_agent/support_assistance_model.py',
    'frontend/src/components/support-assistance/SupportAssistance.tsx'
)
if (
    @($humanMarkers | Where-Object { -not $humanEvidence.Contains($_) }).Count -ne 0 -or
    @($humanFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $root $_)) }).Count -ne 0
) {
    throw 'Issue #173 缺少 #170 HUMAN 辅助接线、聚焦门禁或已知限制证据。'
}

Write-Host 'Issue #173 RAG 分层证据契约通过：#190 retrieval PASS；#169 browser PASS/回答质量已知限制；#170 HUMAN 接线与聚焦门禁在案、真实回答质量 NOT_EVALUATED。'
