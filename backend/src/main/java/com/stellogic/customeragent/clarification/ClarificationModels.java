package com.stellogic.customeragent.clarification;

import java.util.UUID;

record CreateClarification(UUID ticketId, UUID generationId, String requestId, String reasonCode) {}

record ClarificationRequestResult(
        UUID clarificationRequestId, String promptCode, String question) {}

record ReplyToClarification(
        String customerId,
        UUID ticketId,
        UUID clarificationRequestId,
        String customerMessageId,
        UUID resumeRequestId,
        String answer) {}

record ClarificationReplyResult(UUID resumeRequestId, AgentResumeStatus status, boolean replayed) {}

enum AgentResumeStatus {
    PENDING,
    SUBMITTING,
    SUBMITTED,
    RETRY,
    COMPLETED
}
