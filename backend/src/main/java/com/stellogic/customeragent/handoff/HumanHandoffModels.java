package com.stellogic.customeragent.handoff;

import java.util.UUID;

record RequestHumanHandoff(String customerId, UUID ticketId, String requestId, String reasonCode) {}

record HumanHandoffResult(String requestId, String handlingMode, boolean replayed) {}
