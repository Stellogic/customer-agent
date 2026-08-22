package com.stellogic.customeragent.stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

class AuthorizedSsePollingStreamHttpTest {
    @Test
    void destroyedHttpSessionRevokesAnAlreadyBoundStreamSource() {
        MockHttpSession session = new MockHttpSession();
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setSession(session);
        AuthorizedSsePollingStream.Source<String> source =
                AuthorizedSsePollingStream.requireCurrentHttpSession(
                        request,
                        null,
                        new AuthorizedSsePollingStream.Source<>() {
                            @Override
                            public List<String> events(String afterCursor) {
                                return List.of();
                            }

                            @Override
                            public void authorize() {}

                            @Override
                            public String cursor(String event) {
                                return event;
                            }

                            @Override
                            public SseEmitter.SseEventBuilder render(String event) {
                                return SseEmitter.event().data(event);
                            }
                        });

        source.authorize();
        AuthorizedSsePollingStream.invalidateHttpSession(session);

        assertThatThrownBy(source::authorize)
                .isInstanceOfSatisfying(
                        ResponseStatusException.class,
                        exception ->
                                assertThat(exception.getStatusCode())
                                        .isEqualTo(HttpStatus.UNAUTHORIZED));
    }

    @Test
    void subjectReplacementRevokesOldStreamButAllowsNewStreamForTheSameSession() {
        MockHttpSession session = new MockHttpSession();
        replaceSubject(session, "support-demo");
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setSession(session);
        AuthorizedSsePollingStream.Source<String> oldSource = guardedSource(request);

        replaceSubject(session, "approver-demo");
        AuthorizedSsePollingStream.Source<String> newSource = guardedSource(request);

        assertThatThrownBy(oldSource::authorize).isInstanceOf(ResponseStatusException.class);
        newSource.authorize();
    }

    @Test
    void staleRequestAuthenticationCannotBindTheReplacementSubjectsSessionAuthority() {
        MockHttpSession session = new MockHttpSession();
        replaceSubject(session, "approver-demo");
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setSession(session);

        assertThatThrownBy(() -> guardedSource(request, "support-demo"))
                .isInstanceOf(ResponseStatusException.class);
    }

    private void replaceSubject(MockHttpSession session, String subject) {
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        subject, "credential", List.of()));
        session.setAttribute(
                HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, context);
    }

    @Test
    void externalSseClosesWithinSixtySecondsAndCannotSendProjectionAfterRevocation()
            throws Exception {
        try (ConfigurableApplicationContext server = startServer()) {
            StreamAuthorities authorities = server.getBean(StreamAuthorities.class);
            URI baseUri = baseUri(server);
            HttpClient client =
                    HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();

            CompletableFuture<HttpResponse<String>> valid = open(client, baseUri, "valid");
            CompletableFuture<HttpResponse<String>> revoked = open(client, baseUri, "revoked");
            assertThat(authorities.awaitOpened("valid", 5, TimeUnit.SECONDS)).isTrue();
            assertThat(authorities.awaitOpened("revoked", 5, TimeUnit.SECONDS)).isTrue();
            long openedAt = System.nanoTime();

            sleepUntil(openedAt + TimeUnit.SECONDS.toNanos(58));
            authorities.revoke("revoked");

            HttpResponse<String> revokedResponse = revoked.get(2, TimeUnit.SECONDS);
            HttpResponse<String> validResponse = valid.get(4, TimeUnit.SECONDS);
            long elapsedMillis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - openedAt);

            assertThat(revokedResponse.statusCode()).isEqualTo(200);
            assertThat(revokedResponse.body())
                    .contains("data:old-projection")
                    .doesNotContain("forbidden-after-revocation");
            assertThat(validResponse.statusCode()).isEqualTo(200);
            assertThat(validResponse.body()).contains("data:old-projection");
            assertThat(elapsedMillis).isBetween(58_000L, 62_000L);
        }
    }

    private CompletableFuture<HttpResponse<String>> open(
            HttpClient client, URI baseUri, String streamId) {
        return client.sendAsync(
                HttpRequest.newBuilder(baseUri.resolve("/test/sse/" + streamId))
                        .timeout(Duration.ofSeconds(65))
                        .header("Accept", MediaType.TEXT_EVENT_STREAM_VALUE)
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private AuthorizedSsePollingStream.Source<String> guardedSource(
            MockHttpServletRequest request) {
        return guardedSource(request, sessionSubject(request));
    }

    private AuthorizedSsePollingStream.Source<String> guardedSource(
            MockHttpServletRequest request, String expectedSubject) {
        return AuthorizedSsePollingStream.requireCurrentHttpSession(
                request,
                expectedSubject,
                new AuthorizedSsePollingStream.Source<>() {
                    @Override
                    public List<String> events(String afterCursor) {
                        return List.of();
                    }

                    @Override
                    public void authorize() {}

                    @Override
                    public String cursor(String event) {
                        return event;
                    }

                    @Override
                    public SseEmitter.SseEventBuilder render(String event) {
                        return SseEmitter.event().data(event);
                    }
                });
    }

    private String sessionSubject(MockHttpServletRequest request) {
        Object value =
                request.getSession(false)
                        .getAttribute(
                                HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY);
        if (value instanceof org.springframework.security.core.context.SecurityContext context
                && context.getAuthentication() != null) {
            return context.getAuthentication().getName();
        }
        return null;
    }

    private ConfigurableApplicationContext startServer() {
        SpringApplication application = new SpringApplication(TestApplication.class);
        application.setWebApplicationType(WebApplicationType.SERVLET);
        return application.run("--server.port=0");
    }

    private URI baseUri(ConfigurableApplicationContext server) {
        int port = server.getEnvironment().getRequiredProperty("local.server.port", Integer.class);
        return URI.create("http://127.0.0.1:" + port);
    }

    private void sleepUntil(long deadlineNanos) throws InterruptedException {
        long remaining;
        while ((remaining = deadlineNanos - System.nanoTime()) > 0) {
            TimeUnit.NANOSECONDS.sleep(remaining);
        }
    }

    @Configuration(proxyBeanMethods = false)
    @EnableAutoConfiguration
    @Import(TestStreamController.class)
    static class TestApplication {
        @Bean
        StreamAuthorities streamAuthorities() {
            return new StreamAuthorities();
        }

        @Bean
        SecurityFilterChain testSecurity(HttpSecurity http) throws Exception {
            http.authorizeHttpRequests(requests -> requests.anyRequest().permitAll());
            http.csrf(csrf -> csrf.disable());
            return http.build();
        }
    }

    @RestController
    @RequestMapping("/test/sse")
    static class TestStreamController {
        private final StreamAuthorities authorities;

        TestStreamController(StreamAuthorities authorities) {
            this.authorities = authorities;
        }

        @GetMapping(value = "/{streamId}", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
        SseEmitter events(@PathVariable String streamId) {
            return AuthorizedSsePollingStream.open(
                    "external-sse-bound-" + streamId,
                    100,
                    AuthorizedSsePollingStream.MAX_AUTHORIZATION_STALENESS_MILLIS,
                    null,
                    new AuthorizedSsePollingStream.Source<String>() {
                        @Override
                        public List<String> events(String cursor) {
                            authorities.opened(streamId);
                            if (cursor == null) return List.of("old-projection");
                            if (!authorities.isAuthorized(streamId)) {
                                return List.of("forbidden-after-revocation");
                            }
                            return List.of();
                        }

                        @Override
                        public void authorize() {
                            if (!authorities.isAuthorized(streamId)) {
                                throw new ResponseStatusException(HttpStatus.FORBIDDEN);
                            }
                        }

                        @Override
                        public String cursor(String event) {
                            return event;
                        }

                        @Override
                        public SseEmitter.SseEventBuilder render(String event) {
                            return SseEmitter.event().id(event).data(event);
                        }
                    });
        }
    }

    static class StreamAuthorities {
        private final Map<String, AtomicBoolean> authorized = new ConcurrentHashMap<>();
        private final Map<String, CountDownLatch> opened = new ConcurrentHashMap<>();

        void opened(String streamId) {
            authorized.computeIfAbsent(streamId, ignored -> new AtomicBoolean(true));
            opened.computeIfAbsent(streamId, ignored -> new CountDownLatch(1)).countDown();
        }

        boolean awaitOpened(String streamId, long timeout, TimeUnit unit)
                throws InterruptedException {
            return opened.computeIfAbsent(streamId, ignored -> new CountDownLatch(1))
                    .await(timeout, unit);
        }

        boolean isAuthorized(String streamId) {
            return authorized.computeIfAbsent(streamId, ignored -> new AtomicBoolean(true)).get();
        }

        void revoke(String streamId) {
            authorized.get(streamId).set(false);
        }
    }
}
