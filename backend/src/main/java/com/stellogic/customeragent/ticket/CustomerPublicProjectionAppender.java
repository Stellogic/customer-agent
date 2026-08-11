package com.stellogic.customeragent.ticket;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public final class CustomerPublicProjectionAppender {
    private static final String EPOCH = "customer-public-v1";
    private final JdbcTemplate jdbc;

    public CustomerPublicProjectionAppender(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void appendSupportMessage(UUID ticketId, String body, Instant now, boolean resolved) {
        Timestamp at = Timestamp.from(now);
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) "
                        + "values (?, ?, ?, 'SUPPORT', ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, body, at);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', "
                        + "jsonb_build_object('author', 'SUPPORT', 'body', ?, 'sentAt', ?::text), ?)",
                ticketId, EPOCH, eventSequence, body, now.toString(), at);
        if (resolved) {
            jdbc.update(
                    "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, 'TICKET_RESOLVED', "
                            + "jsonb_build_object('lifecycleState', 'RESOLVED'), ?)",
                    ticketId, EPOCH, eventSequence + 1, at);
        }
    }
}
