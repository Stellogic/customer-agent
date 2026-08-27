package com.stellogic.customeragent.ticket;

import java.util.List;
import java.util.UUID;

record StartCustomerIntake(String customerId, String requestId, String message) {}

record ReplyCustomerIntake(String customerId, UUID intakeId, String requestId, String message) {}

record CustomerIntakeSnapshot(
        UUID intakeId,
        String status,
        String candidateOrderReference,
        String candidateOrderSummary,
        List<ProposedIntakeIssue> issues,
        String assistantMessage,
        List<UUID> ticketIds,
        UUID sharedIntakeRecordId,
        boolean replayed) {}

record ProposedIntakeIssue(String kind, String summary) {}

record CustomerVisibleOrderSummary(String reference, String summary, String version) {}

record IntakeUnderstandingRequest(
        String customerMessage,
        List<CustomerVisibleOrderSummary> visibleOrders,
        String currentOrderReference,
        String currentIssueSummary,
        List<ProposedIntakeIssue> currentIssues,
        List<String> currentPendingIssueKinds) {}

record IntakeUnderstanding(
        String intent,
        String status,
        String candidateOrderReference,
        List<ProposedIntakeIssue> issues,
        List<String> pendingIssueKinds,
        String assistantMessage) {}
