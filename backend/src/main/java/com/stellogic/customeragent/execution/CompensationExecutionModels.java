package com.stellogic.customeragent.execution;

import java.math.BigDecimal;
import java.util.UUID;

final class CompensationExecutionModels {
    private CompensationExecutionModels() {}

    record Assignment(UUID executionId, String compensationMethod, BigDecimal amount, String status) {}

    record ClaimCommand(String executorId, UUID executionId, String requestId) {}

    record ClaimResult(
            UUID executionId,
            UUID attemptId,
            String status,
            String idempotencyKey,
            String parameterDigest,
            String compensationMethod,
            BigDecimal amount,
            boolean replayed) {}

    record SuccessCommand(
            String executorId,
            UUID executionId,
            UUID attemptId,
            String requestId,
            String idempotencyKey,
            String parameterDigest) {}

    record SuccessResult(
            UUID executionId,
            UUID attemptId,
            String status,
            String compensationMethod,
            BigDecimal amount,
            String customerMessage,
            boolean replayed) {}
}
