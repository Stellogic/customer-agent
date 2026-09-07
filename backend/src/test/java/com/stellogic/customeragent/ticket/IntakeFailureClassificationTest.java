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
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
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

    @Test
    void successfulIntakeRetainsCallEvidenceReceivedFromAgentHttpResponse() {
        ObjectMapper json = new ObjectMapper();
        var evidence =
                json.readTree(
                        """
                {
                  "schemaVersion":"intake-call-evidence-v1",
                  "logicalCalls":1,"providerAttempts":1,
                  "inputTokens":120,"outputTokens":30,"tokens":150,
                  "costMicros":8,"currency":"USD","usageComplete":true,
                  "failureClassification":"",
                  "attempts":[{
                    "internalCallId":"intake-call-230","attemptId":"intake-attempt-230",
                    "attemptNumber":1,"provider":"deepseek",
                    "providerResponseId":"synthetic-response-230","requestModel":"deepseek-v4-flash",
                    "responseModel":"deepseek-v4-flash","providerHttpStatus":200,
                    "inputTokens":120,"outputTokens":30,"totalTokens":150,
                    "cachedTokens":null,"reasoningTokens":null
                  }]
                }
                """);
        var response = (tools.jackson.databind.node.ObjectNode) json.readTree(response());
        response.set("intake_call_evidence", evidence);
        body = json.writeValueAsString(response);

        IntakeUnderstanding result = gateway.understand(request());

        assertThat(result.status()).isEqualTo("NEEDS_CLARIFICATION");
        assertThat(result.pendingIssueKinds()).containsExactly("DUPLICATE_CHARGE");
        assertThat(json.valueToTree(result).path("callEvidence")).isEqualTo(evidence);
    }

    @Test
    void providerRejectionIsNotParseFailureAndRetainsUnknownUsageEvidence() {
        body =
                """
                {
                  "intake_failure":{"code":"PROVIDER_REQUEST_REJECTED"},
                  "intake_call_evidence":{
                    "schemaVersion":"intake-call-evidence-v1","currency":"USD",
                    "logicalCalls":1,"providerAttempts":1,"tokens":null,"costMicros":null,
                    "usageComplete":false,"failureClassification":"PROVIDER_REQUEST_REJECTED",
                    "attempts":[{"internalCallId":"rejected-intake-230","attemptId":"rejected-attempt-230",
                      "attemptNumber":1,"provider":"deepseek","providerHttpStatus":400,
                      "inputTokens":null,"outputTokens":null,"totalTokens":null}]
                  }
                }
                """;

        var failure =
                catchThrowableOfType(
                        IntakeAgentUnavailableException.class, () -> gateway.understand(request()));

        assertThat(failure).isNotNull();
        assertThat(failure.reason())
                .isEqualTo(IntakeAgentUnavailableException.Reason.PROVIDER_FAILURE);
        var evidence = failure.callEvidence();
        assertThat(evidence.path("failureClassification").asText())
                .isEqualTo("PROVIDER_REQUEST_REJECTED");
        assertThat(evidence.path("tokens").isNull()).isTrue();
        assertThat(evidence.path("costMicros").isNull()).isTrue();
        assertThat(evidence.path("attempts").get(0).path("providerHttpStatus").asInt())
                .isEqualTo(400);
        assertThat(failure.getMessage()).isNull();
        assertThat(failure.getCause()).isNull();
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

    @ParameterizedTest
    @EnumSource(
            value = IntakeAgentUnavailableException.Reason.class,
            names = {"RESPONSE_PARSE", "STATE_CONSISTENCY"})
    void rejectedIntakeRetainsKnownUsageWithoutRetainingTheRawResponse(
            IntakeAgentUnavailableException.Reason reason) {
        ObjectMapper json = new ObjectMapper();
        var evidence =
                json.readTree(
                        """
                {
                  "schemaVersion":"intake-call-evidence-v1","currency":"USD",
                  "logicalCalls":1,"providerAttempts":1,"inputTokens":120,"outputTokens":30,
                  "tokens":150,"costMicros":8,"usageComplete":true,
                  "failureClassification":"SCHEMA_MISMATCH",
                  "attempts":[{"internalCallId":"failed-intake-230","attemptId":"failed-attempt-230",
                    "attemptNumber":1,"provider":"deepseek","providerHttpStatus":200,
                    "inputTokens":120,"outputTokens":30,"totalTokens":150}]
                }
                """);
        tools.jackson.databind.node.ObjectNode response;
        if (reason == IntakeAgentUnavailableException.Reason.RESPONSE_PARSE) {
            response = json.createObjectNode();
            response.putObject("intake_failure").put("code", "SCHEMA_MISMATCH");
        } else {
            response =
                    (tools.jackson.databind.node.ObjectNode)
                            json.readTree(response().replace("[\"DUPLICATE_CHARGE\"]", "[]"));
            ((tools.jackson.databind.node.ObjectNode) evidence).put("failureClassification", "");
        }
        response.set("intake_call_evidence", evidence);
        response.put("raw_output", "private-response-sentinel");
        body = json.writeValueAsString(response);

        var failure =
                catchThrowableOfType(
                        IntakeAgentUnavailableException.class, () -> gateway.understand(request()));

        assertThat(failure).isNotNull();
        assertThat(failure.reason()).isEqualTo(reason);
        assertThat(failure.callEvidence())
                .isEqualTo(evidence)
                .satisfies(
                        value ->
                                assertThat(json.writeValueAsString(value))
                                        .doesNotContain("private-response-sentinel"));
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
