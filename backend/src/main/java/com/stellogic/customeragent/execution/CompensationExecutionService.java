package com.stellogic.customeragent.execution;

import java.util.List;

interface CompensationExecutionService {
    List<CompensationExecutionModels.Assignment> assignments(String executorId);

    CompensationExecutionModels.ClaimResult claim(CompensationExecutionModels.ClaimCommand command);

    CompensationExecutionModels.SuccessResult succeed(
            CompensationExecutionModels.SuccessCommand command);

    CompensationExecutionModels.TransitionResult markUnknown(
            CompensationExecutionModels.UnknownCommand command);

    CompensationExecutionModels.TransitionResult markFailed(
            CompensationExecutionModels.FailureCommand command);

    CompensationExecutionModels.TransitionResult reconcile(
            CompensationExecutionModels.ReconciliationCommand command);
}
