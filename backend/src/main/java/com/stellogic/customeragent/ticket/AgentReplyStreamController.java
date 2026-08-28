package com.stellogic.customeragent.ticket;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
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
final class AgentReplyStreamController {
    private static final Set<String> PROGRESS_STAGES =
            Set.of("UNDERSTANDING", "VERIFYING_FACTS", "QUERYING_RULES", "COMPOSING_REPLY");
    private final AgentReplyStreamService service;
    private final byte[] agentToken;

    AgentReplyStreamController(
            AgentReplyStreamService service,
            @Value("${baseline.identity.agent-token}") String agentToken) {
        this.service = service;
        this.agentToken = agentToken.getBytes(StandardCharsets.UTF_8);
    }

    @PostMapping("/public-reply-events")
    ResponseEntity<Response> append(
            @PathVariable UUID ticketId,
            @PathVariable UUID generationId,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization,
            @RequestHeader(value = "X-Agent-Generation-Id", required = false)
                    UUID scopedGenerationId,
            @RequestHeader(value = "X-Agent-Operation", required = false) String operation,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody JsonNode payload) {
        requireScope(generationId, scopedGenerationId, operation, authorization);
        if (requestId == null || requestId.isBlank() || requestId.length() > 200) {
            throw badRequest("missing stable stream request identity");
        }
        AgentReplyStreamCommand command = parse(ticketId, generationId, requestId.trim(), payload);
        AgentReplyStreamResult result = service.append(command);
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.ACCEPTED)
                .body(new Response(true, result.replayed()));
    }

    private static AgentReplyStreamCommand parse(
            UUID ticketId, UUID generationId, String requestId, JsonNode payload) {
        if (payload == null || !payload.isObject() || !payload.has("type")) {
            throw badRequest("invalid public reply event");
        }
        AgentReplyStreamEventType type;
        try {
            type = AgentReplyStreamEventType.valueOf(requiredText(payload, "type"));
        } catch (IllegalArgumentException exception) {
            throw badRequest("invalid public reply event type");
        }
        Set<String> expected =
                switch (type) {
                    case CONTENT_DELTA -> Set.of("type", "chunkIndex", "delta");
                    case PROGRESS -> Set.of("type", "stage");
                    default -> Set.of("type");
                };
        if (!properties(payload).equals(expected)) {
            throw badRequest("public reply event fields are not allowed");
        }
        Integer chunkIndex = null;
        String delta = null;
        String stage = null;
        if (type == AgentReplyStreamEventType.CONTENT_DELTA) {
            JsonNode index = payload.get("chunkIndex");
            if (index == null || !index.isInt() || index.asInt() < 0) {
                throw badRequest("invalid content chunk index");
            }
            chunkIndex = index.asInt();
            delta = requiredText(payload, "delta");
            if (delta.length() > 512) throw badRequest("content delta is too large");
        } else if (type == AgentReplyStreamEventType.PROGRESS) {
            stage = requiredText(payload, "stage");
            if (!PROGRESS_STAGES.contains(stage)) throw badRequest("unknown public progress stage");
        }
        return new AgentReplyStreamCommand(
                ticketId, generationId, requestId, type, chunkIndex, delta, stage);
    }

    private void requireScope(
            UUID generationId, UUID scopedGenerationId, String operation, String authorization) {
        byte[] actual =
                authorization != null && authorization.startsWith("Bearer ")
                        ? authorization.substring(7).getBytes(StandardCharsets.UTF_8)
                        : new byte[0];
        if (!MessageDigest.isEqual(actual, agentToken)
                || !generationId.equals(scopedGenerationId)
                || !"PUBLISH_PUBLIC_REPLY_EVENT".equals(operation)) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "agent stream is outside the current scope");
        }
    }

    private static String requiredText(JsonNode payload, String name) {
        JsonNode value = payload.get(name);
        if (value == null || !value.isString() || value.asText().isBlank()) {
            throw badRequest("invalid public reply event field");
        }
        return value.asText();
    }

    private static Set<String> properties(JsonNode payload) {
        Set<String> names = new HashSet<>();
        names.addAll(payload.propertyNames());
        return Set.copyOf(names);
    }

    private static ResponseStatusException badRequest(String reason) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, reason);
    }

    record Response(boolean accepted, boolean replayed) {}
}
