package com.stellogic.customeragent.clarification;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/agent/tickets/{ticketId}/generations/{generationId}/clarifications")
final class AgentClarificationController {
    private final ClarificationService service;
    private final byte[] agentToken;

    AgentClarificationController(
            ClarificationService service,
            @Value("${baseline.identity.agent-token}") String agentToken) {
        this.service = service;
        this.agentToken = agentToken.getBytes(StandardCharsets.UTF_8);
    }

    @PostMapping
    ClarificationRequestResult create(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false)
                    UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody CreateBody body) {
        requireScope(ticketId, generationId, scopedGenerationId, operation, authorization);
        if (requestId == null || requestId.isBlank() || requestId.length() > 200) {
            service.auditRejected(ticketId, "MISSING_CLARIFICATION_IDENTITY");
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "missing stable clarification identity");
        }
        return service.create(
                new CreateClarification(ticketId, generationId, requestId, body.reasonCode()));
    }

    private void requireScope(
            UUID ticketId,
            UUID generationId,
            UUID scopedGenerationId,
            String operation,
            String authorization) {
        byte[] actual =
                authorization != null && authorization.startsWith("Bearer ")
                        ? authorization.substring(7).getBytes(StandardCharsets.UTF_8)
                        : new byte[0];
        if (!MessageDigest.isEqual(actual, agentToken)
                || !generationId.equals(scopedGenerationId)
                || !"CREATE_CUSTOMER_CLARIFICATION".equals(operation)) {
            service.auditRejected(ticketId, "CAPABILITY_SCOPE_REJECTED");
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "agent capability is outside the current scope");
        }
    }

    record CreateBody(String reasonCode) {}
}
