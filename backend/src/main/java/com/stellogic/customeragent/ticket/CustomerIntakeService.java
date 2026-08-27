package com.stellogic.customeragent.ticket;

interface CustomerIntakeService {
    CustomerIntakeSnapshot start(StartCustomerIntake command);

    CustomerIntakeSnapshot reply(ReplyCustomerIntake command);
}
