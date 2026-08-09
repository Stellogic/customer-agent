package com.stellogic.customeragent.handoff;

import java.util.UUID;
import java.util.List;

record RequestHumanHandoff(String customerId, UUID ticketId, String requestId, String reasonCode) {}

record HumanHandoffResult(String requestId, String handlingMode, boolean replayed) {}

record AgentSafetyHandoffFact(String type, String value, String evidenceReference) {}

record AgentSafetyHandoffSummary(String conclusionCode, List<AgentSafetyHandoffFact> facts) {}

enum AgentSafetyHandoffReason {
    TOOL_RETRY_EXHAUSTED,
    FACT_CONFLICT,
    INVALID_TOOL_RESPONSE,
    REQUIRED_FACT_MISSING,
    UNSUPPORTED_SCENARIO
}

record RequestAgentSafetyHandoff(
        UUID ticketId,
        UUID generationId,
        String requestId,
        AgentSafetyHandoffReason reasonCode,
        AgentSafetyHandoffSummary summary) {}

record AgentSafetyHandoffResult(String requestId, String handlingMode, String reasonCode, boolean replayed) {}
