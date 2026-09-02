package com.stellogic.customeragent.closure;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
import com.stellogic.customeragent.ticket.CustomerTicketService;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class JdbcClosureService implements ClosureService {
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TicketAuthorityLock authorityLock;
    private final CustomerTicketService ticketService;
    private final CustomerPublicProjectionAppender publicProjection;

    JdbcClosureService(
            JdbcTemplate jdbc,
            Clock clock,
            TicketAuthorityLock authorityLock,
            CustomerTicketService ticketService,
            CustomerPublicProjectionAppender publicProjection) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.authorityLock = authorityLock;
        this.ticketService = ticketService;
        this.publicProjection = publicProjection;
    }

    @Override
    @Transactional
    public CustomerReplyResult reply(CustomerReplyCommand command) {
        String digest =
                StableParameterDigest.sha256(
                        command.originalTicketId().toString(), command.orderReference(),
                        command.issueKind(), command.message());
        authorityLock.acquire(command.originalTicketId());
        List<MessageRecord> replay =
                jdbc.query(
                        "select parameter_digest, result_ticket_id, outcome from customer_reply_request "
                                + "where customer_id = ? and message_id = ?",
                        (rs, row) ->
                                new MessageRecord(
                                        rs.getString(1),
                                        rs.getObject(2, UUID.class),
                                        rs.getString(3)),
                        command.customerId(),
                        command.messageId());
        if (!replay.isEmpty()) {
            MessageRecord record = replay.getFirst();
            if (!record.digest().equals(digest))
                throw new CustomerMessageIdentityConflictException();
            return new CustomerReplyResult(record.resultTicketId(), record.outcome(), true);
        }

        List<TicketRecord> tickets =
                jdbc.query(
                        "select order_reference, issue_kind, lifecycle_state, handling_mode, customer_human_preference, resolved_at "
                                + "from support_ticket where id = ? and customer_id = ? for update",
                        (rs, row) ->
                                new TicketRecord(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getString(4),
                                        rs.getBoolean(5),
                                        rs.getTimestamp(6) == null
                                                ? null
                                                : rs.getTimestamp(6).toInstant()),
                        command.originalTicketId(),
                        command.customerId());
        if (tickets.isEmpty()) throw new ClosureTicketNotFoundException();
        TicketRecord ticket = tickets.getFirst();
        if (!"RESOLVED".equals(ticket.lifecycleState())
                && !"CLOSED".equals(ticket.lifecycleState())) {
            throw new TicketNotReplyableException();
        }

        Instant now = clock.instant();
        boolean sameIssue =
                ticket.orderReference().equals(command.orderReference())
                        && ticket.issueKind().equals(command.issueKind());
        boolean windowOpen =
                "RESOLVED".equals(ticket.lifecycleState())
                        && ticket.resolvedAt() != null
                        && ClosureDeadline.isOpen(ticket.resolvedAt(), now);
        CustomerReplyResult result;
        if (sameIssue && windowOpen) {
            reopen(command, ticket, now);
            result = new CustomerReplyResult(command.originalTicketId(), "REOPENED", false);
        } else {
            if ("RESOLVED".equals(ticket.lifecycleState()) && !windowOpen) {
                closeLocked(command.originalTicketId(), now);
            }
            result = createLinkedTicket(command, now);
        }
        jdbc.update(
                "insert into customer_reply_request "
                        + "(customer_id, message_id, parameter_digest, original_ticket_id, result_ticket_id, outcome, received_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?)",
                command.customerId(),
                command.messageId(),
                digest,
                command.originalTicketId(),
                result.ticketId(),
                result.outcome(),
                Timestamp.from(now));
        return result;
    }

    @Override
    public UUID continueFromConfirmedIntake(
            String customerId,
            UUID originalTicketId,
            String messageId,
            String orderReference,
            String issueKind,
            String message) {
        return reply(
                        new CustomerReplyCommand(
                                customerId,
                                originalTicketId,
                                messageId,
                                orderReference,
                                issueKind,
                                message))
                .ticketId();
    }

    private void reopen(CustomerReplyCommand command, TicketRecord ticket, Instant now) {
        Timestamp at = Timestamp.from(now);
        jdbc.update(
                "update support_ticket set lifecycle_state = 'INVESTIGATING', resolution_running_since = ?, "
                        + "resolved_at = null, close_due_at = null where id = ? and lifecycle_state = 'RESOLVED'",
                at,
                command.originalTicketId());
        if ("AGENT".equals(ticket.handlingMode()) && !ticket.customerHumanPreference()) {
            createFreshGeneration(command.originalTicketId(), at);
        }
        publicProjection.appendCustomerReplyAndReopened(
                command.originalTicketId(), command.message(), now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values "
                        + "(?, 'CUSTOMER_REPLY_RECEIVED', ?, ?), (?, 'TICKET_REOPENED', 'spring-system', ?)",
                command.originalTicketId(),
                command.customerId(),
                at,
                command.originalTicketId(),
                at);
    }

    private void createFreshGeneration(UUID ticketId, Timestamp at) {
        jdbc.update(
                "update agent_processing_generation set status = 'SUPERSEDED' "
                        + "where ticket_id = ? and status = 'ACTIVE'",
                ticketId);
        Integer generationNumber =
                jdbc.queryForObject(
                        "select coalesce(max(generation_number), 0) + 1 from agent_processing_generation where ticket_id = ?",
                        Integer.class,
                        ticketId);
        UUID generationId = UUID.randomUUID();
        UUID threadId = UUID.randomUUID();
        UUID submissionRequestId = UUID.randomUUID();
        jdbc.update(
                "insert into agent_processing_generation "
                        + "(id, ticket_id, generation_number, thread_id, status, created_at) "
                        + "values (?, ?, ?, ?, 'ACTIVE', ?)",
                generationId,
                ticketId,
                generationNumber,
                threadId,
                at);
        jdbc.update(
                "insert into agent_submission "
                        + "(submission_request_id, generation_id, thread_id, parameter_digest, status, next_attempt_at, created_at) "
                        + "values (?, ?, ?, ?, 'PENDING', ?, ?)",
                submissionRequestId,
                generationId,
                threadId,
                StableParameterDigest.sha256(
                        ticketId.toString(),
                        generationId.toString(),
                        threadId.toString(),
                        submissionRequestId.toString()),
                at,
                at);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, 'AGENT_GENERATION_CREATED', 'spring-system', ?)",
                ticketId,
                at);
    }

    private CustomerReplyResult createLinkedTicket(CustomerReplyCommand command, Instant now) {
        UUID linkedTicketId =
                ticketService.createFollowUp(
                        command.customerId(),
                        "follow-up:" + command.originalTicketId() + ":" + command.messageId(),
                        command.orderReference(),
                        command.message(),
                        command.issueKind(),
                        command.originalTicketId());
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values "
                        + "(?, 'FOLLOW_UP_TICKET_CREATED', ?, ?), (?, 'FOLLOW_UP_LINKED', 'spring-system', ?)",
                command.originalTicketId(),
                command.customerId(),
                Timestamp.from(now),
                linkedTicketId,
                Timestamp.from(now));
        return new CustomerReplyResult(linkedTicketId, "LINKED_TICKET_CREATED", false);
    }

    @Override
    @Transactional(readOnly = true)
    public List<UUID> dueTicketIds(Instant now) {
        return jdbc.query(
                "select id from support_ticket where lifecycle_state = 'RESOLVED' and close_due_at <= ? order by close_due_at",
                (rs, row) -> rs.getObject(1, UUID.class),
                Timestamp.from(now));
    }

    @Override
    @Transactional
    public void closeIfDue(UUID ticketId, Instant now) {
        authorityLock.acquire(ticketId);
        closeLocked(ticketId, now);
    }

    private void closeLocked(UUID ticketId, Instant now) {
        Timestamp at = Timestamp.from(now);
        int updated =
                jdbc.update(
                        "update support_ticket set lifecycle_state = 'CLOSED', closed_at = ?, close_reason = 'WAITING_PERIOD_EXPIRED' "
                                + "where id = ? and lifecycle_state = 'RESOLVED' and close_due_at <= ?",
                        at,
                        ticketId,
                        at);
        if (updated == 0) return;
        jdbc.update("delete from shared_support_queue_entry where ticket_id = ?", ticketId);
        publicProjection.appendClosed(ticketId, now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, 'TICKET_CLOSED', 'spring-system', ?)",
                ticketId,
                at);
    }

    private record MessageRecord(String digest, UUID resultTicketId, String outcome) {}

    private record TicketRecord(
            String orderReference,
            String issueKind,
            String lifecycleState,
            String handlingMode,
            boolean customerHumanPreference,
            Instant resolvedAt) {}
}
