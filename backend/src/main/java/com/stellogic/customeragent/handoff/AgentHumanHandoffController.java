package com.stellogic.customeragent.handoff;

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
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/agent/tickets/{ticketId}/generations/{generationId}")
final class AgentHumanHandoffController {
    private final HumanHandoffService service;
    private final byte[] agentToken;

    AgentHumanHandoffController(
            HumanHandoffService service,
            @Value("${baseline.identity.agent-token}") String agentToken) {
        this.service = service;
        this.agentToken = agentToken.getBytes(StandardCharsets.UTF_8);
    }

    @PostMapping("/human-handoff")
    @ResponseStatus(HttpStatus.ACCEPTED)
    AgentHumanHandoffResult request(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false)
                    UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody AgentHumanHandoffBody body) {
        requireScope(ticketId, generationId, scopedGenerationId, operation, authorization);
        if (requestId == null || requestId.isBlank() || requestId.length() > 200) {
            service.auditAgentRejected(ticketId, "MISSING_IDEMPOTENCY_IDENTITY");
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "missing stable command identity");
        }
        return service.requestAgentHumanHandoff(
                new RequestAgentHumanHandoff(
                        ticketId, generationId, requestId, body.reasonCode(), body.summary()));
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
        boolean allowed =
                MessageDigest.isEqual(actual, agentToken)
                        && generationId.equals(scopedGenerationId)
                        && "REQUEST_HUMAN_HANDOFF".equals(operation);
        if (!allowed) {
            service.auditAgentRejected(ticketId, "CAPABILITY_SCOPE_REJECTED");
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "agent capability is outside the current scope");
        }
    }

    record AgentHumanHandoffBody(
            AgentHumanHandoffReason reasonCode, AgentHumanHandoffSummary summary) {}
}
