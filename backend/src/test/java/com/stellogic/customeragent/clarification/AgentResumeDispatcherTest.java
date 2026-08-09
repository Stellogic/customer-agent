package com.stellogic.customeragent.clarification;

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

class AgentResumeDispatcherTest {
    @Test
    void lostPostResponseIsReconciledAndDoesNotCreateASecondEffectiveRun() throws Exception {
        UUID resumeId = UUID.fromString("16000000-0000-0000-0000-000000000021");
        UUID generationId = UUID.fromString("16000000-0000-0000-0000-000000000022");
        UUID ticketId = UUID.fromString("16000000-0000-0000-0000-000000000023");
        UUID threadId = UUID.fromString("16000000-0000-0000-0000-000000000024");
        UUID clarificationId = UUID.fromString("16000000-0000-0000-0000-000000000025");
        var pending = new AgentResumeStore.PendingResume(
                resumeId, generationId, ticketId, threadId, clarificationId, "b".repeat(64), "B");
        AgentResumeStore store = org.mockito.Mockito.mock(AgentResumeStore.class);
        when(store.claim()).thenReturn(Optional.of(pending), Optional.of(pending));
        AtomicInteger posts = new AtomicInteger();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/threads/" + threadId + "/runs", exchange -> {
            if ("GET".equals(exchange.getRequestMethod())) {
                String body = posts.get() == 0
                        ? "[]"
                        : "[{\"run_id\":\"created-before-response-loss\",\"metadata\":{\"resume_request_id\":\""
                                + resumeId + "\"}}]";
                respond(exchange, 200, body);
            } else {
                posts.incrementAndGet();
                exchange.close();
            }
        });
        server.start();
        try {
            var dispatcher = new AgentResumeDispatcher(
                    store, "http://127.0.0.1:" + server.getAddress().getPort(), "service-token", new ObjectMapper());

            dispatcher.dispatchNext();
            dispatcher.dispatchNext();

            verify(store).retry(org.mockito.ArgumentMatchers.eq(resumeId), org.mockito.ArgumentMatchers.any());
            verify(store).submitted(resumeId, "created-before-response-loss");
            org.junit.jupiter.api.Assertions.assertEquals(1, posts.get());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void unknownResumeResponseIsReconciledByStableMetadataWithoutASecondRun() throws Exception {
        UUID resumeId = UUID.fromString("16000000-0000-0000-0000-000000000011");
        UUID generationId = UUID.fromString("16000000-0000-0000-0000-000000000012");
        UUID ticketId = UUID.fromString("16000000-0000-0000-0000-000000000013");
        UUID threadId = UUID.fromString("16000000-0000-0000-0000-000000000014");
        UUID clarificationId = UUID.fromString("16000000-0000-0000-0000-000000000015");
        var pending = new AgentResumeStore.PendingResume(
                resumeId, generationId, ticketId, threadId, clarificationId, "a".repeat(64), "A");
        AgentResumeStore store = org.mockito.Mockito.mock(AgentResumeStore.class);
        when(store.claim()).thenReturn(Optional.of(pending));
        AtomicInteger posts = new AtomicInteger();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/threads/" + threadId + "/runs", exchange -> {
            if ("GET".equals(exchange.getRequestMethod())) {
                respond(exchange, 200, "[{\"run_id\":\"server-run\",\"metadata\":{\"resume_request_id\":\""
                        + resumeId + "\"}}]");
            } else {
                posts.incrementAndGet();
                respond(exchange, 200, "{\"run_id\":\"duplicate-run\"}");
            }
        });
        server.start();
        try {
            var dispatcher = new AgentResumeDispatcher(
                    store, "http://127.0.0.1:" + server.getAddress().getPort(), "service-token", new ObjectMapper());

            dispatcher.dispatchNext();

            verify(store).submitted(resumeId, "server-run");
            verify(store, never()).retry(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
            org.junit.jupiter.api.Assertions.assertEquals(0, posts.get());
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
