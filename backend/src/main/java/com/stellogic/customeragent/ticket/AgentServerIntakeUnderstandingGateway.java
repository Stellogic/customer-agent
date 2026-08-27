package com.stellogic.customeragent.ticket;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
@ConditionalOnProperty(name = "baseline.migrate-only", havingValue = "false", matchIfMissing = true)
final class AgentServerIntakeUnderstandingGateway implements IntakeUnderstandingGateway {
    private final RestClient agent;
    private final ObjectMapper json;

    AgentServerIntakeUnderstandingGateway(
            @Value("${baseline.agent.base-url}") String baseUrl,
            @Value("${baseline.agent.token}") String token,
            ObjectMapper json) {
        this.json = json;
        var requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(3));
        requestFactory.setReadTimeout(Duration.ofSeconds(12));
        this.agent =
                RestClient.builder()
                        .baseUrl(baseUrl)
                        .defaultHeader("Authorization", "Bearer " + token)
                        .requestFactory(requestFactory)
                        .build();
    }

    @Override
    public IntakeUnderstanding understand(IntakeUnderstandingRequest request) {
        try {
            List<Map<String, String>> orders =
                    request.visibleOrders().stream()
                            .map(
                                    order ->
                                            Map.of(
                                                    "reference",
                                                    order.reference(),
                                                    "summary",
                                                    order.summary()))
                            .toList();
            String response =
                    agent.post()
                            .uri("/runs/wait")
                            .contentType(MediaType.APPLICATION_JSON)
                            .body(
                                    Map.of(
                                            "assistant_id",
                                            "intake_agent",
                                            "input",
                                            Map.of(
                                                    "requested_by",
                                                    "spring",
                                                    "customer_message",
                                                    request.customerMessage(),
                                                    "visible_orders",
                                                    orders,
                                                    "current_order_reference",
                                                    nullToEmpty(request.currentOrderReference()),
                                                    "current_issue_summary",
                                                    nullToEmpty(request.currentIssueSummary()))))
                            .retrieve()
                            .body(String.class);
            return parse(response, request);
        } catch (IntakeAgentUnavailableException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new IntakeAgentUnavailableException();
        }
    }

    private IntakeUnderstanding parse(String response, IntakeUnderstandingRequest request) {
        try {
            JsonNode value = json.readTree(response).path("intake_understanding");
            String intent = requiredText(value, "intent");
            String status = requiredText(value, "status");
            String orderReference = optionalText(value, "candidate_order_reference");
            String issueKind = optionalText(value, "issue_kind");
            String issueSummary = optionalText(value, "issue_summary");
            String assistantMessage = requiredText(value, "assistant_message");
            if (!List.of("UNDERSTANDING", "CONFIRM").contains(intent)
                    || !List.of("READY_TO_CONFIRM", "NEEDS_CLARIFICATION", "CONFIRMED")
                            .contains(status)
                    || (orderReference != null
                            && request.visibleOrders().stream()
                                    .noneMatch(order -> order.reference().equals(orderReference)))
                    || (issueKind != null && !"LOGISTICS_DELAY".equals(issueKind))
                    || !hasConsistentShape(
                            intent,
                            status,
                            orderReference,
                            issueKind,
                            issueSummary,
                            request.currentOrderReference(),
                            request.currentIssueSummary())) {
                throw new IntakeAgentUnavailableException();
            }
            return new IntakeUnderstanding(
                    intent, status, orderReference, issueKind, issueSummary, assistantMessage);
        } catch (RuntimeException exception) {
            throw new IntakeAgentUnavailableException();
        }
    }

    private static boolean hasConsistentShape(
            String intent,
            String status,
            String orderReference,
            String issueKind,
            String issueSummary,
            String currentOrderReference,
            String currentIssueSummary) {
        if ("CONFIRM".equals(intent)) {
            return "CONFIRMED".equals(status)
                    && currentOrderReference != null
                    && currentOrderReference.equals(orderReference)
                    && "LOGISTICS_DELAY".equals(issueKind)
                    && currentIssueSummary != null
                    && currentIssueSummary.equals(issueSummary);
        }
        return !"CONFIRMED".equals(status);
    }

    private static String requiredText(JsonNode value, String field) {
        String text = optionalText(value, field);
        if (text == null) throw new IntakeAgentUnavailableException();
        return text;
    }

    private static String optionalText(JsonNode value, String field) {
        JsonNode fieldValue = value.path(field);
        if (fieldValue.isMissingNode() || fieldValue.isNull()) return null;
        String text = fieldValue.asText().trim();
        if (text.isEmpty() || text.length() > 2000) throw new IntakeAgentUnavailableException();
        return text;
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }
}
