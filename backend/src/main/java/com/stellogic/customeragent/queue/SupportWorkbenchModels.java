package com.stellogic.customeragent.queue;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

record SupportQueueItem(UUID ticketId, String lifecycleState, String handlingMode, Instant enteredAt) {}

record SupportWorkbenchSnapshot(
        String epoch,
        long sequence,
        List<SupportQueueItem> sharedQueue,
        List<SupportQueueItem> escalationQueue) {}

record SupportWorkbenchEvent(String epoch, long sequence, String type, String jsonPayload) {
    String cursor() {
        return epoch + ":" + sequence;
    }

    String publicData() {
        return "{\"view\":\"SUPPORT_WORKBENCH\",\"schema\":\"" + epoch + "\",\"payload\":"
                + jsonPayload + "}";
    }
}

record SupportTicketDetails(
        UUID ticketId,
        String customerId,
        String orderReference,
        String description,
        String lifecycleState,
        String handlingMode,
        List<SupportConversationMessage> publicConversation,
        List<SupportInvestigationFact> investigationFacts,
        List<SupportTimelineEvent> businessTimeline) {}

record SupportConversationMessage(String author, String body, Instant sentAt) {}

record SupportInvestigationFact(String factType, String factValue, String evidenceReference, Instant recordedAt) {}

record SupportTimelineEvent(String eventType, String actorId, Instant occurredAt) {}

final class SupportWorkbenchCursorException extends RuntimeException {}

final class SupportTicketNotFoundException extends RuntimeException {}

final class SupportIdentityRequiredException extends RuntimeException {}
