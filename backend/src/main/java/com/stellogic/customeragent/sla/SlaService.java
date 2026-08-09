package com.stellogic.customeragent.sla;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class SlaService {
    private final JdbcTemplate jdbc;
    private final Clock clock;

    SlaService(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    List<UUID> ticketIds() {
        return jdbc.query("select id from support_ticket", (rs, row) -> rs.getObject(1, UUID.class));
    }

    Instant now() {
        return clock.instant();
    }

    @Transactional
    public void evaluateTicket(UUID ticketId, Instant evaluatedAt) {
        List<TicketSlaSnapshot> snapshots = jdbc.query(
                "select created_at, first_responded_at, resolution_elapsed_seconds, "
                        + "resolution_running_since, lifecycle_state from support_ticket where id = ? for update",
                (rs, row) -> new TicketSlaSnapshot(
                        rs.getTimestamp(1).toInstant(),
                        rs.getTimestamp(2) == null ? null : rs.getTimestamp(2).toInstant(),
                        rs.getLong(3),
                        rs.getTimestamp(4) == null ? null : rs.getTimestamp(4).toInstant(),
                        rs.getString(5)),
                ticketId);
        if (snapshots.isEmpty()) return;

        Timestamp occurredAt = Timestamp.from(evaluatedAt);
        for (SlaFact fact : SlaEvaluation.dueFacts(snapshots.getFirst(), evaluatedAt)) {
            int inserted = jdbc.update(
                    "insert into ticket_sla_fact (ticket_id, objective, fact_type, elapsed_seconds, occurred_at) "
                            + "values (?, ?, ?, ?, ?) on conflict do nothing",
                    ticketId, fact.objective().name(), fact.type().name(), fact.elapsedSeconds(), occurredAt);
            if (inserted == 0) continue;

            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, ?, 'spring-system', ?)",
                    ticketId, "SLA_" + fact.objective().name() + "_" + fact.type().name(), occurredAt);
            if (fact.type() == SlaFactType.WARNING) {
                jdbc.update(
                        "insert into support_sla_notification "
                                + "(ticket_id, objective, fact_type, support_id, notified_at) "
                                + "select ?, ?, 'WARNING', support_id, ? from support_assignment "
                                + "where ticket_id = ? and status = 'ACTIVE' on conflict do nothing",
                        ticketId, fact.objective().name(), occurredAt, ticketId);
            } else {
                jdbc.update(
                        "insert into shared_support_queue_entry (ticket_id, reason_code, entered_at) "
                                + "values (?, 'SLA_BREACH', ?) on conflict do nothing",
                        ticketId, occurredAt);
            }
        }
    }
}
