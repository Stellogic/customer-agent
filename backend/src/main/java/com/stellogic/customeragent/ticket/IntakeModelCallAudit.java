package com.stellogic.customeragent.ticket;

import java.sql.Timestamp;
import java.time.Clock;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

@Component
class IntakeModelCallAudit {
    private static final List<String> EVIDENCE_FIELDS =
            List.of(
                    "schemaVersion",
                    "logicalCalls",
                    "providerAttempts",
                    "inputTokens",
                    "outputTokens",
                    "tokens",
                    "costMicros",
                    "currency",
                    "usageComplete",
                    "failureClassification");
    private static final List<String> ATTEMPT_FIELDS =
            List.of(
                    "internalCallId",
                    "attemptId",
                    "attemptNumber",
                    "provider",
                    "providerResponseId",
                    "responseStatus",
                    "requestModel",
                    "responseModel",
                    "backendFingerprint",
                    "promptVersion",
                    "schemaVersion",
                    "durationMs",
                    "inputTokens",
                    "outputTokens",
                    "totalTokens",
                    "cachedTokens",
                    "cacheHit",
                    "failureClassification",
                    "providerHttpStatus",
                    "strictSchemaRequested",
                    "thinkingDisabled",
                    "allowedParametersOnly",
                    "actualResponseShapeValid",
                    "usageReported",
                    "cacheMetricsReported",
                    "reasoningTokens");
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final ObjectMapper json;

    IntakeModelCallAudit(JdbcTemplate jdbc, Clock clock, ObjectMapper json) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.json = json;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public UUID begin(
            String customerId, UUID intakeId, String operation, String requestKey, String phase) {
        UUID invocationId = UUID.randomUUID();
        jdbc.update(
                "insert into intake_model_call (invocation_id, customer_id, intake_id, operation, request_key, phase, started_at, status) values (?, ?, ?, ?, ?, ?, ?, 'PENDING')",
                invocationId,
                customerId,
                intakeId,
                operation,
                requestKey,
                phase,
                Timestamp.from(clock.instant()));
        return invocationId;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void complete(
            UUID invocationId, JsonNode evidence, IntakeAgentUnavailableException.Reason reason) {
        jdbc.update(
                "update intake_model_call set completed_at = ?, status = ?, spring_failure_reason = ?, evidence = ?::jsonb where invocation_id = ?",
                Timestamp.from(clock.instant()),
                reason == null ? "SUCCEEDED" : "FAILED",
                reason == null ? null : reason.name(),
                evidence == null ? null : controlledEvidence(evidence).toString(),
                invocationId);
    }

    private ObjectNode controlledEvidence(JsonNode evidence) {
        ObjectNode result = copyFields(evidence, EVIDENCE_FIELDS);
        JsonNode attempts = evidence.path("attempts");
        if (attempts.isArray()) {
            var records = result.putArray("attempts");
            for (JsonNode attempt : attempts) records.add(copyFields(attempt, ATTEMPT_FIELDS));
        }
        return result;
    }

    private ObjectNode copyFields(JsonNode source, List<String> fields) {
        ObjectNode result = json.createObjectNode();
        for (String field : fields) {
            JsonNode value = source.get(field);
            if (value != null && value.isValueNode()) result.set(field, value);
        }
        return result;
    }
}
