package com.stellogic.customeragent.ticket;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

record IntakeAssistanceQueueItem(
        UUID requestId,
        String status,
        String reasonCode,
        Instant requestedAt,
        Instant claimExpiresAt,
        boolean assignedToCurrentSupport) {}

record IntakeAssistanceSnapshot(
        String epoch, long sequence, List<IntakeAssistanceQueueItem> requests) {}

record IntakeAssistanceOrderCandidate(String reference, String summary) {}

record IntakeAssistanceDetails(
        UUID requestId,
        UUID intakeId,
        String status,
        String reasonCode,
        String originalMessage,
        List<IntakeAssistanceOrderCandidate> orderCandidates,
        String selectedOrderReference,
        List<ProposedIntakeIssue> issues,
        long intakeVersion,
        Instant claimExpiresAt) {}

record IntakeAssistanceClaim(
        UUID requestId, String status, Instant claimExpiresAt, boolean replayed) {}

record IntakeAssistanceMutation(
        UUID requestId,
        String status,
        long intakeVersion,
        Instant claimExpiresAt,
        boolean replayed) {}

record IntakeAssistanceProposalCommand(
        String supportId,
        UUID requestId,
        String requestKey,
        long expectedIntakeVersion,
        String orderReference,
        List<ProposedIntakeIssue> issues) {}

record IntakeAssistanceEvent(String epoch, long sequence, String type, String jsonPayload) {
    String cursor() {
        return epoch + ":" + sequence;
    }

    String publicData() {
        return "{\"view\":\"INTAKE_ASSISTANCE\",\"schema\":\""
                + epoch
                + "\",\"payload\":"
                + jsonPayload
                + "}";
    }
}

final class IntakeAssistanceNotFoundException extends RuntimeException {}

final class IntakeAssistanceConflictException extends RuntimeException {}

final class IntakeAssistanceCursorException extends RuntimeException {}
