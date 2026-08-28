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
                                                    nullToEmpty(request.currentIssueSummary()),
                                                    "current_issues",
                                                    request.currentIssues().stream()
                                                            .map(
                                                                    issue ->
                                                                            Map.of(
                                                                                    "kind",
                                                                                    issue.kind(),
                                                                                    "summary",
                                                                                    issue
                                                                                            .summary()))
                                                            .toList(),
                                                    "current_pending_issue_kinds",
                                                    request.currentPendingIssueKinds())))
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
            List<ProposedIntakeIssue> issues = parseIssues(value.path("issues"));
            List<String> pendingIssueKinds =
                    parsePendingIssueKinds(value.path("pending_issue_kinds"));
            String assistantMessage = requiredText(value, "assistant_message");
            if (!List.of("UNDERSTANDING", "CONFIRM").contains(intent)
                    || !List.of("READY_TO_CONFIRM", "NEEDS_CLARIFICATION", "CONFIRMED")
                            .contains(status)
                    || (orderReference != null
                            && request.visibleOrders().stream()
                                    .noneMatch(order -> order.reference().equals(orderReference)))
                    || !hasConsistentShape(
                            intent,
                            status,
                            orderReference,
                            issues,
                            pendingIssueKinds,
                            request.currentOrderReference(),
                            request.currentIssues(),
                            request.currentPendingIssueKinds())) {
                throw new IntakeAgentUnavailableException();
            }
            return new IntakeUnderstanding(
                    intent, status, orderReference, issues, pendingIssueKinds, assistantMessage);
        } catch (RuntimeException exception) {
            throw new IntakeAgentUnavailableException();
        }
    }

    static boolean hasConsistentShape(
            String intent,
            String status,
            String orderReference,
            List<ProposedIntakeIssue> issues,
            List<String> pendingIssueKinds,
            String currentOrderReference,
            List<ProposedIntakeIssue> currentIssues,
            List<String> currentPendingIssueKinds) {
        if ("CONFIRM".equals(intent)) {
            return "CONFIRMED".equals(status)
                    && currentOrderReference != null
                    && currentOrderReference.equals(orderReference)
                    && !currentIssues.isEmpty()
                    && currentIssues.equals(issues)
                    && currentPendingIssueKinds.isEmpty()
                    && pendingIssueKinds.isEmpty();
        }
        boolean validShape =
                !"CONFIRMED".equals(status)
                        && !("READY_TO_CONFIRM".equals(status)
                                && (issues.isEmpty() || !pendingIssueKinds.isEmpty()))
                        && pendingIssueKinds.stream()
                                .noneMatch(
                                        kind ->
                                                issues.stream()
                                                        .anyMatch(
                                                                issue ->
                                                                        issue.kind().equals(kind)));
        if (!validShape
                || (currentOrderReference != null && !currentOrderReference.equals(orderReference))
                || issues.size() < currentIssues.size()
                || !issues.subList(0, currentIssues.size()).equals(currentIssues)) {
            return false;
        }
        if (currentPendingIssueKinds.isEmpty()) return true;

        String pendingHead = currentPendingIssueKinds.getFirst();
        List<String> pendingTail =
                currentPendingIssueKinds.subList(1, currentPendingIssueKinds.size());
        if (issues.equals(currentIssues)) {
            return pendingIssueKinds.equals(currentPendingIssueKinds)
                    || pendingIssueKinds.equals(pendingTail);
        }
        return issues.size() == currentIssues.size() + 1
                && issues.getLast().kind().equals(pendingHead)
                && pendingIssueKinds.equals(pendingTail);
    }

    private static List<ProposedIntakeIssue> parseIssues(JsonNode value) {
        if (!value.isArray() || value.size() > 8) throw new IntakeAgentUnavailableException();
        java.util.ArrayList<ProposedIntakeIssue> issues = new java.util.ArrayList<>();
        java.util.HashSet<String> kinds = new java.util.HashSet<>();
        for (JsonNode issue : value) {
            String kind = requiredText(issue, "kind");
            String summary = requiredText(issue, "summary");
            if (!List.of("LOGISTICS_DELAY", "PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE")
                            .contains(kind)
                    || !kinds.add(kind)) {
                throw new IntakeAgentUnavailableException();
            }
            issues.add(new ProposedIntakeIssue(kind, summary));
        }
        return List.copyOf(issues);
    }

    private static List<String> parsePendingIssueKinds(JsonNode value) {
        if (!value.isArray() || value.size() > 3) throw new IntakeAgentUnavailableException();
        java.util.ArrayList<String> kinds = new java.util.ArrayList<>();
        for (JsonNode item : value) {
            String kind = item.asText().trim();
            if (!List.of("LOGISTICS_DELAY", "PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE")
                            .contains(kind)
                    || kinds.contains(kind)) {
                throw new IntakeAgentUnavailableException();
            }
            kinds.add(kind);
        }
        return List.copyOf(kinds);
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
