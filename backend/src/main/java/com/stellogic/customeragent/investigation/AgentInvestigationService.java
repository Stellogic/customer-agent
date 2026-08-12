package com.stellogic.customeragent.investigation;

import java.util.UUID;

interface AgentInvestigationService {
    InvestigationFacts facts(UUID ticketId, UUID generationId);

    ConclusionAcceptance submit(
            UUID ticketId, UUID generationId, String requestId, InvestigationConclusion conclusion);

    void auditRejected(UUID ticketId, String reason);
}
