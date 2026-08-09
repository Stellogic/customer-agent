package com.stellogic.customeragent.handoff;

import java.util.UUID;

interface HumanHandoffService {
    HumanHandoffResult request(RequestHumanHandoff command);

    HumanHandoffResult status(String customerId, UUID ticketId, String requestId);
}
