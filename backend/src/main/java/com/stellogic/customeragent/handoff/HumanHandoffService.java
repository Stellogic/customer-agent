package com.stellogic.customeragent.handoff;

import java.util.UUID;

public interface HumanHandoffService {
    HumanHandoffResult request(RequestHumanHandoff command);

    HumanHandoffResult status(String customerId, UUID ticketId, String requestId);

    AgentHumanHandoffResult requestAgentHumanHandoff(RequestAgentHumanHandoff command);

    void auditAgentRejected(UUID ticketId, String reason);

    void rejectProposal(UUID ticketId, String approverId);
}
