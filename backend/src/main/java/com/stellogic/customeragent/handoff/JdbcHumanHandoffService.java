package com.stellogic.customeragent.handoff;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
class JdbcHumanHandoffService implements HumanHandoffService {
    private static final String CUSTOMER_PUBLIC_EPOCH = "customer-public-v1";
    private static final String CUSTOMER_REQUESTED_REASON = "CUSTOMER_REQUESTED";
    private static final String PUBLIC_MESSAGE = "已按您的要求转由客服继续处理。客服将在此工单中与您联系。";
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TicketAuthorityLock authorityLock;

    JdbcHumanHandoffService(JdbcTemplate jdbc, Clock clock, TicketAuthorityLock authorityLock) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.authorityLock = authorityLock;
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public HumanHandoffResult request(RequestHumanHandoff command) {
        String digest = StableParameterDigest.sha256(command.reasonCode());
        authorityLock.acquire(command.ticketId());
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                command.ticketId() + "\n" + command.requestId());
        List<RequestRecord> existing = jdbc.query(
                "select r.parameter_digest, t.customer_id from customer_human_handoff_request r "
                        + "join support_ticket t on t.id = r.ticket_id where r.ticket_id = ? and r.request_id = ?",
                (rs, row) -> new RequestRecord(rs.getString(1), rs.getString(2)),
                command.ticketId(), command.requestId());
        if (!existing.isEmpty()) {
            RequestRecord record = existing.getFirst();
            if (!record.customerId().equals(command.customerId())) notFound();
            if (!record.parameterDigest().equals(digest)) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "HANDOFF_REQUEST_ID_CONFLICT");
            }
            return new HumanHandoffResult(command.requestId(), "HUMAN", true);
        }
        if (!CUSTOMER_REQUESTED_REASON.equals(command.reasonCode())) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "UNSUPPORTED_HANDOFF_REASON");
        }

        List<TicketScope> scopes = jdbc.query(
                "select lifecycle_state, handling_mode, customer_human_preference from support_ticket "
                        + "where id = ? and customer_id = ? for update",
                (rs, row) -> new TicketScope(rs.getString(1), rs.getString(2), rs.getBoolean(3)),
                command.ticketId(), command.customerId());
        if (scopes.isEmpty()) notFound();
        TicketScope scope = scopes.getFirst();
        if ("CLOSED".equals(scope.lifecycleState())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "TICKET_NOT_CURRENT");
        }

        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        boolean transition = !scope.customerHumanPreference() || !"HUMAN".equals(scope.handlingMode());
        List<UUID> activeGenerations = jdbc.query(
                "select id from agent_processing_generation where ticket_id = ? and status = 'ACTIVE' for update",
                (rs, row) -> rs.getObject(1, UUID.class), command.ticketId());
        UUID handedOffGeneration = activeGenerations.isEmpty() ? null : activeGenerations.getFirst();
        jdbc.update(
                "update support_ticket set customer_human_preference = true, handling_mode = 'HUMAN', "
                        + "human_handoff_reason_code = ? where id = ?",
                CUSTOMER_REQUESTED_REASON, command.ticketId());
        for (UUID generationId : activeGenerations) {
            jdbc.update(
                    "update agent_processing_generation set status = 'HANDED_OFF', completed_at = ? "
                            + "where id = ? and status = 'ACTIVE'",
                    at, generationId);
            jdbc.update("update agent_submission set status = 'COMPLETED' where generation_id = ?", generationId);
            jdbc.update("update agent_resume_request set status = 'COMPLETED' where generation_id = ?", generationId);
        }
        jdbc.update(
                "insert into customer_human_handoff_request "
                        + "(ticket_id, request_id, parameter_digest, reason_code, investigation_summary, completed_at) "
                        + "values (?, ?, ?, ?, jsonb_build_object("
                        + "'generationId', ?::uuid::text, 'facts', coalesce((select jsonb_agg(jsonb_build_object("
                        + "'type', fact_type, 'value', fact_value, 'evidenceReference', evidence_reference) "
                        + "order by fact_type) from investigation_fact where generation_id = ?), '[]'::jsonb)), ?)",
                command.ticketId(), command.requestId(), digest, CUSTOMER_REQUESTED_REASON,
                handedOffGeneration, handedOffGeneration, at);
        int queueInserted = jdbc.update(
                "insert into shared_support_queue_entry (ticket_id, reason_code, entered_at) "
                        + "values (?, 'CUSTOMER_REQUESTED_HANDOFF', ?) on conflict do nothing",
                command.ticketId(), at);
        if (transition) appendPublicTransition(command.ticketId(), now, at);
        audit(command.ticketId(), "CUSTOMER_HUMAN_HANDOFF_REQUEST_RECORDED", command.customerId(), at);
        if (transition) {
            audit(command.ticketId(), "CUSTOMER_HUMAN_PREFERENCE_RECORDED", command.customerId(), at);
        }
        if (!activeGenerations.isEmpty()) {
            audit(command.ticketId(), "AGENT_GENERATION_HANDED_OFF", "spring-system", at);
        }
        if (queueInserted == 1) {
            audit(command.ticketId(), "SHARED_SUPPORT_QUEUE_ENTERED", "spring-system", at);
        }
        return new HumanHandoffResult(command.requestId(), "HUMAN", false);
    }

    @Override
    @Transactional(readOnly = true)
    public HumanHandoffResult status(String customerId, UUID ticketId, String requestId) {
        List<String> matches = jdbc.query(
                "select t.handling_mode from customer_human_handoff_request r "
                        + "join support_ticket t on t.id = r.ticket_id "
                        + "where r.ticket_id = ? and r.request_id = ? and t.customer_id = ?",
                (rs, row) -> rs.getString(1), ticketId, requestId, customerId);
        if (matches.isEmpty()) notFound();
        return new HumanHandoffResult(requestId, matches.getFirst(), true);
    }

    private void appendPublicTransition(UUID ticketId, Instant now, Timestamp at) {
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, CUSTOMER_PUBLIC_EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) "
                        + "values (?, ?, ?, 'SUPPORT', ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, PUBLIC_MESSAGE, at);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', "
                        + "jsonb_build_object('author', 'SUPPORT', 'body', ?, 'sentAt', ?::text), ?), "
                        + "(?, ?, ?, 'TICKET_HANDED_OFF', "
                        + "jsonb_build_object('handlingMode', 'HUMAN', 'clarification', null), ?)",
                ticketId, CUSTOMER_PUBLIC_EPOCH, eventSequence, PUBLIC_MESSAGE, now.toString(), at,
                ticketId, CUSTOMER_PUBLIC_EPOCH, eventSequence + 1, at);
    }

    private void audit(UUID ticketId, String eventType, String actorId, Timestamp at) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, ?, ?, ?)",
                ticketId, eventType, actorId, at);
    }

    private static void notFound() {
        throw new ResponseStatusException(HttpStatus.NOT_FOUND, "human handoff request or ticket not found");
    }

    private record RequestRecord(String parameterDigest, String customerId) {}

    private record TicketScope(String lifecycleState, String handlingMode, boolean customerHumanPreference) {}
}
