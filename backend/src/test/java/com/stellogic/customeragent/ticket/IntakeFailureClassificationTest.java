package com.stellogic.customeragent.ticket;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class IntakeFailureClassificationTest {
    private HttpServer server;
    private AgentServerIntakeUnderstandingGateway gateway;
    private int status = 200;
    private String body;

    @BeforeEach
    void startServer() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext(
                "/runs/wait",
                exchange -> {
                    exchange.getRequestBody().readAllBytes();
                    byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                    exchange.getResponseHeaders().set("Content-Type", "application/json");
                    exchange.sendResponseHeaders(status, bytes.length);
                    try (var output = exchange.getResponseBody()) {
                        output.write(bytes);
                    }
                });
        server.start();
        gateway =
                new AgentServerIntakeUnderstandingGateway(
                        "http://127.0.0.1:" + server.getAddress().getPort(),
                        "test-only",
                        new ObjectMapper());
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    @Test
    void httpFailureIsTransportAndDoesNotRetainResponseOrCause() {
        status = 503;
        body = "private-response-sentinel";
        assertFailure(IntakeAgentUnavailableException.Reason.TRANSPORT);
    }

    @Test
    void malformedResponseIsParseFailure() {
        body = "not-json-private-response-sentinel";
        assertFailure(IntakeAgentUnavailableException.Reason.RESPONSE_PARSE);
    }

    @Test
    void missingRequiredArrayIsParseFailure() {
        body = response().replace("\"pending_issue_kinds\": [\"DUPLICATE_CHARGE\"],", "");
        assertFailure(IntakeAgentUnavailableException.Reason.RESPONSE_PARSE);
    }

    @Test
    void droppingPendingTailIsStateFailureAndSurvivesBothCatchBoundaries() {
        body = response().replace("[\"DUPLICATE_CHARGE\"]", "[]");
        assertFailure(IntakeAgentUnavailableException.Reason.STATE_CONSISTENCY);
    }

    @Test
    void advancingOnlyTheClarifiedHeadStillSucceeds() {
        body = response();
        IntakeUnderstanding result = gateway.understand(request());
        assertThat(result.issues())
                .containsExactly(new ProposedIntakeIssue("PACKAGE_NOT_RECEIVED", "包裹未收到"));
        assertThat(result.pendingIssueKinds()).containsExactly("DUPLICATE_CHARGE");
        assertThat(result.status()).isEqualTo("NEEDS_CLARIFICATION");
    }

    private void assertFailure(IntakeAgentUnavailableException.Reason reason) {
        var failure =
                catchThrowableOfType(
                        IntakeAgentUnavailableException.class, () -> gateway.understand(request()));
        assertThat(failure).isNotNull();
        assertThat(failure.reason()).isEqualTo(reason);
        assertThat(failure.getMessage()).isNull();
        assertThat(failure.getCause()).isNull();
    }

    private static IntakeUnderstandingRequest request() {
        return new IntakeUnderstandingRequest(
                "是的，包裹至今仍未收到",
                List.of(new CustomerVisibleOrderSummary("ORDER-TEST", "合成订单", "v1")),
                "ORDER-TEST",
                null,
                List.of(),
                List.of("PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"),
                List.of());
    }

    private static String response() {
        return """
                {"intake_understanding": {
                  "intent": "UNDERSTANDING", "status": "NEEDS_CLARIFICATION",
                  "candidate_order_reference": "ORDER-TEST",
                  "issues": [{"kind":"PACKAGE_NOT_RECEIVED", "summary":"包裹未收到"}],
                  "pending_issue_kinds": ["DUPLICATE_CHARGE"],
                  "remaining_order_references": [], "assistant_message": "请确认扣款问题"
                }}
                """;
    }
}
