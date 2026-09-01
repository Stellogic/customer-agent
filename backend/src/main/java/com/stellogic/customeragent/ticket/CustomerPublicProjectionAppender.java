package com.stellogic.customeragent.ticket;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

@Component
public final class CustomerPublicProjectionAppender {
    private static final String EPOCH = "customer-public-v1";
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;

    public CustomerPublicProjectionAppender(JdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = jdbc;
        this.json = json;
    }

    public void appendSupportMessage(UUID ticketId, String body, Instant now) {
        appendMessage(ticketId, UUID.randomUUID(), null, "SUPPORT", body, now);
    }

    public UUID appendSupportMessageWithId(
            UUID ticketId, UUID publicMessageId, String body, Instant now) {
        appendMessage(ticketId, publicMessageId, null, "SUPPORT", body, now);
        return publicMessageId;
    }

    public void appendCustomerReplyAndReopened(UUID ticketId, String body, Instant now) {
        long transitionSequence = appendMessage(ticketId, null, "CUSTOMER", body, now);
        appendTicketTransition(
                ticketId, transitionSequence, "TICKET_REOPENED", "INVESTIGATING", now);
    }

    public void appendClosed(UUID ticketId, Instant now) {
        Long sequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) + 1 from customer_public_event where"
                                + " ticket_id = ? and epoch = ?",
                        Long.class,
                        ticketId,
                        EPOCH);
        appendTicketTransition(ticketId, sequence, "TICKET_CLOSED", "CLOSED", now);
    }

    public void appendSupportMessageAndResolutionEvent(UUID ticketId, String body, Instant now) {
        long resolutionEventSequence = appendMessage(ticketId, body, now);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type,"
                        + " payload, occurred_at) values (?, ?, ?, 'TICKET_RESOLVED',"
                        + " jsonb_build_object('lifecycleState', 'RESOLVED'), ?)",
                ticketId,
                EPOCH,
                resolutionEventSequence,
                Timestamp.from(now));
    }

    public void appendCompensationReviewCleared(UUID ticketId, String status, Instant now) {
        Long sequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) + 1 from customer_public_event where"
                                + " ticket_id = ? and epoch = ?",
                        Long.class,
                        ticketId,
                        EPOCH);
        jdbc.update(
                "insert into customer_public_event "
                        + "(ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, 'COMPENSATION_REVIEW_CLEARED', "
                        + "jsonb_build_object('status', ?), ?)",
                ticketId,
                EPOCH,
                sequence,
                status,
                Timestamp.from(now));
    }

    public void appendAgentMessage(
            UUID ticketId, UUID generationId, String body, Instant now, boolean resolved) {
        long nextEventSequence = appendMessage(ticketId, generationId, "AGENT", body, now);
        if (resolved) {
            appendGenerationEvent(
                    ticketId,
                    generationId,
                    nextEventSequence,
                    "TICKET_RESOLVED",
                    "jsonb_build_object('lifecycleState', 'RESOLVED')",
                    now);
        }
    }

    public void appendAgentKnowledgeMessage(
            UUID ticketId,
            UUID generationId,
            String body,
            CustomerKnowledgeProjection knowledge,
            Instant now) {
        appendMessage(ticketId, UUID.randomUUID(), generationId, "AGENT", body, now, knowledge);
    }

    public void completeBufferedAgentReplyStream(
            UUID ticketId, UUID generationId, String body, Instant now) {
        int updated =
                jdbc.update(
                        "update agent_public_reply_stream set status='STREAMING', body=?,"
                                + " updated_at=? where generation_id=? and ticket_id=? and"
                                + " status='LOADING' and body=''",
                        body,
                        Timestamp.from(now),
                        generationId,
                        ticketId);
        if (updated != 1) {
            throw new IllegalStateException(
                    "knowledge reply must remain buffered until acceptance");
        }
        completeAgentReplyStream(ticketId, generationId, body, now);
    }

    public void completeAgentReplyStream(
            UUID ticketId, UUID generationId, String body, Instant now) {
        java.util.List<ReplyStreamState> streams =
                jdbc.query(
                        "select status, body from agent_public_reply_stream where generation_id = ?"
                                + " and ticket_id = ? for update",
                        (rs, row) -> new ReplyStreamState(rs.getString(1), rs.getString(2)),
                        generationId,
                        ticketId);
        if (streams.isEmpty()) return;
        ReplyStreamState stream = streams.getFirst();
        if (!"STREAMING".equals(stream.status()) || !body.equals(stream.body())) {
            throw new ResponseStatusException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "persisted reply stream does not match the accepted conclusion");
        }
        jdbc.update(
                "update agent_public_reply_stream set status = 'COMPLETED', updated_at = ? where"
                        + " generation_id = ?",
                Timestamp.from(now),
                generationId);
        Long sequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) + 1 from customer_public_event where"
                                + " ticket_id = ? and epoch = ?",
                        Long.class,
                        ticketId,
                        EPOCH);
        appendGenerationEvent(
                ticketId,
                generationId,
                sequence,
                "AGENT_REPLY_COMPLETED",
                "jsonb_build_object('status', 'COMPLETED')",
                now);
    }

    public void terminalizeAgentReplyStream(
            UUID ticketId, UUID generationId, String status, Instant now) {
        if (!java.util.Set.of("ABORTED", "FAILED").contains(status)) {
            throw new IllegalArgumentException("unsupported reply stream terminal status");
        }
        java.util.List<String> states =
                jdbc.query(
                        "select status from agent_public_reply_stream where generation_id = ? and"
                                + " ticket_id = ? for update",
                        (rs, row) -> rs.getString(1),
                        generationId,
                        ticketId);
        if (states.isEmpty()
                || java.util.Set.of("COMPLETED", "ABORTED", "FAILED").contains(states.getFirst()))
            return;
        jdbc.update(
                "update agent_public_reply_stream set status = ?, body = '', next_chunk_index = 0,"
                        + " progress_stage = null, updated_at = ? where generation_id = ?",
                status,
                Timestamp.from(now),
                generationId);
        Long sequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) + 1 from customer_public_event where"
                                + " ticket_id = ? and epoch = ?",
                        Long.class,
                        ticketId,
                        EPOCH);
        appendGenerationEvent(
                ticketId,
                generationId,
                sequence,
                "ABORTED".equals(status) ? "AGENT_REPLY_ABORTED" : "AGENT_REPLY_FAILED",
                "jsonb_build_object('status', '" + status + "')",
                now);
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
                    "insert into customer_public_event (ticket_id, epoch, sequence,"
                            + " agent_generation, event_type, payload, occurred_at) values (?, ?, ?, ?,"
                            + " ?, jsonb_build_object('lifecycleState', 'WAITING_FOR_CUSTOMER',"
                            + " 'clarification', jsonb_build_object('id', ?::text, 'promptCode', ?,"
                            + " 'question', ?)), ?)",
                    ticketId,
                    EPOCH,
                    nextEventSequence,
                    sourceGeneration,
                    transitionType,
                    clarificationId.toString(),
                    promptCode,
                    question,
                    at);
        } else {
            jdbc.update(
                    "insert into customer_public_event (ticket_id, epoch, sequence,"
                            + " agent_generation, event_type, payload, occurred_at) values (?, ?, ?, ?,"
                            + " ?, jsonb_build_object('lifecycleState', 'INVESTIGATING',"
                            + " 'clarification', null), ?)",
                    ticketId,
                    EPOCH,
                    nextEventSequence,
                    sourceGeneration,
                    transitionType,
                    at);
        }
    }

    public void appendHandoffMessage(UUID ticketId, UUID generationId, String body, Instant now) {
        Timestamp at = Timestamp.from(now);
        Long messageSequence =
                jdbc.queryForObject(
                        "select coalesce(max(message_sequence), 0) + 1 from public_message where"
                                + " ticket_id = ?",
                        Long.class,
                        ticketId);
        Long eventSequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) + 1 from customer_public_event where"
                                + " ticket_id = ? and epoch = ?",
                        Long.class,
                        ticketId,
                        EPOCH);
        long sourceGeneration = sourceGeneration(ticketId, generationId);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body,"
                        + " sent_at) values (?, ?, ?, 'SUPPORT', ?, ?)",
                UUID.randomUUID(),
                ticketId,
                messageSequence,
                body,
                at);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, agent_generation,"
                        + " event_type, payload, occurred_at) values (?, ?, ?, ?,"
                        + " 'PUBLIC_MESSAGE_APPENDED', jsonb_build_object('author', 'SUPPORT', 'body',"
                        + " ?, 'sentAt', ?::text), ?), (?, ?, ?, ?, 'TICKET_HANDED_OFF',"
                        + " jsonb_build_object('handlingMode', 'HUMAN', 'clarification', null), ?)",
                ticketId,
                EPOCH,
                eventSequence,
                sourceGeneration,
                body,
                now.toString(),
                at,
                ticketId,
                EPOCH,
                eventSequence + 1,
                sourceGeneration,
                at);
    }

    private long appendMessage(UUID ticketId, String body, Instant now) {
        return appendMessage(ticketId, UUID.randomUUID(), null, "SUPPORT", body, now);
    }

    private long appendMessage(
            UUID ticketId, UUID generationId, String author, String body, Instant now) {
        return appendMessage(ticketId, UUID.randomUUID(), generationId, author, body, now);
    }

    private long appendMessage(
            UUID ticketId,
            UUID publicMessageId,
            UUID generationId,
            String author,
            String body,
            Instant now) {
        return appendMessage(ticketId, publicMessageId, generationId, author, body, now, null);
    }

    private long appendMessage(
            UUID ticketId,
            UUID publicMessageId,
            UUID generationId,
            String author,
            String body,
            Instant now,
            CustomerKnowledgeProjection knowledge) {
        Timestamp at = Timestamp.from(now);
        if ("CUSTOMER".equals(author)) {
            jdbc.update(
                    "update ticket_auto_resolution set status = 'CANCELLED', updated_at = ? "
                            + "where ticket_id = ? and status = 'PENDING'",
                    at,
                    ticketId);
        }
        Long messageSequence =
                jdbc.queryForObject(
                        "select coalesce(max(message_sequence), 0) + 1 from public_message where"
                                + " ticket_id = ?",
                        Long.class,
                        ticketId);
        Long eventSequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) + 1 from customer_public_event where"
                                + " ticket_id = ? and epoch = ?",
                        Long.class,
                        ticketId,
                        EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body,"
                        + " sent_at, knowledge) values (?, ?, ?, ?, ?, ?, ?::jsonb)",
                publicMessageId,
                ticketId,
                messageSequence,
                author,
                body,
                at,
                knowledge == null ? null : json.writeValueAsString(knowledge));
        if (generationId == null) {
            jdbc.update(
                    "insert into customer_public_event (ticket_id, epoch, sequence, event_type,"
                            + " payload, occurred_at) values (?, ?, ?, 'PUBLIC_MESSAGE_APPENDED',"
                            + " jsonb_build_object('author', ?, 'body', ?, 'sentAt', ?::text,"
                            + " 'knowledge', ?::jsonb), ?)",
                    ticketId,
                    EPOCH,
                    eventSequence,
                    author,
                    body,
                    now.toString(),
                    knowledge == null ? null : json.writeValueAsString(knowledge),
                    at);
        } else {
            jdbc.update(
                    "insert into customer_public_event (ticket_id, epoch, sequence,"
                            + " agent_generation, event_type, payload, occurred_at) values (?, ?, ?, ?,"
                            + " 'PUBLIC_MESSAGE_APPENDED', jsonb_build_object('author', ?, 'body', ?,"
                            + " 'sentAt', ?::text, 'knowledge', ?::jsonb), ?)",
                    ticketId,
                    EPOCH,
                    eventSequence,
                    sourceGeneration(ticketId, generationId),
                    author,
                    body,
                    now.toString(),
                    knowledge == null ? null : json.writeValueAsString(knowledge),
                    at);
        }
        return eventSequence + 1;
    }

    public void appendSupportCompensationReview(
            UUID ticketId,
            UUID publicMessageId,
            String body,
            String compensationMethod,
            String amount,
            Instant now) {
        long nextSequence = appendMessage(ticketId, publicMessageId, null, "SUPPORT", body, now);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type,"
                        + " payload, occurred_at) values (?, ?, ?, 'COMPENSATION_REVIEW_PENDING',"
                        + " jsonb_build_object('compensationMethod', ?, 'amount', ?, 'status',"
                        + " 'PENDING_REVIEW'), ?)",
                ticketId,
                EPOCH,
                nextSequence,
                compensationMethod,
                amount,
                Timestamp.from(now));
    }

    private void appendGenerationEvent(
            UUID ticketId,
            UUID generationId,
            long sequence,
            String eventType,
            String payloadExpression,
            Instant now) {
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, agent_generation,"
                        + " event_type, payload, occurred_at) values (?, ?, ?, ?, ?, "
                        + payloadExpression
                        + ", ?)",
                ticketId,
                EPOCH,
                sequence,
                sourceGeneration(ticketId, generationId),
                eventType,
                Timestamp.from(now));
    }

    private void appendTicketTransition(
            UUID ticketId, long sequence, String eventType, String lifecycleState, Instant now) {
        jdbc.update(
                "insert into customer_public_event "
                        + "(ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, ?, jsonb_build_object('lifecycleState', ?), ?)",
                ticketId,
                EPOCH,
                sequence,
                eventType,
                lifecycleState,
                Timestamp.from(now));
    }

    private long sourceGeneration(UUID ticketId, UUID generationId) {
        if (generationId == null) {
            return 0;
        }
        Long generation =
                jdbc.queryForObject(
                        "select generation_number from agent_processing_generation where id = ? and"
                                + " ticket_id = ?",
                        Long.class,
                        generationId,
                        ticketId);
        if (generation == null) {
            throw new IllegalStateException("agent generation does not belong to ticket");
        }
        return generation;
    }

    private record ReplyStreamState(String status, String body) {}
}
