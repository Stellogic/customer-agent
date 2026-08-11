package com.stellogic.customeragent.ticket;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public final class TicketResolutionTransition {
    private static final String RESOLUTION_UPDATE =
            "update support_ticket set lifecycle_state = 'RESOLVED', "
                    + "resolution_elapsed_seconds = resolution_elapsed_seconds + "
                    + "case when resolution_running_since is null then 0 else greatest(0, "
                    + "extract(epoch from (?::timestamptz - resolution_running_since))::bigint) end, "
                    + "resolution_running_since = null, resolved_at = ?, "
                    + "close_due_at = ?::timestamptz + interval '72 hours' where id = ? and ";
    private final JdbcTemplate jdbc;

    public TicketResolutionTransition(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public int fromAgentInvestigation(UUID ticketId, Instant resolvedAt) {
        return update(ticketId, resolvedAt, "lifecycle_state = 'INVESTIGATING' and handling_mode = 'AGENT'");
    }

    public int afterCompensationExecution(UUID ticketId, Instant resolvedAt) {
        return update(ticketId, resolvedAt, "lifecycle_state <> 'CLOSED'");
    }

    private int update(UUID ticketId, Instant resolvedAt, String authorityPredicate) {
        Timestamp at = Timestamp.from(resolvedAt);
        return jdbc.update(RESOLUTION_UPDATE + authorityPredicate, at, at, at, ticketId);
    }
}
