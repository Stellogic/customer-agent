package com.stellogic.customeragent.ticket;

interface AgentReplyStreamService {
    AgentReplyStreamResult append(AgentReplyStreamCommand command);
}
