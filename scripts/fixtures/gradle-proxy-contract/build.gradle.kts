tasks.register("verifyProxyContract") {
    doLast {
        check(System.getProperty("http.proxyHost") == "proxy.example.test") {
            "HTTP_PROXY was injected, but Gradle did not configure http.proxyHost"
        }
        check(System.getProperty("http.proxyPort") == "8080") {
            "HTTP_PROXY was injected, but Gradle did not configure http.proxyPort"
        }
        check(System.getProperty("https.proxyHost") == "secure-proxy.example.test") {
            "HTTPS_PROXY was injected, but Gradle did not configure https.proxyHost"
        }
        check(System.getProperty("https.proxyPort") == "8443") {
            "HTTPS_PROXY was injected, but Gradle did not configure https.proxyPort"
        }
        check(
            System.getProperty("http.nonProxyHosts") ==
                "localhost|example.test|*.example.test|127.0.0.1"
        ) {
            "NO_PROXY was injected, but Gradle did not configure http.nonProxyHosts"
        }
    }
}

tasks.register("verifyNoProxyContract") {
    doLast {
        check(System.getProperty("http.proxyHost") == null)
        check(System.getProperty("http.proxyPort") == null)
        check(System.getProperty("https.proxyHost") == null)
        check(System.getProperty("https.proxyPort") == null)
        check(System.getProperty("http.nonProxyHosts") == null)
    }
}

tasks.register("verifyAuthenticatedProxyContract") {
    doLast {
        val proxyUser = System.getProperty("https.proxyUser")
        val proxyPassword = System.getProperty("https.proxyPassword")
        check(proxyUser != null && proxyUser.startsWith("proxy:user-") && proxyUser.length > 20) {
            "HTTPS_PROXY credentials were not mapped to the Gradle proxy user"
        }
        check(
            proxyPassword != null &&
                proxyPassword.startsWith("proxy+p@ss-") &&
                proxyPassword.length > 20
        ) {
            "HTTPS_PROXY credentials were not mapped to the Gradle proxy password"
        }
    }
}
