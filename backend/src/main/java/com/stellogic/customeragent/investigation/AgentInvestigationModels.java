package com.stellogic.customeragent.investigation;

import java.util.List;

record InvestigationFacts(
        String orderReference,
        int delayHours,
        boolean paid,
        boolean cancelled,
        boolean fullyRefunded,
        boolean existingCompensation,
        int pendingActionCount,
        String policyVersion,
        List<String> evidenceRefs) {}

record InvestigationConclusion(
        boolean compensationRequired,
        DecisionReasonCode reasonCode,
        int delayHours,
        String orderReference,
        List<String> evidenceRefs) {}

record ConclusionAcceptance(boolean accepted, TicketLifecycleState lifecycleState) {}

enum DecisionReasonCode {
    DELAY_UNDER_24_HOURS
}

enum TicketLifecycleState {
    RESOLVED
}
