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

    public void appendSupportMessage(UUID ticketId, String body, Instant now) {
        appendMessage(ticketId, body, now);
    }

    public void appendSupportMessageAndResolutionEvent(UUID ticketId, String body, Instant now) {
        long resolutionEventSequence = appendMessage(ticketId, body, now);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, 'TICKET_RESOLVED', "
                        + "jsonb_build_object('lifecycleState', 'RESOLVED'), ?)",
                ticketId, EPOCH, resolutionEventSequence, Timestamp.from(now));
    }

    public void appendAgentMessage(
            UUID ticketId, UUID generationId, String body, Instant now, boolean resolved) {
        long nextEventSequence = appendMessage(ticketId, generationId, "AGENT", body, now);
        if (resolved) {
            appendGenerationEvent(ticketId, generationId, nextEventSequence, "TICKET_RESOLVED",
                    "jsonb_build_object('lifecycleState', 'RESOLVED')", now);
        }
    }

    public void appendClarificationMessage(
            UUID ticketId,
            UUID generationId,
            String author,
            String body,
            Instant now,
            String transitionType,
            UUID clarificationId,
            String promptCode,
            String question) {
        long nextEventSequence = appendMessage(ticketId, generationId, author, body, now);
        Timestamp at = Timestamp.from(now);
        long sourceGeneration = sourceGeneration(ticketId, generationId);
        if (clarificationId != null) {
            jdbc.update(
                    "insert into customer_public_event "
                            + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, ?, ?, "
                            + "jsonb_build_object('lifecycleState', 'WAITING_FOR_CUSTOMER', "
                            + "'clarification', jsonb_build_object('id', ?::text, 'promptCode', ?, 'question', ?)), ?)",
                    ticketId, EPOCH, nextEventSequence, sourceGeneration, transitionType,
                    clarificationId.toString(), promptCode, question, at);
        } else {
            jdbc.update(
                    "insert into customer_public_event "
                            + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, ?, ?, "
                            + "jsonb_build_object('lifecycleState', 'INVESTIGATING', 'clarification', null), ?)",
                    ticketId, EPOCH, nextEventSequence, sourceGeneration, transitionType, at);
        }
    }

    public void appendHandoffMessage(UUID ticketId, UUID generationId, String body, Instant now) {
        Timestamp at = Timestamp.from(now);
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, EPOCH);
        long sourceGeneration = sourceGeneration(ticketId, generationId);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) "
                        + "values (?, ?, ?, 'SUPPORT', ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, body, at);
        jdbc.update(
                "insert into customer_public_event "
                        + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', "
                        + "jsonb_build_object('author', 'SUPPORT', 'body', ?, 'sentAt', ?::text), ?), "
                        + "(?, ?, ?, ?, 'TICKET_HANDED_OFF', "
                        + "jsonb_build_object('handlingMode', 'HUMAN', 'clarification', null), ?)",
                ticketId, EPOCH, eventSequence, sourceGeneration, body, now.toString(), at,
                ticketId, EPOCH, eventSequence + 1, sourceGeneration, at);
    }

    private long appendMessage(UUID ticketId, String body, Instant now) {
        return appendMessage(ticketId, null, "SUPPORT", body, now);
    }

    private long appendMessage(
            UUID ticketId, UUID generationId, String author, String body, Instant now) {
        Timestamp at = Timestamp.from(now);
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) "
                        + "values (?, ?, ?, ?, ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, author, body, at);
        if (generationId == null) {
            jdbc.update(
                    "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', "
                            + "jsonb_build_object('author', ?, 'body', ?, 'sentAt', ?::text), ?)",
                    ticketId, EPOCH, eventSequence, author, body, now.toString(), at);
        } else {
            jdbc.update(
                    "insert into customer_public_event "
                            + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', "
                            + "jsonb_build_object('author', ?, 'body', ?, 'sentAt', ?::text), ?)",
                    ticketId, EPOCH, eventSequence, sourceGeneration(ticketId, generationId),
                    author, body, now.toString(), at);
        }
        return eventSequence + 1;
    }

    private void appendGenerationEvent(
            UUID ticketId,
            UUID generationId,
            long sequence,
            String eventType,
            String payloadExpression,
            Instant now) {
        jdbc.update(
                "insert into customer_public_event "
                        + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, ?, ?, " + payloadExpression + ", ?)",
                ticketId, EPOCH, sequence, sourceGeneration(ticketId, generationId),
                eventType, Timestamp.from(now));
    }

    private long sourceGeneration(UUID ticketId, UUID generationId) {
        if (generationId == null) {
            return 0;
        }
        Long generation = jdbc.queryForObject(
                "select generation_number from agent_processing_generation where id = ? and ticket_id = ?",
                Long.class, generationId, ticketId);
        if (generation == null) {
            throw new IllegalStateException("agent generation does not belong to ticket");
        }
        return generation;
    }
}
