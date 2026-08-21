$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$proxyImageTag = "customer-agent/gradle-proxy-contract:local"
$noProxyImageTag = "customer-agent/gradle-no-proxy-contract:local"
$fixture = "$PSScriptRoot/fixtures/gradle-proxy-contract/Dockerfile"
$proxyUser = "proxy-user-$([guid]::NewGuid().ToString('N'))"
$proxyPassword = "proxy-password-$([guid]::NewGuid().ToString('N'))"

function Invoke-RejectedProxyBuild {
    param(
        [string]$Proxy,
        [string]$NoProxy,
        [string[]]$ForbiddenOutput,
        [string]$ExpectedMessage
    )

    $output = docker build `
        --file $fixture `
        --target rejected-proxy-contract `
        --build-arg "HTTP_PROXY=" `
        --build-arg "http_proxy=" `
        --build-arg "HTTPS_PROXY=$Proxy" `
        --build-arg "https_proxy=$Proxy" `
        --build-arg "NO_PROXY=$NoProxy" `
        --build-arg "no_proxy=$NoProxy" `
        $repositoryRoot 2>&1 | Out-String
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        throw "Unsafe Gradle proxy input was accepted"
    }
    foreach ($forbidden in $ForbiddenOutput) {
        if ($output.Contains($forbidden, [System.StringComparison]::Ordinal)) {
            throw "Rejected proxy output leaked a forbidden value"
        }
    }
    if (-not $output.Contains($ExpectedMessage, [System.StringComparison]::Ordinal)) {
        throw "Rejected proxy output did not contain the expected sanitized error"
    }
}

try {
    docker build `
        --file $fixture `
        --target proxy-contract `
        --tag $proxyImageTag `
        --build-arg "HTTP_PROXY=http://proxy.example.test:8080" `
        --build-arg "HTTPS_PROXY=https://secure-proxy.example.test:8443" `
        --build-arg "NO_PROXY=localhost,.example.test,127.0.0.1" `
        $repositoryRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle proxy contract test failed"
    }

    docker build `
        --file $fixture `
        --target no-proxy-contract `
        --tag $noProxyImageTag `
        --build-arg "HTTP_PROXY=" `
        --build-arg "http_proxy=" `
        --build-arg "HTTPS_PROXY=" `
        --build-arg "https_proxy=" `
        --build-arg "NO_PROXY=" `
        --build-arg "no_proxy=" `
        $repositoryRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle no-proxy contract test failed"
    }

    Invoke-RejectedProxyBuild `
        -Proxy "http://${proxyUser}:${proxyPassword}@proxy.example.test:8080" `
        -NoProxy "" `
        -ForbiddenOutput @($proxyUser, $proxyPassword) `
        -ExpectedMessage "authenticated proxy URIs are not supported"

    Invoke-RejectedProxyBuild `
        -Proxy "http://proxy.example.test:8080" `
        -NoProxy "10.0.0.0/8" `
        -ForbiddenOutput @("10.0.0.0/8") `
        -ExpectedMessage "Java non-proxy host patterns cannot represent"
} finally {
    docker image rm $proxyImageTag $noProxyImageTag 2>$null | Out-Null
}
