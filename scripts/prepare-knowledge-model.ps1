param(
    [string]$Uv = 'uv',
    [string]$ModelDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) '.local/models/bge-small-zh-v1.5'),
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'

function Assert-KnowledgeModelDirectory {
    param([Parameter(Mandatory)][string]$Directory)

    $repoRoot = Split-Path -Parent $PSScriptRoot
    $protocolPath = Join-Path $repoRoot 'agent/src/baseline_agent/rag_eval_v1/protocol.json'
    $protocol = Get-Content -LiteralPath $protocolPath -Raw | ConvertFrom-Json -AsHashtable
    foreach ($entry in $protocol.model.files.GetEnumerator()) {
        $path = Join-Path $Directory $entry.Key
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "缺少本地模型文件：$($entry.Key)"
        }
        $bytes = [System.IO.File]::ReadAllBytes($path)
        if ($null -ne $entry.Value.size_bytes -and $bytes.Length -ne $entry.Value.size_bytes) {
            throw "本地模型文件长度不符：$($entry.Key)"
        }
        if ($entry.Value.sha256) {
            $actual = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
            if ($actual -ne $entry.Value.sha256) {
                throw "本地模型文件校验失败：$($entry.Key)"
            }
        }
        if ($entry.Value.git_blob_sha1) {
            $header = [System.Text.Encoding]::UTF8.GetBytes("blob $($bytes.Length)`0")
            $blob = [byte[]]::new($header.Length + $bytes.Length)
            [Array]::Copy($header, 0, $blob, 0, $header.Length)
            [Array]::Copy($bytes, 0, $blob, $header.Length, $bytes.Length)
            $actual = [Convert]::ToHexString([System.Security.Cryptography.SHA1]::HashData($blob)).ToLowerInvariant()
            if ($actual -ne $entry.Value.git_blob_sha1) {
                throw "本地模型文件校验失败：$($entry.Key)"
            }
        }
    }
}

. "$PSScriptRoot/test-gate-lock.ps1"
$holder = Enter-TestGateLock -Issue 190 -CommandType 'knowledge-model-prepare'
try {
    if ($VerifyOnly) {
        Assert-KnowledgeModelDirectory -Directory $ModelDirectory
        Write-Host '本地知识检索模型校验通过。'
    } else {
        Push-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'agent')
        try {
            & $Uv run --frozen python -m baseline_agent.prepare_knowledge_model $ModelDirectory
            if ($LASTEXITCODE -ne 0) { throw '固定 revision 模型准备失败；停止，不使用替代模型。' }
        } finally { Pop-Location }
    }
} finally { Exit-TestGateLock $holder }
