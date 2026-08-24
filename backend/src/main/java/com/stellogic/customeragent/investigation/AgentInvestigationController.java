package com.stellogic.customeragent.investigation;

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

    AgentInvestigationController(
            AgentInvestigationService service,
            @Value("${baseline.identity.agent-token}") String agentToken) {
        this.service = service;
        this.agentToken = agentToken.getBytes(StandardCharsets.UTF_8);
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
            @RequestBody InvestigationConclusion conclusion) {
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
        return service.submit(ticketId, generationId, requestId, conclusion);
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
