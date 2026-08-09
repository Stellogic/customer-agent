package com.stellogic.customeragent.investigation;

import java.sql.Timestamp;
import java.time.Clock;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Component
class AgentAccessAudit {
    private final JdbcTemplate jdbc;
    private final Clock clock;

    AgentAccessAudit(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    void rejected(UUID ticketId, String reason) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "select id, ?, 'agent-machine', ? from support_ticket where id = ?",
                "AGENT_COMMAND_REJECTED_" + reason,
                Timestamp.from(clock.instant()),
                ticketId);
    }
}
