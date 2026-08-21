FROM gradle:9.3.1-jdk25 AS contract-base

WORKDIR /contract
COPY backend/config/gradle-proxy.init.gradle.kts /contract/gradle-proxy.init.gradle.kts
COPY scripts/fixtures/gradle-proxy-contract/settings.gradle.kts /contract/settings.gradle.kts
COPY scripts/fixtures/gradle-proxy-contract/build.gradle.kts /contract/build.gradle.kts

FROM contract-base AS proxy-contract
RUN test "$HTTP_PROXY" = "http://proxy.example.test:8080" \
    && test "$HTTPS_PROXY" = "https://secure-proxy.example.test:8443" \
    && test "$NO_PROXY" = "localhost,.example.test,127.0.0.1"
RUN gradle --init-script /contract/gradle-proxy.init.gradle.kts verifyProxyContract --no-daemon

FROM contract-base AS no-proxy-contract
RUN gradle --init-script /contract/gradle-proxy.init.gradle.kts verifyNoProxyContract --no-daemon

FROM contract-base AS rejected-proxy-contract
RUN gradle --init-script /contract/gradle-proxy.init.gradle.kts help --no-daemon
