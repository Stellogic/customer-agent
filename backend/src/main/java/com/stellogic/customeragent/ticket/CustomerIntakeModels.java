package com.stellogic.customeragent.ticket;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

record StartCustomerIntake(String customerId, String requestId, String message) {}

record ReplyCustomerIntake(String customerId, UUID intakeId, String requestId, String message) {}

record ResolveDuplicateIntake(
        String customerId, UUID intakeId, String requestId, UUID existingTicketId, String action) {}

record RestoreCustomerIntake(
        String customerId, UUID intakeId, String requestId, long expectedVersion) {}

record CustomerIntakeSnapshot(
        UUID intakeId,
        String status,
        String candidateOrderReference,
        String candidateOrderSummary,
        List<ProposedIntakeIssue> issues,
        String assistantMessage,
        List<UUID> ticketIds,
        UUID sharedIntakeRecordId,
        List<DuplicateIntakeMatch> duplicateMatches,
        List<UUID> routedTicketIds,
        int remainingOrderCount,
        int completedOrderCount,
        boolean replayed) {}

record ProposedIntakeIssue(String kind, String summary) {}

record CustomerVisibleOrderSummary(String reference, String summary, String version) {}

record DuplicateIntakeMatch(
        UUID ticketId, String issueKind, String issueSummary, String lifecycleState) {}

record IntakeConversationMessage(String author, String body, Instant sentAt) {}

record RecoverableCustomerIntake(
        CustomerIntakeSnapshot intake,
        long version,
        String retentionState,
        Instant expiresAt,
        Instant archivedAt,
        boolean factsChanged,
        List<IntakeConversationMessage> messages) {}

record CustomerIntakeRecoveryIndex(
        List<RecoverableCustomerIntake> active, List<RecoverableCustomerIntake> archived) {}

record IntakeUnderstandingRequest(
        String customerMessage,
        List<CustomerVisibleOrderSummary> visibleOrders,
        String currentOrderReference,
        String currentIssueSummary,
        List<ProposedIntakeIssue> currentIssues,
        List<String> currentPendingIssueKinds,
        List<String> currentRemainingOrderReferences) {}

record IntakeUnderstanding(
        String intent,
        String status,
        String candidateOrderReference,
        List<ProposedIntakeIssue> issues,
        List<String> pendingIssueKinds,
        List<String> remainingOrderReferences,
        String assistantMessage) {}
