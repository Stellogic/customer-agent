package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Set;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/internal/agent/tickets/{ticketId}/generations/{generationId}")
public final class AgentInvestigationController {
    private final AgentInvestigationService service;
    private final byte[] agentToken;
    private final AgentKnowledgeRetrievalAdapter knowledge;

    AgentInvestigationController(
            AgentInvestigationService service,
            @Value("${baseline.identity.agent-token}") String agentToken,
            AgentKnowledgeRetrievalAdapter knowledge) {
        this.service = service;
        this.agentToken = agentToken.getBytes(StandardCharsets.UTF_8);
        this.knowledge = knowledge;
    }

    @PostMapping("/knowledge/search")
    AgentKnowledgeResult searchKnowledge(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false) UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody JsonNode payload) {
        requireScope(ticketId, generationId, scopedGenerationId, operation, "SEARCH_KNOWLEDGE", authorization);
        if (requestId == null || requestId.isBlank() || requestId.length() > 200
                || !payload.isObject() || !properties(payload).equals(Set.of("query"))
                || !payload.path("query").isString()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid knowledge request");
        }
        String query = payload.get("query").asString().trim();
        if (query.isEmpty() || query.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid knowledge query");
        }
        AgentKnowledgeResult receipt = service.authorizeKnowledgeSearch(ticketId, generationId, requestId, query);
        AgentKnowledgeResult result = receipt == null ? knowledge.searchCustomer(query) : knowledge.revalidateCustomer(receipt);
        return service.acceptKnowledgeSearch(ticketId, generationId, requestId, query, result);
    }

    @GetMapping("/capabilities")
    InvestigationCapabilityCatalog capabilities(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false)
                    UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation) {
        requireScope(
                ticketId,
                generationId,
                scopedGenerationId,
                operation,
                "USE_INVESTIGATION_CAPABILITY",
                authorization);
        return service.capabilities(ticketId, generationId);
    }

    @GetMapping("/customer-communication-context")
    CustomerCommunicationContext customerCommunicationContext(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false)
                    UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation) {
        requireScope(
                ticketId,
                generationId,
                scopedGenerationId,
                operation,
                "READ_CUSTOMER_COMMUNICATION_CONTEXT",
                authorization);
        return service.customerCommunicationContext(ticketId, generationId);
    }

    @GetMapping("/sibling-summary")
    SiblingTicketSummary siblingTicketSummary(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false)
                    UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation) {
        requireScope(
                ticketId,
                generationId,
                scopedGenerationId,
                operation,
                "READ_SIBLING_TICKET_SUMMARY",
                authorization);
        return service.siblingTicketSummary(ticketId, generationId);
    }

    @PostMapping("/capabilities/{capabilityName}")
    InvestigationCapabilityResult invoke(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @PathVariable String capabilityName,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false)
                    UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody JsonNode parameters) {
        requireScope(
                ticketId,
                generationId,
                scopedGenerationId,
                operation,
                "USE_INVESTIGATION_CAPABILITY",
                authorization);
        if (requestId == null || requestId.isBlank() || requestId.length() > 200) {
            service.auditRejected(ticketId, "MISSING_IDEMPOTENCY_IDENTITY");
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "missing stable capability request identity");
        }
        InvestigationCapability capability;
        try {
            capability = InvestigationCapability.valueOf(capabilityName);
        } catch (IllegalArgumentException exception) {
            service.auditRejected(ticketId, "UNKNOWN_INVESTIGATION_CAPABILITY");
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "unknown investigation capability");
        }
        Set<String> actualProperties =
                parameters != null && parameters.isObject()
                        ? properties(parameters)
                        : Set.of("INVALID");
        boolean requiresOrderReference = capability.requiresOrderReference();
        boolean valid = !requiresOrderReference && actualProperties.isEmpty();
        if (requiresOrderReference) {
            JsonNode orderReference = parameters == null ? null : parameters.get("orderReference");
            valid =
                    Set.of("orderReference").equals(actualProperties)
                            && orderReference != null
                            && orderReference.isString()
                            && !orderReference.asText().isBlank()
                            && orderReference.asText().length() <= 200;
        }
        if (!valid) {
            service.auditRejected(ticketId, "INVALID_CAPABILITY_PARAMETERS");
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "invalid investigation capability parameters");
        }
        return service.invoke(
                ticketId,
                generationId,
                requestId.trim(),
                capability,
                new InvestigationCapabilityParameters(
                        requiresOrderReference ? parameters.get("orderReference").asText() : null));
    }

    @PostMapping("/conclusions")
    ConclusionAcceptance submit(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false)
                    UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody JsonNode payload) {
        requireScope(
                ticketId,
                generationId,
                scopedGenerationId,
                operation,
                "SUBMIT_INVESTIGATION_CONCLUSION",
                authorization);
        if (requestId == null || requestId.isBlank() || requestId.length() > 200) {
            service.auditRejected(ticketId, "MISSING_IDEMPOTENCY_IDENTITY");
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "missing stable command identity");
        }
        InvestigationConclusion conclusion = parseConclusion(ticketId, payload);
        return service.submit(ticketId, generationId, requestId, conclusion);
    }

    private InvestigationConclusion parseConclusion(UUID ticketId, JsonNode payload) {
        Set<String> expected =
                Set.of(
                        "compensationRequired",
                        "reasonCode",
                        "delayHours",
                        "delaySeconds",
                        "orderReference",
                        "evidenceRefs",
                        "riskScenario",
                        "sufficiencyPolicyVersion",
                        "evidence",
                        "customerReply");
        if (payload == null || !payload.isObject() || !expected.equals(properties(payload))) {
            return malformedConclusion(ticketId);
        }
        JsonNode reply = payload.get("customerReply");
        Set<String> expectedReply =
                Set.of(
                        "schemaVersion",
                        "body",
                        "intent",
                        "evidenceRefs",
                        "escalationRequired",
                        "referencedOrder");
        if (reply == null || !reply.isObject() || !expectedReply.equals(properties(reply))) {
            return malformedConclusion(ticketId);
        }
        try {
            return new InvestigationConclusion(
                    requiredBoolean(payload, "compensationRequired"),
                    DecisionReasonCode.valueOf(requiredText(payload, "reasonCode")),
                    requiredInt(payload, "delayHours"),
                    requiredLong(payload, "delaySeconds"),
                    requiredText(payload, "orderReference"),
                    requiredTextList(payload, "evidenceRefs"),
                    new EvidenceSufficiencyClaim(
                            InvestigationRiskScenario.valueOf(
                                    requiredText(payload, "riskScenario")),
                            requiredText(payload, "sufficiencyPolicyVersion"),
                            requiredEvidence(payload, "evidence")),
                    new CustomerReplyEnvelope(
                            requiredText(reply, "schemaVersion"),
                            requiredText(reply, "body"),
                            CustomerReplyIntent.valueOf(requiredText(reply, "intent")),
                            requiredTextList(reply, "evidenceRefs"),
                            requiredBoolean(reply, "escalationRequired"),
                            requiredText(reply, "referencedOrder")));
        } catch (IllegalArgumentException exception) {
            return malformedConclusion(ticketId);
        }
    }

    private InvestigationConclusion malformedConclusion(UUID ticketId) {
        service.auditRejected(ticketId, "MALFORMED_CONCLUSION");
        throw new ResponseStatusException(
                HttpStatus.UNPROCESSABLE_ENTITY, "malformed investigation conclusion");
    }

    private static String requiredText(JsonNode object, String name) {
        JsonNode value = object.get(name);
        if (value == null || !value.isString() || value.asText().isBlank()) {
            throw new IllegalArgumentException("invalid string");
        }
        return value.asText();
    }

    private static boolean requiredBoolean(JsonNode object, String name) {
        JsonNode value = object.get(name);
        if (value == null || !value.isBoolean()) {
            throw new IllegalArgumentException("invalid boolean");
        }
        return value.asBoolean();
    }

    private static int requiredInt(JsonNode object, String name) {
        JsonNode value = object.get(name);
        if (value == null || !value.isInt()) {
            throw new IllegalArgumentException("invalid integer");
        }
        return value.asInt();
    }

    private static long requiredLong(JsonNode object, String name) {
        JsonNode value = object.get(name);
        if (value == null || !value.isIntegralNumber()) {
            throw new IllegalArgumentException("invalid long");
        }
        return value.asLong();
    }

    private static java.util.List<String> requiredTextList(JsonNode object, String name) {
        JsonNode value = object.get(name);
        if (value == null || !value.isArray()) {
            throw new IllegalArgumentException("invalid string list");
        }
        java.util.ArrayList<String> result = new java.util.ArrayList<>();
        for (JsonNode item : value) {
            if (!item.isString() || item.asText().isBlank()) {
                throw new IllegalArgumentException("invalid string list item");
            }
            result.add(item.asText());
        }
        return java.util.List.copyOf(result);
    }

    private static java.util.List<ConclusionEvidence> requiredEvidence(
            JsonNode object, String name) {
        JsonNode value = object.get(name);
        if (value == null || !value.isArray() || value.isEmpty()) {
            throw new IllegalArgumentException("invalid evidence list");
        }
        java.util.ArrayList<ConclusionEvidence> result = new java.util.ArrayList<>();
        for (JsonNode item : value) {
            if (item == null
                    || !item.isObject()
                    || !Set.of("evidenceReference", "applicability").equals(properties(item))) {
                throw new IllegalArgumentException("invalid evidence item");
            }
            java.util.List<EvidenceApplicability> applicability =
                    requiredTextList(item, "applicability").stream()
                            .map(EvidenceApplicability::valueOf)
                            .toList();
            result.add(
                    new ConclusionEvidence(requiredText(item, "evidenceReference"), applicability));
        }
        return java.util.List.copyOf(result);
    }

    private void requireScope(
            UUID ticketId,
            UUID generationId,
            UUID scopedGenerationId,
            String operation,
            String expectedOperation,
            String authorization) {
        byte[] actual =
                authorization != null && authorization.startsWith("Bearer ")
                        ? authorization.substring(7).getBytes(StandardCharsets.UTF_8)
                        : new byte[0];
        boolean allowed =
                MessageDigest.isEqual(actual, agentToken)
                        && generationId.equals(scopedGenerationId)
                        && expectedOperation.equals(operation);
        if (!allowed) {
            service.auditRejected(ticketId, "CAPABILITY_SCOPE_REJECTED");
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "agent capability is outside the current scope");
        }
    }

    private static Set<String> properties(JsonNode object) {
        Set<String> names = new java.util.HashSet<>();
        names.addAll(object.propertyNames());
        return Set.copyOf(names);
    }
}
