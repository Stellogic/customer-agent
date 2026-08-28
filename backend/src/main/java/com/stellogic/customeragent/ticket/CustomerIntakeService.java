package com.stellogic.customeragent.ticket;

interface CustomerIntakeService {
    CustomerIntakeSnapshot start(StartCustomerIntake command);

    CustomerIntakeSnapshot reply(ReplyCustomerIntake command);

    CustomerIntakeSnapshot resolveDuplicate(ResolveDuplicateIntake command);

    CustomerIntakeSnapshot snapshot(String customerId, java.util.UUID intakeId);
}
