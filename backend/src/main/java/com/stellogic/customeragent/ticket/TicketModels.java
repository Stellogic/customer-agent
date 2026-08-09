package com.stellogic.customeragent.ticket;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

record CreateCustomerTicket(String customerId, String requestId, String orderReference, String description) {}

record TicketCreationResult(UUID ticketId, boolean replayed) {}

record PublicMessage(String author, String body, Instant sentAt) {}

record CustomerPublicSnapshot(
        UUID ticketId,
        String lifecycleState,
        String handlingMode,
        Instant createdAt,
        Instant firstRespondedAt,
        String epoch,
        long sequence,
        List<PublicMessage> messages) {}

record CustomerPublicEvent(String epoch, long sequence, String type, String jsonPayload) {
    String cursor() {
        return epoch + ":" + sequence;
    }
}
