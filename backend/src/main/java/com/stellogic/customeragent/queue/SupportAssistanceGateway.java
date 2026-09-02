package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import tools.jackson.databind.JsonNode;

interface SupportAssistanceGateway {
    JsonNode generate(
            SupportAssistanceKind kind,
            String query,
            SupportAssistanceContext.Snapshot context,
            AgentKnowledgeResult knowledge);
}
