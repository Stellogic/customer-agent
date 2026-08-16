package com.stellogic.customeragent.identity;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;
import tools.jackson.databind.ObjectMapper;

class HumanSessionLifecycleTest {
    private static final String SESSION_COOKIE = "JSESSIONID";

    @Test
    void sessionIsNonPersistentExpiresAfterThirtyMinutesOfInactivityAndDiesOnRestart()
            throws Exception {
        String authenticatedCookie;
        try (ConfigurableApplicationContext firstServer = startServer()) {
            HttpClient client = HttpClient.newHttpClient();
            URI baseUri = baseUri(firstServer);

            HttpResponse<String> csrf =
                    client.send(
                            HttpRequest.newBuilder(baseUri.resolve("/api/auth/csrf")).GET().build(),
                            HttpResponse.BodyHandlers.ofString());
            String anonymousSetCookie = sessionSetCookie(csrf);
            assertSessionOnlyCookie(anonymousSetCookie);

            String anonymousCookie = requestCookie(anonymousSetCookie);
            String csrfToken =
                    firstServer
                            .getBean(ObjectMapper.class)
                            .readTree(csrf.body())
                            .get("token")
                            .asText();
            HttpResponse<String> login =
                    client.send(
                            HttpRequest.newBuilder(baseUri.resolve("/api/auth/login"))
                                    .header("Cookie", anonymousCookie)
                                    .header("X-CSRF-TOKEN", csrfToken)
                                    .header(
                                            "Content-Type",
                                            MediaType.APPLICATION_FORM_URLENCODED_VALUE)
                                    .POST(
                                            HttpRequest.BodyPublishers.ofString(
                                                    "username=customer-demo&password=local-demo-password&remember-me=on"))
                                    .build(),
                            HttpResponse.BodyHandlers.ofString());

            assertThat(login.statusCode()).isEqualTo(HttpServletResponse.SC_NO_CONTENT);
            String authenticatedSetCookie = sessionSetCookie(login);
            assertSessionOnlyCookie(authenticatedSetCookie);
            authenticatedCookie = requestCookie(authenticatedSetCookie);

            HttpResponse<String> current = getCurrentSession(client, baseUri, authenticatedCookie);
            assertThat(current.statusCode()).isEqualTo(HttpServletResponse.SC_OK);
            assertThat(firstServer.getBean(SessionIntervalProbe.class).seconds()).isEqualTo(1800);
        }

        try (ConfigurableApplicationContext restartedServer = startServer()) {
            HttpResponse<String> afterRestart =
                    getCurrentSession(
                            HttpClient.newHttpClient(),
                            baseUri(restartedServer),
                            authenticatedCookie);
            assertThat(afterRestart.statusCode()).isEqualTo(HttpServletResponse.SC_UNAUTHORIZED);
        }
    }

    private ConfigurableApplicationContext startServer() {
        SpringApplication application = new SpringApplication(LifecycleTestApplication.class);
        application.setWebApplicationType(WebApplicationType.SERVLET);
        return application.run(
                "--server.port=0",
                "--spring.profiles.active=local-demo",
                "--server.servlet.session.timeout=30m",
                "--server.servlet.session.cookie.http-only=true",
                "--server.servlet.session.cookie.secure=true",
                "--server.servlet.session.cookie.same-site=strict");
    }

    private URI baseUri(ConfigurableApplicationContext server) {
        int port = server.getEnvironment().getRequiredProperty("local.server.port", Integer.class);
        return URI.create("http://127.0.0.1:" + port);
    }

    private HttpResponse<String> getCurrentSession(
            HttpClient client, URI baseUri, String sessionCookie)
            throws IOException, InterruptedException {
        return client.send(
                HttpRequest.newBuilder(baseUri.resolve("/api/auth/session"))
                        .header("Cookie", sessionCookie)
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    private String sessionSetCookie(HttpResponse<?> response) {
        return response.headers().allValues("Set-Cookie").stream()
                .filter(value -> value.startsWith(SESSION_COOKIE + "="))
                .findFirst()
                .orElseThrow(() -> new AssertionError("response did not set a session cookie"));
    }

    private String requestCookie(String setCookie) {
        return setCookie.substring(0, setCookie.indexOf(';'));
    }

    private void assertSessionOnlyCookie(String setCookie) {
        assertThat(setCookie)
                .containsIgnoringCase("HttpOnly")
                .containsIgnoringCase("Secure")
                .containsIgnoringCase("SameSite=Strict")
                .doesNotContainIgnoringCase("Expires=")
                .doesNotContainIgnoringCase("Max-Age=");
    }

    @Configuration(proxyBeanMethods = false)
    @EnableAutoConfiguration
    @Import({
        AuthSessionController.class,
        HumanSecurityConfiguration.class,
        LocalDemoHumanAccountsConfiguration.class
    })
    static class LifecycleTestApplication {
        @Bean
        SessionIntervalProbe sessionIntervalProbe() {
            return new SessionIntervalProbe();
        }

        @Bean
        FilterRegistrationBean<OncePerRequestFilter> sessionIntervalProbeFilter(
                SessionIntervalProbe probe) {
            FilterRegistrationBean<OncePerRequestFilter> registration =
                    new FilterRegistrationBean<>();
            registration.setFilter(
                    new OncePerRequestFilter() {
                        @Override
                        protected void doFilterInternal(
                                HttpServletRequest request,
                                HttpServletResponse response,
                                FilterChain filterChain)
                                throws ServletException, IOException {
                            filterChain.doFilter(request, response);
                            HttpSession session = request.getSession(false);
                            if (session != null
                                    && request.getRequestURI().equals("/api/auth/session")) {
                                probe.record(session.getMaxInactiveInterval());
                            }
                        }
                    });
            return registration;
        }
    }

    static class SessionIntervalProbe {
        private final AtomicInteger seconds = new AtomicInteger();

        void record(int intervalSeconds) {
            seconds.set(intervalSeconds);
        }

        int seconds() {
            return seconds.get();
        }
    }
}
