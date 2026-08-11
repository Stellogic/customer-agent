package com.stellogic.customeragent.execution;

import java.util.UUID;

interface CompensationSimulatorService {
    CompensationSimulatorModels.ExecuteResult execute(CompensationSimulatorModels.ExecuteCommand command);

    CompensationSimulatorModels.ReconciliationResult reconcile(UUID executionId, String idempotencyKey);
}
