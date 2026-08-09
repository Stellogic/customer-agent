package com.stellogic.customeragent.sla;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class SupportSlaProjectionService {
    private final JdbcTemplate jdbc;

    SupportSlaProjectionService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional(readOnly = true)
    List<SlaWarningNotification> notifications(String supportId) {
        return jdbc.query(
                "select ticket_id, objective, notified_at from support_sla_notification "
                        + "where support_id = ? order by notified_at, ticket_id, objective",
                (rs, row) -> new SlaWarningNotification(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getTimestamp(3).toInstant()),
                supportId);
    }

    @Transactional(readOnly = true)
    List<SharedEscalationSummary> escalations() {
        return jdbc.query(
                "select q.ticket_id, t.lifecycle_state, t.handling_mode, q.reason_code, q.entered_at, "
                        + "array_agg(f.objective order by f.objective) "
                        + "from shared_support_queue_entry q join support_ticket t on t.id = q.ticket_id "
                        + "join ticket_sla_fact f on f.ticket_id = q.ticket_id and f.fact_type = 'BREACH' "
                        + "where q.reason_code = 'SLA_BREACH' "
                        + "group by q.ticket_id, t.lifecycle_state, t.handling_mode, q.reason_code, q.entered_at "
                        + "order by q.entered_at, q.ticket_id",
                (rs, row) -> new SharedEscalationSummary(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3), rs.getString(4),
                        List.of((String[]) rs.getArray(6).getArray()), rs.getTimestamp(5).toInstant()));
    }

}

record SlaWarningNotification(UUID ticketId, String objective, Instant warnedAt) {}

record SharedEscalationSummary(
        UUID ticketId,
        String lifecycleState,
        String handlingMode,
        String reasonCode,
        List<String> breachedObjectives,
        Instant enteredAt) {}
