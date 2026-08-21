$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$proxyImageTag = "customer-agent/gradle-proxy-contract:local"
$noProxyImageTag = "customer-agent/gradle-no-proxy-contract:local"
$authenticatedProxyImageTag = "customer-agent/gradle-authenticated-proxy-contract:local"
$fixture = "$PSScriptRoot/fixtures/gradle-proxy-contract/Dockerfile"
$proxyUser = "proxy-user-$([guid]::NewGuid().ToString('N'))"
$proxyPassword = "proxy-password-$([guid]::NewGuid().ToString('N'))"
$probeSuffix = [guid]::NewGuid().ToString('N')
$proxyNetwork = "customer-agent-gradle-proxy-net-$probeSuffix"
$proxyContainer = "customer-agent-gradle-proxy-$probeSuffix"

function Invoke-CurlProxyProbe {
    docker network create $proxyNetwork | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the Gradle proxy contract network"
    }

    docker run --detach --name $proxyContainer --network $proxyNetwork alpine:3.22 `
        sh -c "while true; do printf 'HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\nproxy-ok' | nc -l -p 8080; done" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start the Gradle proxy contract endpoint"
    }

    $proxyEndpoint = "http://${proxyContainer}:8080"
    $result = docker run --rm --network $proxyNetwork `
        --env "HTTP_PROXY=$proxyEndpoint" `
        --env "http_proxy=$proxyEndpoint" `
        --env "HTTPS_PROXY=$proxyEndpoint" `
        --env "https_proxy=$proxyEndpoint" `
        --env "NO_PROXY=" `
        --env "no_proxy=" `
        gradle:9.3.1-jdk25 curl --fail --silent --show-error http://origin.example.test/probe
    if ($LASTEXITCODE -ne 0 -or $result -ne "proxy-ok") {
        throw "Ordinary HTTP client did not use the standard proxy environment"
    }
}

function Invoke-AuthenticatedProxyBuild {
    $proxy = "http://${proxyUser}:${proxyPassword}@proxy.example.test:8080"
    $output = docker build `
        --file $fixture `
        --target authenticated-proxy-contract `
        --tag $authenticatedProxyImageTag `
        --build-arg "HTTP_PROXY=" `
        --build-arg "http_proxy=" `
        --build-arg "HTTPS_PROXY=$proxy" `
        --build-arg "https_proxy=$proxy" `
        --build-arg "NO_PROXY=" `
        --build-arg "no_proxy=" `
        $repositoryRoot 2>&1 | Out-String
    $exitCode = $LASTEXITCODE

    if ($output.Contains($proxyUser, [System.StringComparison]::Ordinal) -or
        $output.Contains($proxyPassword, [System.StringComparison]::Ordinal)
    ) {
        throw "Authenticated proxy build output leaked a credential"
    }
    if ($exitCode -ne 0) {
        throw "Authenticated Gradle proxy contract test failed"
    }
}

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
    Invoke-CurlProxyProbe

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

    Invoke-AuthenticatedProxyBuild

    Invoke-RejectedProxyBuild `
        -Proxy "http://proxy.example.test:8080" `
        -NoProxy "10.0.0.0/8" `
        -ForbiddenOutput @("10.0.0.0/8") `
        -ExpectedMessage "Java non-proxy host patterns cannot represent"
} finally {
    docker container rm --force $proxyContainer 2>$null | Out-Null
    docker network rm $proxyNetwork 2>$null | Out-Null
    docker image rm $proxyImageTag $noProxyImageTag $authenticatedProxyImageTag 2>$null | Out-Null
}
