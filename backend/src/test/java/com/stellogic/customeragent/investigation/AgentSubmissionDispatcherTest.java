package com.stellogic.customeragent.investigation;

import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class AgentSubmissionDispatcherTest {
    @Test
    void unknownRunResponseIsReconciledByStableSubmissionMetadata() throws Exception {
        UUID submissionId = UUID.fromString("14000000-0000-0000-0000-000000000001");
        UUID generationId = UUID.fromString("14000000-0000-0000-0000-000000000002");
        UUID ticketId = UUID.fromString("14000000-0000-0000-0000-000000000003");
        UUID threadId = UUID.fromString("14000000-0000-0000-0000-000000000004");
        var submission =
                new AgentSubmissionStore.PendingSubmission(
                        submissionId, generationId, ticketId, threadId);
        AgentSubmissionStore store = org.mockito.Mockito.mock(AgentSubmissionStore.class);
        when(store.claim()).thenReturn(Optional.of(submission));
        AtomicInteger runPosts = new AtomicInteger();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext(
                "/threads/" + threadId,
                exchange -> {
                    if (exchange.getRequestURI().getPath().endsWith("/runs")) {
                        if ("GET".equals(exchange.getRequestMethod())) {
                            respond(
                                    exchange,
                                    200,
                                    "[{\"run_id\":\"server-run\",\"metadata\":{\"submission_request_id\":\""
                                            + submissionId
                                            + "\"}}]");
                        } else {
                            runPosts.incrementAndGet();
                            respond(exchange, 200, "{}");
                        }
                    } else {
                        respond(exchange, 200, "{}");
                    }
                });
        server.start();
        try {
            var dispatcher =
                    new AgentSubmissionDispatcher(
                            store,
                            "http://127.0.0.1:" + server.getAddress().getPort(),
                            "service-token",
                            new ObjectMapper());

            dispatcher.dispatchNext();

            verify(store).submitted(submissionId);
            verify(store, never())
                    .retry(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
            org.junit.jupiter.api.Assertions.assertEquals(0, runPosts.get());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void terminalFailedRunCreatesAnotherRunOnTheStableThread() throws Exception {
        UUID submissionId = UUID.fromString("14000000-0000-0000-0000-000000000011");
        UUID generationId = UUID.fromString("14000000-0000-0000-0000-000000000012");
        UUID ticketId = UUID.fromString("14000000-0000-0000-0000-000000000013");
        UUID threadId = UUID.fromString("14000000-0000-0000-0000-000000000014");
        var submission =
                new AgentSubmissionStore.PendingSubmission(
                        submissionId, generationId, ticketId, threadId);
        AgentSubmissionStore store = org.mockito.Mockito.mock(AgentSubmissionStore.class);
        when(store.claim()).thenReturn(Optional.of(submission));
        AtomicInteger runPosts = new AtomicInteger();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext(
                "/threads/" + threadId,
                exchange -> {
                    if (exchange.getRequestURI().getPath().endsWith("/runs")) {
                        if ("GET".equals(exchange.getRequestMethod())) {
                            respond(
                                    exchange,
                                    200,
                                    "[{\"run_id\":\"failed-run\",\"status\":\"error\",\"metadata\":{\"submission_request_id\":\""
                                            + submissionId
                                            + "\"}}]");
                        } else {
                            runPosts.incrementAndGet();
                            respond(exchange, 200, "{}");
                        }
                    } else {
                        respond(exchange, 200, "{}");
                    }
                });
        server.start();
        try {
            var dispatcher =
                    new AgentSubmissionDispatcher(
                            store,
                            "http://127.0.0.1:" + server.getAddress().getPort(),
                            "service-token",
                            new ObjectMapper());

            dispatcher.dispatchNext();

            verify(store).submitted(submissionId);
            org.junit.jupiter.api.Assertions.assertEquals(1, runPosts.get());
        } finally {
            server.stop(0);
        }
    }

    private static void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
