package com.stellogic.customeragent.clarification;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.sla.SlaService;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
class JdbcClarificationService implements ClarificationService {
    private static final String EPOCH = "customer-public-v1";
    private static final String PROMPT_CODE = "ORDER_CONFIRMATION_CODE";
    private static final String PUBLIC_QUESTION = "为确认需要调查的订单，请回复订单确认码（A 或 B）。";
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final SlaService slaService;
    private final TicketAuthorityLock authorityLock;

    JdbcClarificationService(
            JdbcTemplate jdbc, Clock clock, SlaService slaService, TicketAuthorityLock authorityLock) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.slaService = slaService;
        this.authorityLock = authorityLock;
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public ClarificationRequestResult create(CreateClarification command) {
        authorityLock.acquire(command.ticketId());
        if (!"ORDER_AMBIGUOUS".equals(command.reasonCode())) {
            reject(command.ticketId(), HttpStatus.UNPROCESSABLE_ENTITY, "UNSUPPORTED_CLARIFICATION_REASON");
        }
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                command.generationId() + "\n" + command.requestId());
        List<ClarificationRequestResult> existing = jdbc.query(
                "select id, prompt_code, public_question from customer_clarification_request "
                        + "where generation_id = ? and request_key = ?",
                (rs, row) -> new ClarificationRequestResult(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3)),
                command.generationId(), command.requestId());
        if (!existing.isEmpty()) {
            if (!hasCurrentAgentAuthority(command.ticketId(), command.generationId())) {
                reject(command.ticketId(), HttpStatus.FORBIDDEN, "STALE_CLARIFICATION_GENERATION");
            }
            return existing.getFirst();
        }

        List<Integer> scopes = jdbc.query(
                "select 1 from agent_processing_generation g "
                        + "join support_ticket t on t.id = g.ticket_id "
                        + "where g.id = ? and g.ticket_id = ? and g.status = 'ACTIVE' "
                        + "and t.lifecycle_state = 'INVESTIGATING' and t.handling_mode = 'AGENT' "
                        + "and not t.customer_human_preference for update of g, t",
                (rs, row) -> rs.getInt(1),
                command.generationId(), command.ticketId());
        if (scopes.isEmpty()) reject(command.ticketId(), HttpStatus.FORBIDDEN, "STALE_CLARIFICATION_GENERATION");
        Integer candidates = jdbc.queryForObject(
                "select count(*) from synthetic_order_alias a join support_ticket t "
                        + "on t.order_reference = a.alias and t.customer_id = a.customer_id where t.id = ?",
                Integer.class, command.ticketId());
        if (candidates == null || candidates < 2) {
            reject(command.ticketId(), HttpStatus.UNPROCESSABLE_ENTITY, "ORDER_NOT_AMBIGUOUS");
        }

        UUID requestId = UUID.randomUUID();
        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        jdbc.update(
                "insert into customer_clarification_request "
                        + "(id, ticket_id, generation_id, request_key, reason_code, prompt_code, public_question, status, created_at) "
                        + "values (?, ?, ?, ?, 'ORDER_AMBIGUOUS', ?, ?, 'OPEN', ?)",
                requestId, command.ticketId(), command.generationId(), command.requestId(), PROMPT_CODE, PUBLIC_QUESTION, at);
        jdbc.update(
                "update support_ticket set lifecycle_state = 'WAITING_FOR_CUSTOMER', "
                        + "resolution_elapsed_seconds = resolution_elapsed_seconds + "
                        + "case when resolution_running_since is null then 0 else greatest(0, extract(epoch from (?::timestamptz - resolution_running_since))::bigint) end, "
                        + "resolution_running_since = null where id = ?",
                at, command.ticketId());
        slaService.evaluateTicket(command.ticketId(), now);
        appendPublicMessage(
                command.ticketId(), command.generationId(), "AGENT", PUBLIC_QUESTION, now,
                "CUSTOMER_CLARIFICATION_REQUESTED", requestId);
        audit(command.ticketId(), "CUSTOMER_CLARIFICATION_REQUESTED", "agent-machine", at);
        return new ClarificationRequestResult(requestId, PROMPT_CODE, PUBLIC_QUESTION);
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public ClarificationReplyResult reply(ReplyToClarification command) {
        authorityLock.acquire(command.ticketId());
        String normalizedAnswer = command.answer().trim().toUpperCase(Locale.ROOT);
        String answerDigest = StableParameterDigest.sha256(normalizedAnswer);
        String parameterDigest = StableParameterDigest.sha256(
                command.ticketId().toString(), command.clarificationRequestId().toString(),
                command.resumeRequestId().toString(), command.customerMessageId(), answerDigest);
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                command.ticketId() + "\nCUSTOMER_CLARIFICATION_REPLY");

        List<ResumeRecord> existing = jdbc.query(
                "select r.parameter_digest, r.customer_message_id, r.status, c.ticket_id, t.customer_id "
                        + "from agent_resume_request r join customer_clarification_request c on c.id = r.clarification_request_id "
                        + "join support_ticket t on t.id = c.ticket_id where r.resume_request_id = ?",
                (rs, row) -> new ResumeRecord(
                        rs.getString(1), rs.getString(2), AgentResumeStatus.valueOf(rs.getString(3)),
                        rs.getObject(4, UUID.class), rs.getString(5)),
                command.resumeRequestId());
        if (!existing.isEmpty()) {
            ResumeRecord record = existing.getFirst();
            if (!record.ticketId().equals(command.ticketId()) || !record.customerId().equals(command.customerId())) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "clarification resume not found");
            }
            if (!record.parameterDigest().equals(parameterDigest)
                    || !record.customerMessageId().equals(command.customerMessageId())) {
                reject(command.ticketId(), HttpStatus.CONFLICT, "RESUME_REQUEST_ID_CONFLICT");
            }
            return new ClarificationReplyResult(command.resumeRequestId(), record.status(), true);
        }
        Integer reusedMessage = jdbc.queryForObject(
                "select count(*) from agent_resume_request where customer_message_id = ?",
                Integer.class, command.customerMessageId());
        if (reusedMessage != null && reusedMessage > 0) {
            reject(command.ticketId(), HttpStatus.CONFLICT, "CUSTOMER_MESSAGE_ID_CONFLICT");
        }

        List<ReplyScope> scopes = jdbc.query(
                "select c.generation_id, g.thread_id, t.order_reference, c.status, t.lifecycle_state, "
                        + "t.handling_mode, t.customer_human_preference, t.customer_id, g.status "
                        + "from customer_clarification_request c "
                        + "join agent_processing_generation g on g.id = c.generation_id "
                        + "join support_ticket t on t.id = c.ticket_id "
                        + "where c.id = ? and c.ticket_id = ? for update of c, g, t",
                (rs, row) -> new ReplyScope(
                        rs.getObject(1, UUID.class), rs.getObject(2, UUID.class), rs.getString(3),
                        rs.getString(4), rs.getString(5), rs.getString(6), rs.getBoolean(7),
                        rs.getString(8), rs.getString(9)),
                command.clarificationRequestId(), command.ticketId());
        if (scopes.isEmpty() || !scopes.getFirst().customerId().equals(command.customerId())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "clarification request not found");
        }
        ReplyScope scope = scopes.getFirst();
        if (!"OPEN".equals(scope.clarificationStatus())
                || !"WAITING_FOR_CUSTOMER".equals(scope.lifecycleState())
                || !"AGENT".equals(scope.handlingMode())
                || scope.customerHumanPreference()
                || !"ACTIVE".equals(scope.generationStatus())) {
            reject(command.ticketId(), HttpStatus.CONFLICT, "STALE_CLARIFICATION_REPLY");
        }
        List<String> matches = jdbc.query(
                "select order_reference from synthetic_order_alias where alias = ? and customer_id = ? and answer_code = ?",
                (rs, row) -> rs.getString(1), scope.orderAlias(), command.customerId(), normalizedAnswer);
        if (matches.size() != 1) {
            reject(command.ticketId(), HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_CLARIFICATION_ANSWER");
        }

        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        String resolvedOrder = matches.getFirst();
        jdbc.update(
                "update customer_clarification_request set status = 'ANSWERED', answer_digest = ?, answer_summary = ?, "
                        + "resolved_order_reference = ?, answered_at = ? where id = ? and status = 'OPEN'",
                answerDigest, normalizedAnswer, resolvedOrder, at, command.clarificationRequestId());
        jdbc.update(
                "update support_ticket set order_reference = ?, lifecycle_state = 'INVESTIGATING', "
                        + "resolution_running_since = ? where id = ?",
                resolvedOrder, at, command.ticketId());
        slaService.evaluateTicket(command.ticketId(), now);
        jdbc.update(
                "insert into agent_resume_request "
                        + "(resume_request_id, customer_message_id, clarification_request_id, generation_id, thread_id, "
                        + "parameter_digest, answer_digest, answer_summary, status, next_attempt_at, created_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)",
                command.resumeRequestId(), command.customerMessageId(), command.clarificationRequestId(),
                scope.generationId(), scope.threadId(), parameterDigest, answerDigest, normalizedAnswer, at, at);
        appendPublicMessage(
                command.ticketId(), scope.generationId(), "CUSTOMER", command.answer().trim(), now,
                "TICKET_INVESTIGATION_RESUMED", null);
        audit(command.ticketId(), "CUSTOMER_CLARIFICATION_ANSWERED", command.customerId(), at);
        audit(command.ticketId(), "AGENT_RESUME_REQUESTED", "spring-system", at);
        return new ClarificationReplyResult(command.resumeRequestId(), AgentResumeStatus.PENDING, false);
    }

    @Override
    @Transactional(readOnly = true)
    public ClarificationReplyResult status(String customerId, UUID ticketId, UUID resumeRequestId) {
        List<AgentResumeStatus> statuses = jdbc.query(
                "select r.status from agent_resume_request r "
                        + "join customer_clarification_request c on c.id = r.clarification_request_id "
                        + "join support_ticket t on t.id = c.ticket_id "
                        + "where r.resume_request_id = ? and c.ticket_id = ? and t.customer_id = ?",
                (rs, row) -> AgentResumeStatus.valueOf(rs.getString(1)), resumeRequestId, ticketId, customerId);
        if (statuses.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "clarification resume not found");
        return new ClarificationReplyResult(resumeRequestId, statuses.getFirst(), true);
    }

    @Override
    public void auditRejected(UUID ticketId, String reason) {
        audit(ticketId, "AGENT_COMMAND_REJECTED_" + reason, "agent-machine", Timestamp.from(clock.instant()));
    }

    private void appendPublicMessage(
            UUID ticketId, UUID generationId, String author, String body, Instant now,
            String transitionType, UUID clarificationId) {
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?", Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, EPOCH);
        Timestamp at = Timestamp.from(now);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) values (?, ?, ?, ?, ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, author, body, at);
        jdbc.update(
                "insert into customer_public_event "
                        + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, (select generation_number from agent_processing_generation "
                        + "where id = ? and ticket_id = ?), 'PUBLIC_MESSAGE_APPENDED', "
                        + "jsonb_build_object('author', ?, 'body', ?, 'sentAt', ?::text), ?)",
                ticketId, EPOCH, eventSequence, generationId, ticketId, author, body, now.toString(), at);
        if (clarificationId != null) {
            jdbc.update(
                    "insert into customer_public_event "
                            + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, (select generation_number from agent_processing_generation "
                            + "where id = ? and ticket_id = ?), ?, "
                            + "jsonb_build_object('lifecycleState', 'WAITING_FOR_CUSTOMER', "
                            + "'clarification', jsonb_build_object('id', ?::text, 'promptCode', ?, 'question', ?)), ?)",
                    ticketId, EPOCH, eventSequence + 1, generationId, ticketId, transitionType,
                    clarificationId.toString(), PROMPT_CODE, PUBLIC_QUESTION, at);
        } else {
            jdbc.update(
                    "insert into customer_public_event "
                            + "(ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, (select generation_number from agent_processing_generation "
                            + "where id = ? and ticket_id = ?), ?, "
                            + "jsonb_build_object('lifecycleState', 'INVESTIGATING', 'clarification', null), ?)",
                    ticketId, EPOCH, eventSequence + 1, generationId, ticketId, transitionType, at);
        }
    }

    private void reject(UUID ticketId, HttpStatus status, String reason) {
        audit(ticketId, "CLARIFICATION_REJECTED_" + reason, "spring-system", Timestamp.from(clock.instant()));
        throw new ResponseStatusException(status, reason);
    }

    private void audit(UUID ticketId, String type, String actor, Timestamp at) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, ?, ?, ?)",
                ticketId, type, actor, at);
    }

    private boolean hasCurrentAgentAuthority(UUID ticketId, UUID generationId) {
        return !jdbc.query(
                "select 1 from agent_processing_generation g join support_ticket t on t.id = g.ticket_id "
                        + "where g.id = ? and g.ticket_id = ? and g.status = 'ACTIVE' "
                        + "and t.handling_mode = 'AGENT' and not t.customer_human_preference",
                (rs, row) -> rs.getInt(1), generationId, ticketId).isEmpty();
    }

    private record ReplyScope(
            UUID generationId, UUID threadId, String orderAlias, String clarificationStatus,
            String lifecycleState, String handlingMode, boolean customerHumanPreference,
            String customerId, String generationStatus) {}

    private record ResumeRecord(
            String parameterDigest, String customerMessageId, AgentResumeStatus status,
            UUID ticketId, String customerId) {}
}
