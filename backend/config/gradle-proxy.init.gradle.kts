import java.net.URI

fun environmentValue(upperName: String, lowerName: String): String? {
    val values =
        listOfNotNull(
                System.getenv(upperName)?.trim()?.takeIf(String::isNotEmpty),
                System.getenv(lowerName)?.trim()?.takeIf(String::isNotEmpty),
            )
            .distinct()

    if (values.size > 1) {
        throw GradleException("Conflicting $upperName and $lowerName values are not supported")
    }
    return values.singleOrNull()
}

fun proxyUri(environmentName: String, value: String): URI {
    val uri =
        try {
            URI(value)
        } catch (_: IllegalArgumentException) {
            throw GradleException("$environmentName must be a valid HTTP or HTTPS proxy URI")
        }

    if (uri.scheme?.lowercase() !in setOf("http", "https") || uri.host.isNullOrBlank()) {
        throw GradleException("$environmentName must be a valid HTTP or HTTPS proxy URI")
    }
    if ((!uri.path.isNullOrEmpty() && uri.path != "/") || uri.rawQuery != null || uri.rawFragment != null) {
        throw GradleException("$environmentName must not contain a path, query, or fragment")
    }
    return uri
}

fun configureProxy(environmentName: String, lowerName: String, propertyPrefix: String) {
    val value = environmentValue(environmentName, lowerName) ?: return
    if (!System.getProperty("$propertyPrefix.proxyHost").isNullOrBlank()) {
        return
    }

    val uri = proxyUri(environmentName, value)
    val defaultPort = if (uri.scheme.equals("https", ignoreCase = true)) 443 else 80
    System.setProperty("$propertyPrefix.proxyHost", uri.host)
    System.setProperty("$propertyPrefix.proxyPort", (uri.port.takeIf { it >= 0 } ?: defaultPort).toString())
    uri.userInfo?.split(':', limit = 2)?.let { credentials ->
        System.setProperty("$propertyPrefix.proxyUser", credentials.first())
        System.setProperty("$propertyPrefix.proxyPassword", credentials.getOrElse(1) { "" })
    }
}

fun javaNonProxyHosts(value: String): String {
    val patterns =
        value.split(',').flatMap { rawToken ->
            val token = rawToken.trim()
            if (token.isEmpty()) {
                return@flatMap emptyList()
            }
            if (token.contains('/') || token.contains('@') || token.any(Char::isWhitespace)) {
                throw GradleException(
                    "NO_PROXY contains a value that Java non-proxy host patterns cannot represent"
                )
            }
            if (token == "::1" || token == "[::1]") {
                return@flatMap listOf("[::1]")
            }
            if (token.contains(':')) {
                throw GradleException(
                    "NO_PROXY port-specific and IPv6 values other than loopback are not supported"
                )
            }
            if (token.startsWith('.')) {
                val domain = token.drop(1)
                if (domain.isEmpty() || domain.contains('*')) {
                    throw GradleException("NO_PROXY contains an unsupported wildcard pattern")
                }
                return@flatMap listOf(domain, "*$token")
            }
            if (token.count { it == '*' } > 1 ||
                ('*' in token && !token.startsWith('*') && !token.endsWith('*'))
            ) {
                throw GradleException("NO_PROXY contains an unsupported wildcard pattern")
            }
            listOf(token)
        }

    return patterns.distinct().joinToString("|")
}

configureProxy("HTTP_PROXY", "http_proxy", "http")
configureProxy("HTTPS_PROXY", "https_proxy", "https")

environmentValue("NO_PROXY", "no_proxy")
    ?.takeIf { it.isNotBlank() && System.getProperty("http.nonProxyHosts").isNullOrBlank() }
    ?.let { System.setProperty("http.nonProxyHosts", javaNonProxyHosts(it)) }
