package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class JdbcCustomerTicketService implements CustomerTicketService {
    private static final String EPOCH = "customer-public-v1";
    private static final Set<String> AGENT_ISSUE_KINDS =
            Set.of("LOGISTICS_DELAY", "PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE");
    private static final String ACKNOWLEDGEMENT = "您的问题已受理，我们会在此公开沟通中更新进展。";
    private static final String UNSUPPORTED_ISSUE_ACKNOWLEDGEMENT = "您的新问题已创建关联客服工单，并转由客服继续处理。";
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TicketAuthorityLock authorityLock;

    @Autowired
    public JdbcCustomerTicketService(
            JdbcTemplate jdbc, Clock clock, TicketAuthorityLock authorityLock) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.authorityLock = authorityLock;
    }

    @Override
    @Transactional
    public TicketCreationResult create(CreateCustomerTicket command) {
        String digest =
                StableParameterDigest.sha256(
                        command.orderReference(), command.description(), command.issueKind());
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                (ResultSetExtractor<Void>) resultSet -> null,
                command.customerId() + "\n" + command.requestId());
        List<RequestRecord> existing =
                jdbc.query(
                        "select parameter_digest, ticket_id from customer_ticket_request where customer_id = ? and request_id = ?",
                        (rs, row) ->
                                new RequestRecord(rs.getString(1), rs.getObject(2, UUID.class)),
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
        boolean agentHandling = AGENT_ISSUE_KINDS.contains(command.issueKind());
        String acknowledgement =
                agentHandling ? ACKNOWLEDGEMENT : UNSUPPORTED_ISSUE_ACKNOWLEDGEMENT;
        boolean startsAgentInvestigation =
                agentHandling
                        && !jdbc.query(
                                        "select 1 from synthetic_order where order_reference = ? and customer_id = ? "
                                                + "union all select 1 from synthetic_order_alias where alias = ? and customer_id = ? limit 1",
                                        (rs, row) -> rs.getInt(1),
                                        command.orderReference(),
                                        command.customerId(),
                                        command.orderReference(),
                                        command.customerId())
                                .isEmpty();
        jdbc.update(
                "insert into support_ticket (id, customer_id, order_reference, description, issue_kind, lifecycle_state, handling_mode, "
                        + "created_at, first_responded_at, resolution_running_since) "
                        + "values (?, ?, ?, ?, ?, 'INVESTIGATING', ?, ?, ?, ?)",
                ticketId,
                command.customerId(),
                command.orderReference(),
                command.description(),
                command.issueKind(),
                agentHandling ? "AGENT" : "HUMAN",
                databaseTime,
                databaseTime,
                databaseTime);
        jdbc.update(
                "insert into customer_ticket_request (customer_id, request_id, parameter_digest, ticket_id) values (?, ?, ?, ?)",
                command.customerId(),
                command.requestId(),
                digest,
                ticketId);
        if (agentHandling) {
            UUID generationId = UUID.randomUUID();
            UUID threadId = UUID.randomUUID();
            jdbc.update(
                    "insert into agent_processing_generation "
                            + "(id, ticket_id, generation_number, thread_id, status, created_at) "
                            + "values (?, ?, 1, ?, 'ACTIVE', ?)",
                    generationId,
                    ticketId,
                    threadId,
                    databaseTime);
            if (startsAgentInvestigation) {
                UUID submissionRequestId = UUID.randomUUID();
                jdbc.update(
                        "insert into agent_submission "
                                + "(submission_request_id, generation_id, thread_id, parameter_digest, status, next_attempt_at, created_at) "
                                + "values (?, ?, ?, ?, 'PENDING', current_timestamp, ?)",
                        submissionRequestId,
                        generationId,
                        threadId,
                        StableParameterDigest.sha256(
                                ticketId.toString(),
                                generationId.toString(),
                                threadId.toString(),
                                submissionRequestId.toString()),
                        databaseTime);
            }
        } else {
            jdbc.update(
                    "update support_ticket set human_handoff_reason_code = 'UNSUPPORTED_SCENARIO' where id = ?",
                    ticketId);
            jdbc.update(
                    "insert into shared_support_queue_entry (ticket_id, reason_code, entered_at) "
                            + "values (?, 'UNSUPPORTED_ISSUE', ?)",
                    ticketId,
                    databaseTime);
        }
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) values (?, ?, 1, 'CUSTOMER', ?, ?), (?, ?, 2, 'SUPPORT', ?, ?)",
                UUID.randomUUID(),
                ticketId,
                command.description(),
                databaseTime,
                UUID.randomUUID(),
                ticketId,
                acknowledgement,
                databaseTime);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, 'TICKET_CREATED', ?, ?), (?, 'FIRST_RESPONSE_RECORDED', 'spring-system', ?)",
                ticketId,
                command.customerId(),
                databaseTime,
                ticketId,
                databaseTime);
        if (agentHandling) {
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                            + "values (?, 'AGENT_GENERATION_CREATED', 'spring-system', ?)",
                    ticketId,
                    databaseTime);
        } else {
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                            + "values (?, 'UNSUPPORTED_ISSUE_ROUTED_TO_HUMAN', 'spring-system', ?)",
                    ticketId,
                    databaseTime);
        }
        jdbc.update(
                "insert into customer_public_event "
                        + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                        + "values (?, ?, 1, ?, 'TICKET_ACCEPTED', "
                        + "jsonb_build_object('ticketId', ?::text, 'lifecycleState', 'INVESTIGATING', 'handlingMode', ?), ?), "
                        + "(?, ?, 2, ?, 'PUBLIC_MESSAGE_APPENDED', "
                        + "jsonb_build_object('author', 'SUPPORT', 'body', ?, 'sentAt', ?::text), ?)",
                ticketId,
                EPOCH,
                agentHandling ? 1 : 0,
                ticketId.toString(),
                agentHandling ? "AGENT" : "HUMAN",
                databaseTime,
                ticketId,
                EPOCH,
                agentHandling ? 1 : 0,
                acknowledgement,
                now.toString(),
                databaseTime);
        return new TicketCreationResult(ticketId, false);
    }

    @Override
    @Transactional
    public CustomerMessageResult appendMessage(AppendCustomerMessage command) {
        String digest =
                StableParameterDigest.sha256(
                        command.ticketId().toString(), command.message().trim());
        authorityLock.acquire(command.ticketId());
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                (ResultSetExtractor<Void>) resultSet -> null,
                command.customerId() + "\n" + command.messageId());
        List<CustomerMessageRequestRecord> existing =
                jdbc.query(
                        "select parameter_digest, outcome from customer_public_message_request "
                                + "where customer_id = ? and message_id = ?",
                        (rs, row) ->
                                new CustomerMessageRequestRecord(rs.getString(1), rs.getString(2)),
                        command.customerId(),
                        command.messageId());
        if (!existing.isEmpty()) {
            CustomerMessageRequestRecord record = existing.getFirst();
            if (!record.digest().equals(digest)) throw new RequestIdentityConflictException();
            return new CustomerMessageResult(command.ticketId(), record.outcome(), true);
        }

        List<AppendableTicket> tickets =
                jdbc.query(
                        "select lifecycle_state, handling_mode, customer_human_preference "
                                + "from support_ticket where id = ? and customer_id = ? for update",
                        (rs, row) ->
                                new AppendableTicket(
                                        rs.getString(1), rs.getString(2), rs.getBoolean(3)),
                        command.ticketId(),
                        command.customerId());
        if (tickets.isEmpty()) throw new TicketNotFoundException();
        AppendableTicket ticket = tickets.getFirst();
        if (!Set.of("NEW", "INVESTIGATING", "WAITING_FOR_CUSTOMER", "WAITING_FOR_EXTERNAL")
                        .contains(ticket.lifecycleState())
                || !"AGENT".equals(ticket.handlingMode())
                || ticket.customerHumanPreference()) {
            throw new CustomerMessageNotAcceptedException();
        }

        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        List<GenerationRecord> active =
                jdbc.query(
                        "select id, generation_number from agent_processing_generation "
                                + "where ticket_id = ? and status = 'ACTIVE' for update",
                        (rs, row) ->
                                new GenerationRecord(rs.getObject(1, UUID.class), rs.getLong(2)),
                        command.ticketId());
        jdbc.update(
                "update ticket_auto_resolution set status = 'CANCELLED', updated_at = ? "
                        + "where ticket_id = ? and status = 'PENDING'",
                at,
                command.ticketId());
        Long nextGeneration =
                jdbc.queryForObject(
                        "select coalesce(max(generation_number), 0) + 1 "
                                + "from agent_processing_generation where ticket_id = ?",
                        Long.class,
                        command.ticketId());
        long newGeneration = nextGeneration == null ? 1 : nextGeneration;
        for (GenerationRecord generation : active) {
            jdbc.update(
                    "update agent_processing_generation set status = 'SUPERSEDED', completed_at = ? "
                            + "where id = ? and status = 'ACTIVE'",
                    at,
                    generation.id());
            jdbc.update(
                    "update agent_submission set status = 'COMPLETED', last_error = null "
                            + "where generation_id = ? and status <> 'COMPLETED'",
                    generation.id());
            jdbc.update(
                    "update agent_resume_request set status = 'COMPLETED' "
                            + "where generation_id = ? and status <> 'COMPLETED'",
                    generation.id());
        }

        UUID generationId = UUID.randomUUID();
        UUID threadId = UUID.randomUUID();
        UUID submissionRequestId = UUID.randomUUID();
        jdbc.update(
                "insert into agent_processing_generation "
                        + "(id, ticket_id, generation_number, thread_id, status, created_at) "
                        + "values (?, ?, ?, ?, 'ACTIVE', ?)",
                generationId,
                command.ticketId(),
                newGeneration,
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
                        command.ticketId().toString(),
                        generationId.toString(),
                        threadId.toString(),
                        submissionRequestId.toString()),
                at,
                at);
        if ("WAITING_FOR_CUSTOMER".equals(ticket.lifecycleState())) {
            jdbc.update(
                    "update support_ticket set lifecycle_state = 'INVESTIGATING', resolution_running_since = ? where id = ?",
                    at,
                    command.ticketId());
        }

        Long messageSequence =
                jdbc.queryForObject(
                        "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                        Long.class,
                        command.ticketId());
        Long eventSequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                        Long.class,
                        command.ticketId(),
                        EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) "
                        + "values (?, ?, ?, 'CUSTOMER', ?, ?)",
                UUID.randomUUID(),
                command.ticketId(),
                messageSequence,
                command.message().trim(),
                at);
        long acceptedGeneration = active.isEmpty() ? newGeneration : active.getFirst().number();
        jdbc.update(
                "insert into customer_public_event "
                        + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) values "
                        + "(?, ?, ?, ?, 'CUSTOMER_MESSAGE_ACCEPTED', "
                        + "jsonb_build_object('author', 'CUSTOMER', 'body', ?, 'sentAt', ?::text), ?)",
                command.ticketId(),
                EPOCH,
                eventSequence,
                acceptedGeneration,
                command.message().trim(),
                now.toString(),
                at);
        long nextEvent = eventSequence + 1;
        if (!active.isEmpty()) {
            jdbc.update(
                    "insert into customer_public_event "
                            + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, ?, 'AGENT_PROCESSING_TERMINATED', "
                            + "jsonb_build_object('reason', 'NEW_CUSTOMER_MESSAGE'), ?)",
                    command.ticketId(),
                    EPOCH,
                    nextEvent++,
                    active.getFirst().number(),
                    at);
        }
        jdbc.update(
                "insert into customer_public_event "
                        + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, ?, 'AGENT_PROCESSING_STARTED', "
                        + "jsonb_build_object('state', 'PROCESSING'), ?)",
                command.ticketId(),
                EPOCH,
                nextEvent,
                newGeneration,
                at);
        jdbc.update(
                "insert into customer_public_message_request "
                        + "(customer_id, message_id, parameter_digest, ticket_id, outcome, received_at) "
                        + "values (?, ?, ?, ?, 'ACCEPTED', ?)",
                command.customerId(),
                command.messageId(),
                digest,
                command.ticketId(),
                at);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, 'CUSTOMER_MESSAGE_ACCEPTED', ?, ?)",
                command.ticketId(),
                command.customerId(),
                at);
        if (!active.isEmpty()) {
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                            + "values (?, 'AGENT_GENERATION_SUPERSEDED', 'spring-system', ?)",
                    command.ticketId(),
                    at);
        }
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, 'AGENT_GENERATION_CREATED', 'spring-system', ?)",
                command.ticketId(),
                at);
        return new CustomerMessageResult(command.ticketId(), "ACCEPTED", false);
    }

    @Override
    @Transactional
    public UUID createFollowUp(
            String customerId,
            String requestId,
            String orderReference,
            String description,
            String issueKind,
            UUID originalTicketId) {
        TicketCreationResult result =
                create(
                        new CreateCustomerTicket(
                                customerId, requestId, orderReference, description, issueKind));
        jdbc.update(
                "update support_ticket set follow_up_of = ? where id = ?",
                originalTicketId,
                result.ticketId());
        return result.ticketId();
    }

    @Override
    @Transactional(readOnly = true)
    public CustomerPublicSnapshot snapshot(String customerId, UUID ticketId) {
        List<CustomerPublicSnapshot> snapshots =
                jdbc.query(
                        "select t.id, t.lifecycle_state, t.handling_mode, t.created_at, t.first_responded_at, "
                                + "coalesce((select max(sequence) from customer_public_event e where e.ticket_id = t.id and e.epoch = ?), 0), "
                                + "coalesce((select max(generation_number) from agent_processing_generation g where g.ticket_id = t.id), 0), "
                                + "a.status, case when a.status = 'PENDING' then a.due_at else null end "
                                + "from support_ticket t left join ticket_auto_resolution a on a.ticket_id = t.id "
                                + "where t.id = ? and t.customer_id = ?",
                        (rs, row) ->
                                new CustomerPublicSnapshot(
                                        rs.getObject(1, UUID.class),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getTimestamp(4).toInstant(),
                                        rs.getTimestamp(5).toInstant(),
                                        EPOCH,
                                        rs.getLong(6),
                                        rs.getLong(7),
                                        List.of(),
                                        null,
                                        null,
                                        rs.getString(8) == null
                                                ? null
                                                : new CurrentAutoResolution(
                                                        rs.getString(8),
                                                        rs.getTimestamp(9) == null
                                                                ? null
                                                                : rs.getTimestamp(9).toInstant())),
                        EPOCH,
                        ticketId,
                        customerId);
        if (snapshots.isEmpty()) throw new TicketNotFoundException();
        List<PublicMessage> messages =
                jdbc.query(
                        "select author, body, sent_at from public_message where ticket_id = ? order by message_sequence",
                        JdbcCustomerTicketService::mapMessage,
                        ticketId);
        CustomerPublicSnapshot ticket = snapshots.getFirst();
        List<CurrentClarification> clarifications =
                jdbc.query(
                        "select id, prompt_code, public_question from customer_clarification_request "
                                + "where ticket_id = ? and status = 'OPEN'",
                        (rs, row) ->
                                new CurrentClarification(
                                        rs.getObject(1, UUID.class),
                                        rs.getString(2),
                                        rs.getString(3)),
                        ticketId);
        List<CurrentReplyStream> replyStreams =
                jdbc.query(
                        "select coalesce(s.status, case when g.status = 'ACTIVE' then 'LOADING' else null end), "
                                + "coalesce(s.body, ''), coalesce(s.progress_stage, 'UNDERSTANDING') "
                                + "from agent_processing_generation g left join agent_public_reply_stream s on s.generation_id = g.id "
                                + "where g.ticket_id = ? order by g.generation_number desc limit 1",
                        (rs, row) ->
                                rs.getString(1) == null
                                        ? null
                                        : new CurrentReplyStream(
                                                rs.getString(1), rs.getString(2), rs.getString(3)),
                        ticketId);
        CurrentReplyStream currentReplyStream =
                replyStreams.isEmpty() ? null : replyStreams.getFirst();
        return new CustomerPublicSnapshot(
                ticket.ticketId(),
                ticket.lifecycleState(),
                ticket.handlingMode(),
                ticket.createdAt(),
                ticket.firstRespondedAt(),
                ticket.epoch(),
                ticket.sequence(),
                ticket.agentGeneration(),
                messages,
                clarifications.isEmpty() ? null : clarifications.getFirst(),
                currentReplyStream,
                ticket.autoResolution());
    }

    @Override
    @Transactional(readOnly = true)
    public List<CustomerPublicEvent> events(String customerId, UUID ticketId, String afterCursor) {
        CustomerPublicSnapshot authority = snapshot(customerId, ticketId);
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
        if (after < 0 || after > authority.sequence()) throw new ProjectionCursorException();
        Long firstRetained =
                jdbc.queryForObject(
                        "select min(sequence) from customer_public_event where ticket_id = ? and epoch = ?",
                        Long.class,
                        ticketId,
                        EPOCH);
        if (after < authority.sequence() && firstRetained != null && firstRetained > after + 1) {
            throw new ProjectionCursorException();
        }
        return jdbc.query(
                "select epoch, sequence, agent_generation, event_type, payload::text from customer_public_event where ticket_id = ? and epoch = ? and sequence > ? order by sequence",
                (rs, row) ->
                        new CustomerPublicEvent(
                                rs.getString(1),
                                rs.getLong(2),
                                rs.getLong(3),
                                rs.getString(4),
                                rs.getString(5)),
                ticketId,
                EPOCH,
                after);
    }

    private static PublicMessage mapMessage(ResultSet rs, int row) throws SQLException {
        return new PublicMessage(rs.getString(1), rs.getString(2), rs.getTimestamp(3).toInstant());
    }

    private record RequestRecord(String digest, UUID ticketId) {}

    private record CustomerMessageRequestRecord(String digest, String outcome) {}

    private record AppendableTicket(
            String lifecycleState, String handlingMode, boolean customerHumanPreference) {}

    private record GenerationRecord(UUID id, long number) {}
}
