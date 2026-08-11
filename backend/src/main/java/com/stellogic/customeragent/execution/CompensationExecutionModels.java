package com.stellogic.customeragent.execution;

import java.math.BigDecimal;
import java.util.UUID;

final class CompensationExecutionModels {
    private CompensationExecutionModels() {}

    record Assignment(
            UUID executionId,
            CompensationMethod compensationMethod,
            BigDecimal amount,
            ExecutionStatus status,
            String idempotencyKey) {}

    record ClaimCommand(String executorId, UUID executionId, String requestId) {}

    record ClaimResult(
            UUID executionId,
            UUID attemptId,
            ExecutionStatus status,
            String idempotencyKey,
            String parameterDigest,
            CompensationMethod compensationMethod,
            BigDecimal amount,
            boolean replayed) {}

    record BoundAttempt(UUID attemptId, String idempotencyKey, String parameterDigest) {}

    record SuccessCommand(
            String executorId,
            UUID executionId,
            String requestId,
            BoundAttempt attempt) {
        UUID attemptId() { return attempt.attemptId(); }
        String idempotencyKey() { return attempt.idempotencyKey(); }
        String parameterDigest() { return attempt.parameterDigest(); }
    }

    record SuccessResult(
            UUID executionId,
            UUID attemptId,
            ExecutionStatus status,
            CompensationMethod compensationMethod,
            BigDecimal amount,
            String customerMessage,
            boolean replayed) {}

    record UnknownCommand(
            String executorId,
            UUID executionId,
            String requestId,
            BoundAttempt attempt) {
        UUID attemptId() { return attempt.attemptId(); }
        String idempotencyKey() { return attempt.idempotencyKey(); }
        String parameterDigest() { return attempt.parameterDigest(); }
    }

    record FailureCommand(
            String executorId,
            UUID executionId,
            String requestId,
            BoundAttempt attempt) {
        UUID attemptId() { return attempt.attemptId(); }
        String idempotencyKey() { return attempt.idempotencyKey(); }
        String parameterDigest() { return attempt.parameterDigest(); }
    }

    record ReconciliationCommand(
            String executorId,
            UUID executionId,
            String requestId,
            String queryId,
            ReconciliationOutcome outcome,
            String resultReference) {}

    record TransitionResult(
            UUID executionId,
            UUID attemptId,
            ExecutionStatus status,
            String customerMessage,
            boolean replayed) {}

    enum ExecutionStatus { READY, PROCESSING, UNKNOWN, SUCCEEDED, FAILED }

    enum ReconciliationOutcome { FOUND, NOT_FOUND, UNKNOWN }

    enum CompensationMethod { COUPON, SIMULATED_PARTIAL_REFUND }
}
