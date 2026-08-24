package com.stellogic.customeragent.investigation;

import java.util.List;
import java.util.UUID;

record InvestigationFacts(
        String matchStatus,
        String orderReference,
        Integer delayHours,
        Long delaySeconds,
        Boolean paid,
        Boolean cancelled,
        Boolean fullyRefunded,
        Boolean existingCompensation,
        Integer pendingActionCount,
        String policyVersion,
        List<String> evidenceRefs) {}

record InvestigationConclusion(
        boolean compensationRequired,
        DecisionReasonCode reasonCode,
        int delayHours,
        long delaySeconds,
        String orderReference,
        List<String> evidenceRefs) {}

record ConclusionAcceptance(
        boolean accepted,
        TicketLifecycleState lifecycleState,
        UUID proposalRevisionId,
        Integer proposalRevision,
        ProposalRevisionStatus proposalStatus) {}

enum DecisionReasonCode {
    DELAY_UNDER_24_HOURS,
    LOGISTICS_DELAY
}

enum TicketLifecycleState {
    INVESTIGATING,
    RESOLVED
}

enum ProposalRevisionStatus {
    PENDING_APPROVAL
}
