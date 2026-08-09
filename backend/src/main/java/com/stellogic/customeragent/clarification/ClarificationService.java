package com.stellogic.customeragent.clarification;

import java.util.UUID;

interface ClarificationService {
    ClarificationRequestResult create(CreateClarification command);

    ClarificationReplyResult reply(ReplyToClarification command);

    ClarificationReplyResult status(String customerId, UUID ticketId, UUID resumeRequestId);

    void auditRejected(UUID ticketId, String reason);
}
