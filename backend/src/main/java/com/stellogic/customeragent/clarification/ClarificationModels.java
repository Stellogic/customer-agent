package com.stellogic.customeragent.clarification;

import java.util.List;
import java.util.UUID;

record CreateClarification(
        UUID ticketId,
        UUID generationId,
        String requestId,
        String reasonCode,
        CustomerClarificationReply customerReply) {}

record CustomerClarificationReply(
        String schemaVersion,
        String body,
        String intent,
        List<String> evidenceRefs,
        boolean escalationRequired,
        String referencedOrder) {}

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
