package com.stellogic.customeragent.investigation;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
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

    @GetMapping("/facts")
    InvestigationFacts facts(
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
                "READ_INVESTIGATION_FACTS",
                authorization);
        return service.facts(ticketId, generationId);
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
}
