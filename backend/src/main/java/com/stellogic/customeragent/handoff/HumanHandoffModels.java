package com.stellogic.customeragent.handoff;

import java.util.UUID;
import java.util.List;

record RequestHumanHandoff(String customerId, UUID ticketId, String requestId, String reasonCode) {}

record HumanHandoffResult(String requestId, String handlingMode, boolean replayed) {}

record AgentHumanHandoffFact(String type, String value, String evidenceReference) {}

record AgentHumanHandoffSummary(String conclusionCode, List<AgentHumanHandoffFact> facts) {}

enum AgentHumanHandoffReason {
    TOOL_RETRY_EXHAUSTED,
    FACT_CONFLICT,
    INVALID_TOOL_RESPONSE,
    REQUIRED_FACT_MISSING,
    UNSUPPORTED_SCENARIO
}

record RequestAgentHumanHandoff(
        UUID ticketId,
        UUID generationId,
        String requestId,
        AgentHumanHandoffReason reasonCode,
        AgentHumanHandoffSummary summary) {}

record AgentHumanHandoffResult(String requestId, String handlingMode, String reasonCode, boolean replayed) {}
