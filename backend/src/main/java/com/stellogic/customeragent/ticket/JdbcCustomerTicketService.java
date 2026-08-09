package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class JdbcCustomerTicketService implements CustomerTicketService {
    private static final String EPOCH = "customer-public-v1";
    private static final String ACKNOWLEDGEMENT = "您的物流延迟问题已受理，我们会在此公开沟通中更新进展。";
    private final JdbcTemplate jdbc;
    private final Clock clock;

    @Autowired
    public JdbcCustomerTicketService(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    @Override
    @Transactional
    public TicketCreationResult create(CreateCustomerTicket command) {
        String digest = StableParameterDigest.sha256(command.orderReference(), command.description());
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                (ResultSetExtractor<Void>) resultSet -> null,
                command.customerId() + "\n" + command.requestId());
        List<RequestRecord> existing = jdbc.query(
                "select parameter_digest, ticket_id from customer_ticket_request where customer_id = ? and request_id = ?",
                (rs, row) -> new RequestRecord(rs.getString(1), rs.getObject(2, UUID.class)),
                command.customerId(),
                command.requestId());
        if (!existing.isEmpty()) {
            RequestRecord record = existing.getFirst();
            if (!record.digest().equals(digest)) throw new RequestIdentityConflictException();
            return new TicketCreationResult(record.ticketId(), true);
        }

        UUID ticketId = UUID.randomUUID();
        Instant now = clock.instant();
        Timestamp databaseTime = Timestamp.from(now);
        boolean startsAgentInvestigation = !jdbc.query(
                "select 1 from synthetic_order where order_reference = ? and customer_id = ? "
                        + "union all select 1 from synthetic_order_alias where alias = ? and customer_id = ? limit 1",
                (rs, row) -> rs.getInt(1),
                command.orderReference(), command.customerId(), command.orderReference(), command.customerId()).isEmpty();
        jdbc.update(
                "insert into support_ticket (id, customer_id, order_reference, description, lifecycle_state, handling_mode, "
                        + "created_at, first_responded_at, resolution_running_since) "
                        + "values (?, ?, ?, ?, 'INVESTIGATING', 'AGENT', ?, ?, ?)",
                ticketId,
                command.customerId(),
                command.orderReference(),
                command.description(),
                databaseTime,
                databaseTime,
                databaseTime);
        jdbc.update(
                "insert into customer_ticket_request (customer_id, request_id, parameter_digest, ticket_id) values (?, ?, ?, ?)",
                command.customerId(), command.requestId(), digest, ticketId);
        UUID generationId = UUID.randomUUID();
        UUID threadId = UUID.randomUUID();
        jdbc.update(
                "insert into agent_processing_generation (id, ticket_id, generation_number, thread_id, status, created_at) values (?, ?, 1, ?, 'ACTIVE', ?)",
                generationId, ticketId, threadId, databaseTime);
        if (startsAgentInvestigation) {
            UUID submissionRequestId = UUID.randomUUID();
            jdbc.update(
                    "insert into agent_submission (submission_request_id, generation_id, thread_id, parameter_digest, status, next_attempt_at, created_at) values (?, ?, ?, ?, 'PENDING', current_timestamp, ?)",
                    submissionRequestId,
                    generationId,
                    threadId,
                    StableParameterDigest.sha256(
                            ticketId.toString(), generationId.toString(), threadId.toString(), submissionRequestId.toString()),
                    databaseTime);
        }
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) values (?, ?, 1, 'CUSTOMER', ?, ?), (?, ?, 2, 'SUPPORT', ?, ?)",
                UUID.randomUUID(), ticketId, command.description(), databaseTime,
                UUID.randomUUID(), ticketId, ACKNOWLEDGEMENT, databaseTime);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, 'TICKET_CREATED', ?, ?), (?, 'FIRST_RESPONSE_RECORDED', 'spring-system', ?)",
                ticketId, command.customerId(), databaseTime, ticketId, databaseTime);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, 'AGENT_GENERATION_CREATED', 'spring-system', ?)",
                ticketId, databaseTime);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) values (?, ?, 1, 'TICKET_ACCEPTED', jsonb_build_object('ticketId', ?::text, 'lifecycleState', 'INVESTIGATING', 'handlingMode', 'AGENT'), ?), (?, ?, 2, 'PUBLIC_MESSAGE_APPENDED', jsonb_build_object('author', 'SUPPORT', 'body', ?, 'sentAt', ?::text), ?)",
                ticketId, EPOCH, ticketId.toString(), databaseTime,
                ticketId, EPOCH, ACKNOWLEDGEMENT, now.toString(), databaseTime);
        return new TicketCreationResult(ticketId, false);
    }

    @Override
    @Transactional(readOnly = true)
    public CustomerPublicSnapshot snapshot(String customerId, UUID ticketId) {
        List<CustomerPublicSnapshot> snapshots = jdbc.query(
                "select id, lifecycle_state, handling_mode, created_at, first_responded_at, coalesce((select max(sequence) from customer_public_event e where e.ticket_id = t.id and e.epoch = ?), 0) from support_ticket t where id = ? and customer_id = ?",
                (rs, row) -> new CustomerPublicSnapshot(
                        rs.getObject(1, UUID.class),
                        rs.getString(2),
                        rs.getString(3),
                        rs.getTimestamp(4).toInstant(),
                        rs.getTimestamp(5).toInstant(),
                        EPOCH,
                        rs.getLong(6),
                        List.of(),
                        null),
                EPOCH, ticketId, customerId);
        if (snapshots.isEmpty()) throw new TicketNotFoundException();
        List<PublicMessage> messages = jdbc.query(
                "select author, body, sent_at from public_message where ticket_id = ? order by message_sequence",
                JdbcCustomerTicketService::mapMessage,
                ticketId);
        CustomerPublicSnapshot ticket = snapshots.getFirst();
        List<CurrentClarification> clarifications = jdbc.query(
                "select id, prompt_code, public_question from customer_clarification_request "
                        + "where ticket_id = ? and status = 'OPEN'",
                (rs, row) -> new CurrentClarification(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3)),
                ticketId);
        return new CustomerPublicSnapshot(
                ticket.ticketId(), ticket.lifecycleState(), ticket.handlingMode(), ticket.createdAt(),
                ticket.firstRespondedAt(), ticket.epoch(), ticket.sequence(), messages,
                clarifications.isEmpty() ? null : clarifications.getFirst());
    }

    @Override
    @Transactional(readOnly = true)
    public List<CustomerPublicEvent> events(String customerId, UUID ticketId, String afterCursor) {
        snapshot(customerId, ticketId);
        long after = 0;
        if (afterCursor != null && !afterCursor.isBlank()) {
            int separator = afterCursor.lastIndexOf(':');
            if (separator < 1 || !EPOCH.equals(afterCursor.substring(0, separator))) {
                throw new ProjectionCursorException();
            }
            try {
                after = Long.parseLong(afterCursor.substring(separator + 1));
            } catch (NumberFormatException exception) {
                throw new ProjectionCursorException();
            }
        }
        return jdbc.query(
                "select epoch, sequence, event_type, payload::text from customer_public_event where ticket_id = ? and epoch = ? and sequence > ? order by sequence",
                (rs, row) -> new CustomerPublicEvent(rs.getString(1), rs.getLong(2), rs.getString(3), rs.getString(4)),
                ticketId, EPOCH, after);
    }

    private static PublicMessage mapMessage(ResultSet rs, int row) throws SQLException {
        return new PublicMessage(rs.getString(1), rs.getString(2), rs.getTimestamp(3).toInstant());
    }

    private record RequestRecord(String digest, UUID ticketId) {}
}
