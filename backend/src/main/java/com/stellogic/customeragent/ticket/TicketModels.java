package com.stellogic.customeragent.ticket;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

record CreateCustomerTicket(
        String customerId,
        String requestId,
        String orderReference,
        String description,
        String issueKind) {}

record TicketCreationResult(UUID ticketId, boolean replayed) {}

record AppendCustomerMessage(String customerId, UUID ticketId, String messageId, String message) {}

record CustomerMessageResult(UUID ticketId, String outcome, boolean replayed) {}

record PublicMessage(String author, String body, Instant sentAt) {}

record CurrentClarification(UUID id, String promptCode, String question) {}

record CurrentAutoResolution(String status, Instant dueAt) {}

record CustomerPublicSnapshot(
        UUID ticketId,
        String lifecycleState,
        String handlingMode,
        Instant createdAt,
        Instant firstRespondedAt,
        String epoch,
        long sequence,
        long agentGeneration,
        List<PublicMessage> messages,
        CurrentClarification clarification,
        CurrentReplyStream replyStream,
        CurrentAutoResolution autoResolution,
        PendingCompensationProjection pendingCompensation) {
    CustomerPublicSnapshot(
            UUID ticketId,
            String lifecycleState,
            String handlingMode,
            Instant createdAt,
            Instant firstRespondedAt,
            String epoch,
            long sequence,
            long agentGeneration,
            List<PublicMessage> messages,
            CurrentClarification clarification,
            CurrentReplyStream replyStream) {
        this(
                ticketId,
                lifecycleState,
                handlingMode,
                createdAt,
                firstRespondedAt,
                epoch,
                sequence,
                agentGeneration,
                messages,
                clarification,
                replyStream,
                null,
                null);
    }

    CustomerPublicSnapshot(
            UUID ticketId,
            String lifecycleState,
            String handlingMode,
            Instant createdAt,
            Instant firstRespondedAt,
            String epoch,
            long sequence,
            long agentGeneration,
            List<PublicMessage> messages,
            CurrentClarification clarification,
            CurrentReplyStream replyStream,
            CurrentAutoResolution autoResolution) {
        this(
                ticketId,
                lifecycleState,
                handlingMode,
                createdAt,
                firstRespondedAt,
                epoch,
                sequence,
                agentGeneration,
                messages,
                clarification,
                replyStream,
                autoResolution,
                null);
    }
}

record PendingCompensationProjection(
        String compensationMethod, String amount, String currency, String status) {}

record CustomerPublicEvent(
        String epoch, long sequence, long agentGeneration, String type, String jsonPayload) {
    String cursor() {
        return epoch + ":" + sequence;
    }

    String publicData() {
        return "{\"view\":\"CUSTOMER_PUBLIC\",\"schema\":\""
                + epoch
                + "\",\"generation\":"
                + agentGeneration
                + ",\"payload\":"
                + jsonPayload
                + "}";
    }
}
