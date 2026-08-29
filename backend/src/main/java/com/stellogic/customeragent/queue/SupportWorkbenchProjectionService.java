package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
class SupportWorkbenchProjectionService {
    static final String LEGACY_EPOCH = "support-workbench-v1";
    static final String EPOCH = "support-workbench-v2";
    private static final Set<SupportTicketLifecycleState> PUBLIC_REPLY_LIFECYCLE_STATES =
            Set.of(
                    SupportTicketLifecycleState.NEW,
                    SupportTicketLifecycleState.INVESTIGATING,
                    SupportTicketLifecycleState.WAITING_FOR_CUSTOMER,
                    SupportTicketLifecycleState.WAITING_FOR_EXTERNAL);
    private final JdbcTemplate jdbc;
    private final TicketAuthorityLock ticketLock;
    private final CustomerPublicProjectionAppender publicProjection;

    SupportWorkbenchProjectionService(JdbcTemplate jdbc, TicketAuthorityLock ticketLock) {
        this(jdbc, ticketLock, null);
    }

    @Autowired
    SupportWorkbenchProjectionService(
            JdbcTemplate jdbc,
            TicketAuthorityLock ticketLock,
            CustomerPublicProjectionAppender publicProjection) {
        this.jdbc = jdbc;
        this.ticketLock = ticketLock;
        this.publicProjection = publicProjection;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    SupportWorkbenchSnapshot snapshot(String supportId) {
        return snapshot(supportId, EPOCH);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    SupportWorkbenchSnapshot snapshot(String supportId, String epoch) {
        requireSupportPrincipal(supportId);
        requireSupportedEpoch(epoch);
        List<SupportQueueItem> shared = queueItems("");
        List<SupportQueueItem> escalations = queueItems("where q.reason_code = 'SLA_BREACH' ");
        Long sequence =
                jdbc.queryForObject(
                        "select coalesce(max(epoch_sequence), 0) from support_workbench_event where epoch = ?",
                        Long.class,
                        epoch);
        UUID assignedTicketId = currentAssignmentTicketId(supportId);
        return new SupportWorkbenchSnapshot(
                epoch, sequence == null ? 0 : sequence, shared, escalations, assignedTicketId);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    List<SupportWorkbenchEvent> events(String supportId, String afterCursor) {
        WorkbenchCursor cursor = parseCursor(afterCursor);
        SupportWorkbenchSnapshot authority = snapshot(supportId, cursor.epoch());
        long after = cursor.sequence();
        if (after < 0 || after > authority.sequence()) throw new SupportWorkbenchCursorException();
        Long firstRetained =
                jdbc.queryForObject(
                        "select min(epoch_sequence) from support_workbench_event where epoch = ?",
                        Long.class,
                        cursor.epoch());
        if (after < authority.sequence() && firstRetained != null && firstRetained > after + 1) {
            throw new SupportWorkbenchCursorException();
        }
        return jdbc.query(
                "select epoch, epoch_sequence, event_type, payload::text from support_workbench_event "
                        + "where epoch = ? and epoch_sequence > ? order by epoch_sequence",
                (rs, row) ->
                        new SupportWorkbenchEvent(
                                rs.getString(1), rs.getLong(2), rs.getString(3), rs.getString(4)),
                cursor.epoch(),
                after);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    SupportTicketDetails details(String supportId, UUID ticketId) {
        requireSupportPrincipal(supportId);
        List<SupportTicketDetails> tickets =
                jdbc.query(
                        "select t.id, t.customer_id, t.order_reference, t.description, t.lifecycle_state, t.handling_mode, a.support_id "
                                + "from support_ticket t join support_assignment a on a.ticket_id = t.id "
                                + "where t.id = ? and a.support_id = ? and a.status = 'ACTIVE' "
                                + "and t.lifecycle_state not in ('RESOLVED', 'CLOSED')",
                        (rs, row) ->
                                new SupportTicketDetails(
                                        rs.getObject(1, UUID.class),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getString(4),
                                        SupportTicketLifecycleState.valueOf(rs.getString(5)),
                                        SupportHandlingMode.valueOf(rs.getString(6)),
                                        rs.getString(7),
                                        List.of(),
                                        List.of(),
                                        List.of()),
                        ticketId,
                        supportId);
        if (tickets.isEmpty()) throw new SupportTicketNotFoundException();
        SupportTicketDetails ticket = tickets.getFirst();
        List<SupportConversationMessage> conversation =
                jdbc.query(
                        "select id, author, body, sent_at from public_message where ticket_id = ? order by message_sequence",
                        (rs, row) ->
                                new SupportConversationMessage(
                                        rs.getObject(1, UUID.class),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getTimestamp(4).toInstant()),
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
                ticket.assignedSupportId(),
                conversation,
                facts,
                timeline);
    }

    @Transactional
    SupportAssignmentClaim claim(String supportId, UUID ticketId) {
        requireSupportPrincipal(supportId);
        ticketLock.acquire(ticketId);
        List<String> activeTicketStates =
                jdbc.queryForList(
                        "select lifecycle_state from support_ticket where id = ? and lifecycle_state not in ('RESOLVED', 'CLOSED') for update",
                        String.class,
                        ticketId);
        if (activeTicketStates.isEmpty()) throw new SupportTicketNotFoundException();
        List<String> activeAssignees =
                jdbc.queryForList(
                        "select support_id from support_assignment where ticket_id = ? and status = 'ACTIVE'",
                        String.class,
                        ticketId);
        if (!activeAssignees.isEmpty()) {
            if (supportId.equals(activeAssignees.getFirst())) {
                return new SupportAssignmentClaim(ticketId, supportId, true);
            }
            throw new SupportTicketNotFoundException();
        }
        Integer queued =
                jdbc.queryForObject(
                        "select count(*) from shared_support_queue_entry where ticket_id = ?",
                        Integer.class,
                        ticketId);
        if (queued == null || queued == 0) {
            throw new SupportTicketNotFoundException();
        }
        jdbc.update(
                "insert into support_assignment (id, ticket_id, support_id, status, assigned_at) "
                        + "values (?, ?, ?, 'ACTIVE', clock_timestamp())",
                UUID.randomUUID(),
                ticketId,
                supportId);
        jdbc.update("delete from shared_support_queue_entry where ticket_id = ?", ticketId);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, 'SUPPORT_ASSIGNMENT_CREATED', ?, clock_timestamp())",
                ticketId,
                supportId);
        return new SupportAssignmentClaim(ticketId, supportId, false);
    }

    @Transactional
    SupportPublicReplyResult publicReply(
            String supportId, UUID ticketId, String idempotencyKey, String body) {
        requireSupportPrincipal(supportId);
        String normalizedBody = body == null ? "" : body.trim();
        String digest = StableParameterDigest.sha256(ticketId.toString(), normalizedBody);
        ticketLock.acquire(ticketId);
        lockReplyRequest(supportId, idempotencyKey);

        SupportTicketScope ticket = currentTicketScope(supportId, ticketId);
        if (ticket == null) throw new SupportTicketNotFoundException();

        // A POST replay still requires current send authority; the query endpoint below is the
        // read-only recovery path when the assignment has been revoked after an uncertain reply.
        List<SupportReplyRequest> existing = findReplyRequest(supportId, idempotencyKey);
        if (!existing.isEmpty()) {
            SupportReplyRequest record = existing.getFirst();
            if (!record.ticketId().equals(ticketId) || !record.digest().equals(digest)) {
                throw new SupportReplyIdentityConflictException();
            }
            return new SupportPublicReplyResult(
                    record.ticketId(),
                    idempotencyKey,
                    record.publicMessageId(),
                    record.outcome(),
                    true);
        }

        requireReplyAllowed(ticket);

        if (publicProjection == null) {
            throw new IllegalStateException("support public projection is unavailable");
        }
        Timestamp databaseTime =
                jdbc.queryForObject("select clock_timestamp()", Timestamp.class);
        Instant now = databaseTime == null ? Instant.now() : databaseTime.toInstant();
        UUID publicMessageId = UUID.randomUUID();
        publicProjection.appendSupportMessageWithId(ticketId, publicMessageId, normalizedBody, now);
        jdbc.update(
                "insert into support_public_message_request "
                        + "(support_id, message_id, ticket_id, parameter_digest, public_message_id, outcome, received_at) "
                        + "values (?, ?, ?, ?, ?, 'ACCEPTED', ?)",
                supportId,
                idempotencyKey,
                ticketId,
                digest,
                publicMessageId,
                databaseTime);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, 'SUPPORT_PUBLIC_REPLY_ACCEPTED', ?, ?)",
                ticketId,
                supportId,
                databaseTime);
        return new SupportPublicReplyResult(
                ticketId, idempotencyKey, publicMessageId, "ACCEPTED", false);
    }

    @Transactional(isolation = Isolation.REPEATABLE_READ)
    SupportPublicReplyResult queryPublicReply(
            String supportId, UUID ticketId, String idempotencyKey) {
        requireSupportPrincipal(supportId);
        List<SupportReplyRequest> requests = findReplyRequest(supportId, idempotencyKey);
        if (requests.isEmpty() || !ticketId.equals(requests.getFirst().ticketId())) {
            throw new SupportTicketNotFoundException();
        }
        SupportReplyRequest record = requests.getFirst();
        return new SupportPublicReplyResult(
                record.ticketId(),
                idempotencyKey,
                record.publicMessageId(),
                record.outcome(),
                true);
    }

    private UUID currentAssignmentTicketId(String supportId) {
        List<UUID> assignments =
                jdbc.query(
                        "select a.ticket_id from support_assignment a "
                                + "join support_ticket t on t.id = a.ticket_id "
                                + "where a.support_id = ? and a.status = 'ACTIVE' "
                                + "and t.lifecycle_state not in ('RESOLVED', 'CLOSED') "
                                + "order by a.assigned_at desc, a.id desc limit 1",
                        (rs, row) -> rs.getObject(1, UUID.class),
                        supportId);
        return assignments.isEmpty() ? null : assignments.getFirst();
    }

    private SupportTicketScope currentTicketScope(String supportId, UUID ticketId) {
        List<SupportTicketScope> tickets =
                jdbc.query(
                        "select t.lifecycle_state, t.handling_mode "
                                + "from support_ticket t join support_assignment a on a.ticket_id = t.id "
                                + "where t.id = ? and a.support_id = ? and a.status = 'ACTIVE' "
                                + "and t.lifecycle_state not in ('RESOLVED', 'CLOSED') "
                                + "for update of t, a",
                        (rs, row) ->
                                new SupportTicketScope(
                                        SupportTicketLifecycleState.valueOf(rs.getString(1)),
                                        SupportHandlingMode.valueOf(rs.getString(2))),
                        ticketId,
                        supportId);
        return tickets.isEmpty() ? null : tickets.getFirst();
    }

    private List<SupportReplyRequest> findReplyRequest(String supportId, String idempotencyKey) {
        return jdbc.query(
                "select ticket_id, parameter_digest, public_message_id, outcome "
                        + "from support_public_message_request where support_id = ? and message_id = ?",
                (rs, row) ->
                        new SupportReplyRequest(
                                rs.getObject(1, UUID.class),
                                rs.getString(2),
                                rs.getObject(3, UUID.class),
                                rs.getString(4)),
                supportId,
                idempotencyKey);
    }

    private void lockReplyRequest(String supportId, String idempotencyKey) {
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                resultSet -> null,
                supportId + "\nSUPPORT_PUBLIC_REPLY\n" + idempotencyKey);
    }

    private static void requireReplyAllowed(SupportTicketScope ticket) {
        if (!PUBLIC_REPLY_LIFECYCLE_STATES.contains(ticket.lifecycleState())
                || ticket.handlingMode() != SupportHandlingMode.HUMAN) {
            throw new SupportPublicReplyNotAllowedException();
        }
    }

    private List<SupportQueueItem> queueItems(String predicate) {
        return jdbc.query(
                "select q.ticket_id, t.order_reference, t.issue_kind, t.lifecycle_state, t.handling_mode, min(q.entered_at) "
                        + "from shared_support_queue_entry q join support_ticket t on t.id = q.ticket_id "
                        + predicate
                        + "group by q.ticket_id, t.order_reference, t.issue_kind, t.lifecycle_state, t.handling_mode "
                        + "order by min(q.entered_at), q.ticket_id",
                (rs, row) ->
                        new SupportQueueItem(
                                rs.getObject(1, UUID.class),
                                rs.getString(2),
                                rs.getString(3),
                                SupportTicketLifecycleState.valueOf(rs.getString(4)),
                                SupportHandlingMode.valueOf(rs.getString(5)),
                                rs.getTimestamp(6).toInstant()));
    }

    private static WorkbenchCursor parseCursor(String cursor) {
        if (cursor == null || cursor.isBlank()) return new WorkbenchCursor(EPOCH, 0);
        int separator = cursor.lastIndexOf(':');
        if (separator < 1) {
            throw new SupportWorkbenchCursorException();
        }
        String epoch = cursor.substring(0, separator);
        requireSupportedEpoch(epoch);
        try {
            return new WorkbenchCursor(epoch, Long.parseLong(cursor.substring(separator + 1)));
        } catch (NumberFormatException exception) {
            throw new SupportWorkbenchCursorException();
        }
    }

    private static void requireSupportedEpoch(String epoch) {
        if (!EPOCH.equals(epoch) && !LEGACY_EPOCH.equals(epoch)) {
            throw new SupportWorkbenchCursorException();
        }
    }

    private record WorkbenchCursor(String epoch, long sequence) {}

    private record SupportTicketScope(
            SupportTicketLifecycleState lifecycleState, SupportHandlingMode handlingMode) {}

    private record SupportReplyRequest(
            UUID ticketId, String digest, UUID publicMessageId, String outcome) {}

    private static void requireSupportPrincipal(String supportId) {
        if (supportId == null || supportId.isBlank()) {
            throw new SupportIdentityRequiredException();
        }
    }
}
