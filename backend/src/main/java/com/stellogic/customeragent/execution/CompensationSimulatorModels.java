package com.stellogic.customeragent.execution;

import java.math.BigDecimal;
import java.util.UUID;

final class CompensationSimulatorModels {
    private CompensationSimulatorModels() {}

    record ExecuteCommand(
            UUID executionId,
            String idempotencyKey,
            String parameterDigest,
            BigDecimal amount,
            Scenario scenario) {}

    record ExecuteResult(ProviderOutcome outcome, String resultReference, boolean responseLost) {}

    record ReconciliationResult(
            String queryId,
            CompensationExecutionModels.ReconciliationOutcome outcome,
            String resultReference) {}

    enum ProviderOutcome { SUCCEEDED, CONFIRMED_NOT_OCCURRED, UNKNOWN }

    enum Scenario {
        SUCCESS,
        BEFORE_EFFECT_FAILURE,
        AFTER_EFFECT_RESPONSE_LOST,
        RECONCILIATION_NOT_FOUND,
        RECONCILIATION_UNKNOWN
    }
}
