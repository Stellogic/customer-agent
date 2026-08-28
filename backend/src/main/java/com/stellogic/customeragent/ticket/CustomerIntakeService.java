package com.stellogic.customeragent.ticket;

import java.util.UUID;

interface CustomerIntakeService {
    CustomerIntakeSnapshot start(StartCustomerIntake command);

    CustomerIntakeSnapshot reply(ReplyCustomerIntake command);

    CustomerIntakeSnapshot resolveDuplicate(ResolveDuplicateIntake command);

    CustomerIntakeSnapshot snapshot(String customerId, java.util.UUID intakeId);

    CustomerIntakeRecoveryIndex recoveryIndex(String customerId);

    RecoverableCustomerIntake recoverableSnapshot(String customerId, UUID intakeId);

    RecoverableCustomerIntake restore(RestoreCustomerIntake command);
}
