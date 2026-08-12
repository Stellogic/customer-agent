package com.stellogic.customeragent.queue;

import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
class SupportWorkbenchProjectionService {
    static final String EPOCH = "support-workbench-v1";
    private static final String SUPPORT_ID = "support-demo";
    private final JdbcTemplate jdbc;

    SupportWorkbenchProjectionService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    SupportWorkbenchSnapshot snapshot(String supportId) {
        requireSupport(supportId);
        List<SupportQueueItem> shared = queueItems("");
        List<SupportQueueItem> escalations = queueItems("where q.reason_code = 'SLA_BREACH' ");
        Long sequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) from support_workbench_event where epoch = ?",
                        Long.class,
                        EPOCH);
        return new SupportWorkbenchSnapshot(
                EPOCH, sequence == null ? 0 : sequence, shared, escalations);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    List<SupportWorkbenchEvent> events(String supportId, String afterCursor) {
        SupportWorkbenchSnapshot authority = snapshot(supportId);
        long after = parseCursor(afterCursor);
        if (after < 0 || after > authority.sequence()) throw new SupportWorkbenchCursorException();
        Long firstRetained =
                jdbc.queryForObject(
                        "select min(sequence) from support_workbench_event where epoch = ?",
                        Long.class,
                        EPOCH);
        if (after < authority.sequence() && firstRetained != null && firstRetained > after + 1) {
            throw new SupportWorkbenchCursorException();
        }
        return jdbc.query(
                "select epoch, sequence, event_type, payload::text from support_workbench_event "
                        + "where epoch = ? and sequence > ? order by sequence",
                (rs, row) ->
                        new SupportWorkbenchEvent(
                                rs.getString(1), rs.getLong(2), rs.getString(3), rs.getString(4)),
                EPOCH,
                after);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    SupportTicketDetails details(String supportId, UUID ticketId) {
        requireSupport(supportId);
        List<SupportTicketDetails> tickets =
                jdbc.query(
                        "select t.id, t.customer_id, t.order_reference, t.description, t.lifecycle_state, t.handling_mode "
                                + "from support_ticket t join support_assignment a on a.ticket_id = t.id "
                                + "where t.id = ? and a.support_id = ? and a.status = 'ACTIVE'",
                        (rs, row) ->
                                new SupportTicketDetails(
                                        rs.getObject(1, UUID.class),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getString(4),
                                        SupportTicketLifecycleState.valueOf(rs.getString(5)),
                                        SupportHandlingMode.valueOf(rs.getString(6)),
                                        List.of(),
                                        List.of(),
                                        List.of()),
                        ticketId,
                        supportId);
        if (tickets.isEmpty()) throw new SupportTicketNotFoundException();
        SupportTicketDetails ticket = tickets.getFirst();
        List<SupportConversationMessage> conversation =
                jdbc.query(
                        "select author, body, sent_at from public_message where ticket_id = ? order by message_sequence",
                        (rs, row) ->
                                new SupportConversationMessage(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getTimestamp(3).toInstant()),
                        ticketId);
        List<SupportInvestigationFact> facts =
                jdbc.query(
                        "select f.fact_type, f.fact_value, f.evidence_reference, f.recorded_at "
                                + "from investigation_fact f join agent_processing_generation g on g.id = f.generation_id "
                                + "where g.ticket_id = ? order by f.recorded_at, f.fact_type",
                        (rs, row) ->
                                new SupportInvestigationFact(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getTimestamp(4).toInstant()),
                        ticketId);
        List<SupportTimelineEvent> timeline =
                jdbc.query(
                        "select event_type, actor_id, occurred_at from audit_event where ticket_id = ? order by occurred_at, id",
                        (rs, row) ->
                                new SupportTimelineEvent(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getTimestamp(3).toInstant()),
                        ticketId);
        return new SupportTicketDetails(
                ticket.ticketId(),
                ticket.customerId(),
                ticket.orderReference(),
                ticket.description(),
                ticket.lifecycleState(),
                ticket.handlingMode(),
                conversation,
                facts,
                timeline);
    }

    private List<SupportQueueItem> queueItems(String predicate) {
        return jdbc.query(
                "select q.ticket_id, t.lifecycle_state, t.handling_mode, min(q.entered_at) "
                        + "from shared_support_queue_entry q join support_ticket t on t.id = q.ticket_id "
                        + predicate
                        + "group by q.ticket_id, t.lifecycle_state, t.handling_mode "
                        + "order by min(q.entered_at), q.ticket_id",
                (rs, row) ->
                        new SupportQueueItem(
                                rs.getObject(1, UUID.class),
                                SupportTicketLifecycleState.valueOf(rs.getString(2)),
                                SupportHandlingMode.valueOf(rs.getString(3)),
                                rs.getTimestamp(4).toInstant()));
    }

    private static long parseCursor(String cursor) {
        if (cursor == null || cursor.isBlank()) return 0;
        int separator = cursor.lastIndexOf(':');
        if (separator < 1 || !EPOCH.equals(cursor.substring(0, separator))) {
            throw new SupportWorkbenchCursorException();
        }
        try {
            return Long.parseLong(cursor.substring(separator + 1));
        } catch (NumberFormatException exception) {
            throw new SupportWorkbenchCursorException();
        }
    }

    static void requireSupport(String supportId) {
        if (!SUPPORT_ID.equals(supportId == null ? null : supportId.trim())) {
            throw new SupportIdentityRequiredException();
        }
    }
}
