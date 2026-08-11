package com.stellogic.customeragent.execution;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/compensation-executions")
public final class CompensationExecutionController {
    private static final String EXECUTOR_ID = "compensation-executor";
    private final CompensationExecutionService service;
    private final byte[] executorToken;

    CompensationExecutionController(
            CompensationExecutionService service,
            @Value("${baseline.identity.executor-token}") String executorToken) {
        this.service = service;
        this.executorToken = executorToken.getBytes(StandardCharsets.UTF_8);
    }

    @GetMapping
    List<CompensationExecutionModels.Assignment> assignments(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization) {
        requireExecutor(authorization);
        return service.assignments(EXECUTOR_ID);
    }

    @PostMapping("/{executionId}/claims")
    ResponseEntity<CompensationExecutionModels.ClaimResult> claim(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID executionId) {
        requireExecutor(authorization);
        if (requestId == null || requestId.isBlank() || requestId.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "stable delivery identity required");
        }
        var result = service.claim(new CompensationExecutionModels.ClaimCommand(
                EXECUTOR_ID, executionId, requestId.trim()));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED).body(result);
    }

    @PostMapping("/{executionId}/success")
    CompensationExecutionModels.SuccessResult succeed(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID executionId,
            @RequestBody(required = false) SuccessRequest body) {
        requireExecutor(authorization);
        if (requestId == null || requestId.isBlank() || requestId.length() > 200
                || body == null || body.attemptId() == null
                || body.idempotencyKey() == null || body.idempotencyKey().isBlank()
                || body.parameterDigest() == null || !body.parameterDigest().matches("[0-9a-f]{64}")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "bound execution result required");
        }
        return service.succeed(new CompensationExecutionModels.SuccessCommand(
                EXECUTOR_ID, executionId, body.attemptId(), requestId.trim(),
                body.idempotencyKey(), body.parameterDigest()));
    }

    @PostMapping("/{executionId}/unknown")
    CompensationExecutionModels.TransitionResult markUnknown(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID executionId,
            @RequestBody(required = false) UnknownRequest body) {
        requireExecutor(authorization);
        requireRequestId(requestId);
        if (body == null || body.attemptId() == null
                || body.idempotencyKey() == null || body.idempotencyKey().isBlank()
                || body.parameterDigest() == null || !body.parameterDigest().matches("[0-9a-f]{64}")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "bound unknown result required");
        }
        return service.markUnknown(new CompensationExecutionModels.UnknownCommand(
                EXECUTOR_ID, executionId, body.attemptId(), requestId.trim(),
                body.idempotencyKey(), body.parameterDigest()));
    }

    @PostMapping("/{executionId}/failures")
    CompensationExecutionModels.TransitionResult markFailed(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID executionId,
            @RequestBody(required = false) UnknownRequest body) {
        requireExecutor(authorization);
        requireRequestId(requestId);
        if (body == null || body.attemptId() == null
                || body.idempotencyKey() == null || body.idempotencyKey().isBlank()
                || body.parameterDigest() == null || !body.parameterDigest().matches("[0-9a-f]{64}")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "bound confirmed failure required");
        }
        return service.markFailed(new CompensationExecutionModels.FailureCommand(
                EXECUTOR_ID, executionId, body.attemptId(), requestId.trim(),
                body.idempotencyKey(), body.parameterDigest()));
    }

    @PostMapping("/{executionId}/reconciliations")
    CompensationExecutionModels.TransitionResult reconcile(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID executionId,
            @RequestBody(required = false) ReconciliationRequest body) {
        requireExecutor(authorization);
        requireRequestId(requestId);
        if (body == null || body.queryId() == null || body.queryId().isBlank() || body.outcome() == null
                || (body.outcome() == CompensationExecutionModels.ReconciliationOutcome.FOUND
                    && (body.resultReference() == null || body.resultReference().isBlank()))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "authoritative reconciliation required");
        }
        return service.reconcile(new CompensationExecutionModels.ReconciliationCommand(
                EXECUTOR_ID, executionId, requestId.trim(), body.queryId().trim(),
                body.outcome(), body.resultReference()));
    }

    private static void requireRequestId(String requestId) {
        if (requestId == null || requestId.isBlank() || requestId.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "stable delivery identity required");
        }
    }

    private void requireExecutor(String authorization) {
        byte[] actual = authorization != null && authorization.startsWith("Bearer ")
                ? authorization.substring(7).getBytes(StandardCharsets.UTF_8)
                : new byte[0];
        if (!MessageDigest.isEqual(actual, executorToken)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "executor identity required");
        }
    }

    record SuccessRequest(UUID attemptId, String idempotencyKey, String parameterDigest) {}

    record UnknownRequest(UUID attemptId, String idempotencyKey, String parameterDigest) {}

    record ReconciliationRequest(
            String queryId,
            CompensationExecutionModels.ReconciliationOutcome outcome,
            String resultReference) {}
}
