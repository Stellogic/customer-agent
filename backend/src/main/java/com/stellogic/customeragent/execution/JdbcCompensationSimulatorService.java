package com.stellogic.customeragent.execution;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Clock;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
class JdbcCompensationSimulatorService implements CompensationSimulatorService {
    private final JdbcTemplate jdbc;
    private final Clock clock;

    JdbcCompensationSimulatorService(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    @Override
    @Transactional
    public CompensationSimulatorModels.ExecuteResult execute(CompensationSimulatorModels.ExecuteCommand command) {
        List<ProviderOperation> existing = providerOperation(command.executionId(), true);
        if (!existing.isEmpty()) {
            ProviderOperation operation = existing.getFirst();
            if (!operation.matches(command)) conflict("simulator identity conflict");
            return operation.executeResult();
        }

        ApprovedExecution execution = approvedExecution(command.executionId());
        if (!execution.idempotencyKey().equals(command.idempotencyKey())
                || !execution.parameterDigest().equals(command.parameterDigest())
                || execution.amount().compareTo(command.amount()) != 0
                || execution.method() != CompensationExecutionModels.CompensationMethod.SIMULATED_PARTIAL_REFUND) {
            conflict("simulator parameters do not match approved execution");
        }
        EffectStatus effect = switch (command.scenario()) {
            case SUCCESS, AFTER_EFFECT_RESPONSE_LOST -> EffectStatus.SUCCEEDED;
            case BEFORE_EFFECT_FAILURE, RECONCILIATION_NOT_FOUND -> EffectStatus.NOT_OCCURRED;
            case RECONCILIATION_UNKNOWN -> EffectStatus.UNCERTAIN;
        };
        String reference = effect == EffectStatus.SUCCEEDED
                ? "simulated-refund:" + command.executionId() : null;
        jdbc.update(
                "insert into simulated_compensation_provider_operation "
                        + "(execution_id, idempotency_key, parameter_digest, amount, scenario, effect_status, "
                        + "result_reference, query_count, created_at) values (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                command.executionId(), command.idempotencyKey(), command.parameterDigest(), command.amount(),
                command.scenario().name(), effect.name(), reference, Timestamp.from(clock.instant()));
        return new ProviderOperation(
                command.executionId(), command.idempotencyKey(), command.parameterDigest(), command.amount(),
                command.scenario(), effect, reference, 0).executeResult();
    }

    @Override
    @Transactional
    public CompensationSimulatorModels.ReconciliationResult reconcile(UUID executionId) {
        List<ProviderOperation> operations = providerOperation(executionId, true);
        if (operations.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "provider execution identity not found");
        }
        ProviderOperation operation = operations.getFirst();
        int queryNumber = operation.queryCount() + 1;
        jdbc.update(
                "update simulated_compensation_provider_operation set query_count = ? where execution_id = ?",
                queryNumber, executionId);
        CompensationExecutionModels.ReconciliationOutcome outcome = switch (operation.effectStatus()) {
            case SUCCEEDED -> CompensationExecutionModels.ReconciliationOutcome.FOUND;
            case NOT_OCCURRED -> CompensationExecutionModels.ReconciliationOutcome.NOT_FOUND;
            case UNCERTAIN -> CompensationExecutionModels.ReconciliationOutcome.UNKNOWN;
        };
        String queryId = "provider-query:" + executionId + ":" + queryNumber;
        jdbc.update(
                "insert into simulated_compensation_provider_query "
                        + "(query_id, execution_id, outcome, result_reference, queried_at) values (?, ?, ?, ?, ?)",
                queryId, executionId, outcome.name(), operation.resultReference(), Timestamp.from(clock.instant()));
        return new CompensationSimulatorModels.ReconciliationResult(
                queryId, outcome, operation.resultReference());
    }

    private ApprovedExecution approvedExecution(UUID executionId) {
        List<ApprovedExecution> executions = jdbc.query(
                "select idempotency_key, parameter_digest, compensation_method, amount "
                        + "from compensation_execution where id = ? and assigned_executor_id = 'compensation-executor' "
                        + "and status = 'PROCESSING' for update",
                (rs, row) -> new ApprovedExecution(
                        rs.getString(1), rs.getString(2),
                        CompensationExecutionModels.CompensationMethod.valueOf(rs.getString(3)),
                        rs.getBigDecimal(4)),
                executionId);
        if (executions.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "processable execution not found");
        }
        return executions.getFirst();
    }

    private List<ProviderOperation> providerOperation(UUID executionId, boolean lock) {
        return jdbc.query(
                "select execution_id, idempotency_key, parameter_digest, amount, scenario, effect_status, "
                        + "result_reference, query_count from simulated_compensation_provider_operation "
                        + "where execution_id = ?" + (lock ? " for update" : ""),
                (rs, row) -> new ProviderOperation(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3), rs.getBigDecimal(4),
                        CompensationSimulatorModels.Scenario.valueOf(rs.getString(5)),
                        EffectStatus.valueOf(rs.getString(6)), rs.getString(7), rs.getInt(8)),
                executionId);
    }

    private static void conflict(String message) {
        throw new ResponseStatusException(HttpStatus.CONFLICT, message);
    }

    private enum EffectStatus { SUCCEEDED, NOT_OCCURRED, UNCERTAIN }

    private record ApprovedExecution(
            String idempotencyKey,
            String parameterDigest,
            CompensationExecutionModels.CompensationMethod method,
            BigDecimal amount) {}

    private record ProviderOperation(
            UUID executionId,
            String idempotencyKey,
            String parameterDigest,
            BigDecimal amount,
            CompensationSimulatorModels.Scenario scenario,
            EffectStatus effectStatus,
            String resultReference,
            int queryCount) {
        boolean matches(CompensationSimulatorModels.ExecuteCommand command) {
            return executionId.equals(command.executionId())
                    && idempotencyKey.equals(command.idempotencyKey())
                    && parameterDigest.equals(command.parameterDigest())
                    && amount.compareTo(command.amount()) == 0
                    && scenario == command.scenario();
        }

        CompensationSimulatorModels.ExecuteResult executeResult() {
            CompensationSimulatorModels.ProviderOutcome outcome = switch (effectStatus) {
                case SUCCEEDED -> CompensationSimulatorModels.ProviderOutcome.SUCCEEDED;
                case NOT_OCCURRED -> CompensationSimulatorModels.ProviderOutcome.CONFIRMED_NOT_OCCURRED;
                case UNCERTAIN -> CompensationSimulatorModels.ProviderOutcome.UNKNOWN;
            };
            boolean responseLost = scenario == CompensationSimulatorModels.Scenario.AFTER_EFFECT_RESPONSE_LOST
                    || scenario == CompensationSimulatorModels.Scenario.RECONCILIATION_NOT_FOUND
                    || scenario == CompensationSimulatorModels.Scenario.RECONCILIATION_UNKNOWN;
            return new CompensationSimulatorModels.ExecuteResult(outcome, resultReference, responseLost);
        }
    }
}
