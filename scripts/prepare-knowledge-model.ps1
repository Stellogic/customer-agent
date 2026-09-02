param(
    [string]$Uv = 'uv',
    [string]$ModelDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) '.local/models/bge-small-zh-v1.5')
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/test-gate-lock.ps1"
$holder = Enter-TestGateLock -Issue 190 -CommandType 'knowledge-model-prepare'
try {
    Push-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'agent')
    try {
        & $Uv run --frozen python -m baseline_agent.prepare_knowledge_model $ModelDirectory
        if ($LASTEXITCODE -ne 0) { throw '固定 revision 模型准备失败；停止，不使用替代模型。' }
    } finally { Pop-Location }
} finally { Exit-TestGateLock $holder }
