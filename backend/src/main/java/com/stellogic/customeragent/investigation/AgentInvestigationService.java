package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import java.util.UUID;

interface AgentInvestigationService {
    InvestigationCapabilityCatalog capabilities(UUID ticketId, UUID generationId);

    CustomerCommunicationContext customerCommunicationContext(UUID ticketId, UUID generationId);

    AgentKnowledgeResult authorizeKnowledgeSearch(
            UUID ticketId, UUID generationId, String requestId, String query);

    AgentKnowledgeResult acceptKnowledgeSearch(
            UUID ticketId, UUID generationId, String requestId, String query, AgentKnowledgeResult result);

    SiblingTicketSummary siblingTicketSummary(UUID ticketId, UUID generationId);

    InvestigationCapabilityResult invoke(
            UUID ticketId,
            UUID generationId,
            String requestId,
            InvestigationCapability capability,
            InvestigationCapabilityParameters parameters);

    ConclusionAcceptance submit(
            UUID ticketId, UUID generationId, String requestId, InvestigationConclusion conclusion);

    void auditRejected(UUID ticketId, String reason);
}
