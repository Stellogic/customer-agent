package com.stellogic.customeragent.ticket;

import java.nio.charset.StandardCharsets;
import java.nio.ByteBuffer;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.HexFormat;
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
    public JdbcCustomerTicketService(JdbcTemplate jdbc) {
        this(jdbc, Clock.systemUTC());
    }

    JdbcCustomerTicketService(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    @Override
    @Transactional
    public TicketCreationResult create(CreateCustomerTicket command) {
        String digest = digest(command.orderReference(), command.description());
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
        jdbc.update(
                "insert into support_ticket (id, customer_id, order_reference, description, lifecycle_state, handling_mode, created_at, first_responded_at) values (?, ?, ?, ?, 'INVESTIGATING', 'AGENT', ?, ?)",
                ticketId,
                command.customerId(),
                command.orderReference(),
                command.description(),
                databaseTime,
                databaseTime);
        jdbc.update(
                "insert into customer_ticket_request (customer_id, request_id, parameter_digest, ticket_id) values (?, ?, ?, ?)",
                command.customerId(), command.requestId(), digest, ticketId);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) values (?, ?, 1, 'CUSTOMER', ?, ?), (?, ?, 2, 'SUPPORT', ?, ?)",
                UUID.randomUUID(), ticketId, command.description(), databaseTime,
                UUID.randomUUID(), ticketId, ACKNOWLEDGEMENT, databaseTime);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, 'TICKET_CREATED', ?, ?), (?, 'FIRST_RESPONSE_RECORDED', 'spring-system', ?)",
                ticketId, command.customerId(), databaseTime, ticketId, databaseTime);
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
                        List.of()),
                EPOCH, ticketId, customerId);
        if (snapshots.isEmpty()) throw new TicketNotFoundException();
        List<PublicMessage> messages = jdbc.query(
                "select author, body, sent_at from public_message where ticket_id = ? order by message_sequence",
                JdbcCustomerTicketService::mapMessage,
                ticketId);
        CustomerPublicSnapshot ticket = snapshots.getFirst();
        return new CustomerPublicSnapshot(
                ticket.ticketId(), ticket.lifecycleState(), ticket.handlingMode(), ticket.createdAt(),
                ticket.firstRespondedAt(), ticket.epoch(), ticket.sequence(), messages);
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

    private static String digest(String... values) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (String value : values) {
                byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
                digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(bytes.length).array());
                digest.update(bytes);
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }

    private record RequestRecord(String digest, UUID ticketId) {}
}
