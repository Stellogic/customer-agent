package com.stellogic.customeragent.execution;

import java.math.BigDecimal;
import java.util.UUID;
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
@RequestMapping("/internal/compensation-simulator")
final class CompensationSimulatorController {
    private final CompensationSimulatorService service;
    private final ExecutorMachineIdentity executorIdentity;

    CompensationSimulatorController(
            CompensationSimulatorService service,
            ExecutorMachineIdentity executorIdentity) {
        this.service = service;
        this.executorIdentity = executorIdentity;
    }

    @PostMapping("/{executionId}/executions")
    CompensationSimulatorModels.ExecuteResult execute(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @RequestHeader(value = "X-Simulation-Scenario", required = false) String scenario,
            @PathVariable UUID executionId,
            @RequestBody(required = false) ExecuteRequest body) {
        executorIdentity.require(authorization);
        if (idempotencyKey == null || idempotencyKey.isBlank() || body == null
                || body.parameterDigest() == null || !body.parameterDigest().matches("[0-9a-f]{64}")
                || body.amount() == null || body.amount().signum() <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "bound simulator execution required");
        }
        CompensationSimulatorModels.Scenario injection;
        try {
            injection = scenario == null || scenario.isBlank()
                    ? CompensationSimulatorModels.Scenario.AFTER_EFFECT_RESPONSE_LOST
                    : CompensationSimulatorModels.Scenario.valueOf(scenario);
        } catch (IllegalArgumentException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "unsupported simulation scenario");
        }
        var result = service.execute(new CompensationSimulatorModels.ExecuteCommand(
                executionId, idempotencyKey.trim(), body.parameterDigest(), body.amount(), injection));
        if (result.responseLost()) {
            throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT, "simulated provider response lost");
        }
        return result;
    }

    @GetMapping("/{executionId}/reconciliation")
    CompensationSimulatorModels.ReconciliationResult reconcile(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @PathVariable UUID executionId) {
        executorIdentity.require(authorization);
        if (idempotencyKey == null || idempotencyKey.isBlank() || idempotencyKey.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "original execution identity required");
        }
        return service.reconcile(executionId, idempotencyKey.trim());
    }

    record ExecuteRequest(String parameterDigest, BigDecimal amount) {}
}
