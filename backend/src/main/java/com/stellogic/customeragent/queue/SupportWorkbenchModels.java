package com.stellogic.customeragent.queue;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

enum SupportTicketLifecycleState {
    NEW,
    INVESTIGATING,
    WAITING_FOR_CUSTOMER,
    WAITING_FOR_EXTERNAL,
    RESOLVED,
    CLOSED
}

enum SupportHandlingMode {
    AGENT,
    HUMAN
}

record SupportQueueItem(
        UUID ticketId,
        SupportTicketLifecycleState lifecycleState,
        SupportHandlingMode handlingMode,
        Instant enteredAt) {}

record SupportWorkbenchSnapshot(
        String epoch,
        long sequence,
        List<SupportQueueItem> sharedQueue,
        List<SupportQueueItem> escalationQueue) {}

record SupportAssignmentClaim(UUID ticketId, String supportId, boolean replayed) {}

record SupportWorkbenchEvent(String epoch, long sequence, String type, String jsonPayload) {
    String cursor() {
        return epoch + ":" + sequence;
    }

    String publicData() {
        return "{\"view\":\"SUPPORT_WORKBENCH\",\"schema\":\""
                + epoch
                + "\",\"payload\":"
                + jsonPayload
                + "}";
    }
}

record SupportTicketDetails(
        UUID ticketId,
        String customerId,
        String orderReference,
        String description,
        SupportTicketLifecycleState lifecycleState,
        SupportHandlingMode handlingMode,
        List<SupportConversationMessage> publicConversation,
        List<SupportInvestigationFact> investigationFacts,
        List<SupportTimelineEvent> businessTimeline) {}

record SupportConversationMessage(String author, String body, Instant sentAt) {}

record SupportInvestigationFact(
        String factType, String factValue, String evidenceReference, Instant recordedAt) {}

record SupportTimelineEvent(String eventType, String actorId, Instant occurredAt) {}

final class SupportWorkbenchCursorException extends RuntimeException {}

final class SupportTicketNotFoundException extends RuntimeException {}

final class SupportIdentityRequiredException extends RuntimeException {}
