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
        String issueKind,
        String issueSummary,
        String assistantMessage,
        UUID ticketId,
        boolean replayed) {}

record CustomerVisibleOrderSummary(String reference, String summary, String version) {}

record IntakeUnderstandingRequest(
        String customerMessage,
        List<CustomerVisibleOrderSummary> visibleOrders,
        String currentOrderReference,
        String currentIssueSummary) {}

record IntakeUnderstanding(
        String intent,
        String status,
        String candidateOrderReference,
        String issueKind,
        String issueSummary,
        String assistantMessage) {}
