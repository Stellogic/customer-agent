package com.stellogic.customeragent.closure;

import java.util.UUID;

record CustomerReplyCommand(
        String customerId, UUID originalTicketId, String messageId,
        String orderReference, String issueKind, String message) {}

record CustomerReplyResult(UUID ticketId, String outcome, boolean replayed) {}
