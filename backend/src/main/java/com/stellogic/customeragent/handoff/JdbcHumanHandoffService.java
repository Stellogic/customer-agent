package com.stellogic.customeragent.handoff;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
class JdbcHumanHandoffService implements HumanHandoffService {
    private static final String CUSTOMER_PUBLIC_EPOCH = "customer-public-v1";
    private static final String CUSTOMER_REQUESTED_REASON = "CUSTOMER_REQUESTED";
    private static final String CUSTOMER_PUBLIC_MESSAGE = "已按您的要求转由客服继续处理。客服将在此工单中与您联系。";
    private static final String AGENT_HANDOFF_PUBLIC_MESSAGE = "为确保处理安全，此工单已转由客服继续调查。客服将在此工单中与您联系。";
    private static final String APPROVAL_REJECTION_PUBLIC_MESSAGE =
            "为继续妥善处理，此工单已转由客服跟进。客服将在此工单中与您联系。";
    private static final String INCOMPLETE_INVESTIGATION_CONCLUSION = "INVESTIGATION_COULD_NOT_CONTINUE";
    private static final Set<String> SUMMARY_FACT_TYPES = Set.of(
            "ORDER", "LOGISTICS_DELAY_SECONDS", "PAYMENT", "POLICY", "PENDING_ACTION_COUNT");
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TicketAuthorityLock authorityLock;
    private final ObjectMapper objectMapper;

    JdbcHumanHandoffService(
            JdbcTemplate jdbc, Clock clock, TicketAuthorityLock authorityLock, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.authorityLock = authorityLock;
        this.objectMapper = objectMapper;
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public HumanHandoffResult request(RequestHumanHandoff command) {
        String digest = StableParameterDigest.sha256(command.reasonCode());
        acquireRequestIdentity(command.ticketId(), command.requestId());
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
        List<String> tickets = jdbc.query(
                "select lifecycle_state from support_ticket where id = ? and customer_id = ? for update",
                (rs, row) -> rs.getString(1), command.ticketId(), command.customerId());
        if (tickets.isEmpty()) notFound();
        if ("CLOSED".equals(tickets.getFirst())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "TICKET_NOT_CURRENT");
        }

        HandoffTransition transition = transitionToHuman(
                command.ticketId(), CUSTOMER_REQUESTED_REASON, "CUSTOMER_REQUESTED_HANDOFF",
                CUSTOMER_PUBLIC_MESSAGE, true, command.customerId());
        jdbc.update(
                "insert into customer_human_handoff_request "
                        + "(ticket_id, request_id, parameter_digest, reason_code, investigation_summary, completed_at) "
                        + "values (?, ?, ?, ?, jsonb_build_object("
                        + "'generationId', ?::uuid::text, 'facts', coalesce((select jsonb_agg(jsonb_build_object("
                        + "'type', fact_type, 'value', fact_value, 'evidenceReference', evidence_reference) "
                        + "order by fact_type) from investigation_fact where generation_id = ?), '[]'::jsonb)), ?)",
                command.ticketId(), command.requestId(), digest, CUSTOMER_REQUESTED_REASON,
                transition.generationId(), transition.generationId(), transition.at());
        audit(command.ticketId(), "CUSTOMER_HUMAN_HANDOFF_REQUEST_RECORDED", command.customerId(), transition.at());
        if (transition.publicTransitionRequired()) {
            audit(command.ticketId(), "CUSTOMER_HUMAN_PREFERENCE_RECORDED", command.customerId(), transition.at());
        }
        return new HumanHandoffResult(command.requestId(), "HUMAN", false);
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public AgentHumanHandoffResult requestAgentHumanHandoff(RequestAgentHumanHandoff command) {
        validateAgentHandoffCommand(command);
        String summaryJson = serializeSummary(command.summary());
        String digest = agentHandoffDigest(command);
        acquireRequestIdentity(command.ticketId(), command.requestId());
        List<AgentHandoffRequestRecord> existing = jdbc.query(
                "select parameter_digest, ticket_id, reason_code from agent_human_handoff_request "
                        + "where generation_id = ? and request_id = ?",
                (rs, row) -> new AgentHandoffRequestRecord(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getString(3)),
                command.generationId(), command.requestId());
        if (!existing.isEmpty()) {
            AgentHandoffRequestRecord record = existing.getFirst();
            if (!record.ticketId().equals(command.ticketId())) {
                rejectAgent(command.ticketId(), AgentHandoffRejection.OUT_OF_SCOPE_HANDOFF_REPLAY);
            }
            if (!record.parameterDigest().equals(digest)) {
                rejectAgent(command.ticketId(), AgentHandoffRejection.HANDOFF_REQUEST_ID_CONFLICT);
                throw new ResponseStatusException(HttpStatus.CONFLICT, "HANDOFF_REQUEST_ID_CONFLICT");
            }
            return new AgentHumanHandoffResult(
                    command.requestId(), "HUMAN", record.reasonCode(), true);
        }

        List<Integer> authority = jdbc.query(
                "select 1 from agent_processing_generation g join support_ticket t on t.id = g.ticket_id "
                        + "where g.id = ? and g.ticket_id = ? and g.status = 'ACTIVE' "
                        + "and t.handling_mode = 'AGENT' and t.lifecycle_state <> 'CLOSED' "
                        + "and not t.customer_human_preference for update of g, t",
                (rs, row) -> rs.getInt(1), command.generationId(), command.ticketId());
        if (authority.isEmpty()) {
            rejectAgent(command.ticketId(), AgentHandoffRejection.STALE_OR_OUT_OF_SCOPE_GENERATION);
        }

        validateSummaryEvidence(command);

        HandoffTransition transition = transitionToHuman(
                command.ticketId(), command.reasonCode().name(), "AGENT_HUMAN_HANDOFF",
                AGENT_HANDOFF_PUBLIC_MESSAGE, false, "agent-machine");
        if (!command.generationId().equals(transition.generationId())) {
            rejectAgent(command.ticketId(), AgentHandoffRejection.STALE_OR_OUT_OF_SCOPE_GENERATION);
        }
        jdbc.update(
                "insert into agent_human_handoff_request "
                        + "(generation_id, ticket_id, request_id, parameter_digest, reason_code, investigation_summary, completed_at) "
                        + "values (?, ?, ?, ?, ?, ?::jsonb, ?)",
                command.generationId(), command.ticketId(), command.requestId(), digest,
                command.reasonCode().name(), summaryJson, transition.at());
        audit(command.ticketId(), "AGENT_HUMAN_HANDOFF_REQUEST_RECORDED", "agent-machine", transition.at());
        return new AgentHumanHandoffResult(
                command.requestId(), "HUMAN", command.reasonCode().name(), false);
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

    @Override
    @Transactional
    public void rejectProposal(UUID ticketId, String approverId) {
        authorityLock.acquire(ticketId);
        transitionToHuman(
                ticketId, "APPROVAL_REJECTED", "APPROVAL_REJECTED_HANDOFF",
                APPROVAL_REJECTION_PUBLIC_MESSAGE, false, approverId);
    }

    private HandoffTransition transitionToHuman(
            UUID ticketId,
            String handoffReason,
            String queueReason,
            String publicMessage,
            boolean forceCustomerPreference,
            String actorId) {
        List<TicketScope> scopes = jdbc.query(
                "select lifecycle_state, handling_mode, customer_human_preference from support_ticket "
                        + "where id = ? for update",
                (rs, row) -> new TicketScope(rs.getString(1), rs.getString(2), rs.getBoolean(3)), ticketId);
        if (scopes.isEmpty()) notFound();
        TicketScope scope = scopes.getFirst();
        if ("CLOSED".equals(scope.lifecycleState())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "TICKET_NOT_CURRENT");
        }
        boolean publicTransitionRequired = !"HUMAN".equals(scope.handlingMode())
                || (forceCustomerPreference && !scope.customerHumanPreference());
        Timestamp at = Timestamp.from(clock.instant());
        List<UUID> activeGenerations = jdbc.query(
                "select id from agent_processing_generation where ticket_id = ? and status = 'ACTIVE' for update",
                (rs, row) -> rs.getObject(1, UUID.class), ticketId);
        UUID generationId = activeGenerations.isEmpty() ? null : activeGenerations.getFirst();
        jdbc.update(
                "update support_ticket set customer_human_preference = case when ? then true else customer_human_preference end, "
                        + "handling_mode = 'HUMAN', human_handoff_reason_code = ? where id = ?",
                forceCustomerPreference, handoffReason, ticketId);
        for (UUID activeGeneration : activeGenerations) {
            jdbc.update(
                    "update agent_processing_generation set status = 'HANDED_OFF', completed_at = ? "
                            + "where id = ? and status = 'ACTIVE'",
                    at, activeGeneration);
            jdbc.update("update agent_submission set status = 'COMPLETED' where generation_id = ?", activeGeneration);
            jdbc.update("update agent_resume_request set status = 'COMPLETED' where generation_id = ?", activeGeneration);
        }
        int queueInserted = jdbc.update(
                "insert into shared_support_queue_entry (ticket_id, reason_code, entered_at) "
                        + "values (?, ?, ?) on conflict do nothing",
                ticketId, queueReason, at);
        if (publicTransitionRequired) appendPublicTransition(ticketId, publicMessage, at.toInstant(), at);
        audit(ticketId, "HUMAN_HANDOFF_RECORDED", actorId, at);
        if (!activeGenerations.isEmpty()) audit(ticketId, "AGENT_GENERATION_HANDED_OFF", "spring-system", at);
        if (queueInserted == 1) audit(ticketId, "SHARED_SUPPORT_QUEUE_ENTERED", "spring-system", at);
        return new HandoffTransition(generationId, at, publicTransitionRequired);
    }

    private void validateAgentHandoffCommand(RequestAgentHumanHandoff command) {
        if (command.reasonCode() == null || command.summary() == null
                || !INCOMPLETE_INVESTIGATION_CONCLUSION.equals(command.summary().conclusionCode())
                || command.summary().facts() == null || command.summary().facts().size() > 20) {
            rejectAgent(command.ticketId(), AgentHandoffRejection.INVALID_HANDOFF_SUMMARY);
        }
        for (AgentHumanHandoffFact fact : command.summary().facts()) {
            boolean valid = fact != null && SUMMARY_FACT_TYPES.contains(fact.type())
                    && controlledText(fact.value(), 200) && controlledText(fact.evidenceReference(), 300)
                    && (fact.evidenceReference().startsWith("order:")
                        || fact.evidenceReference().startsWith("logistics:")
                        || fact.evidenceReference().startsWith("payment:")
                        || fact.evidenceReference().startsWith("policy:")
                        || fact.evidenceReference().startsWith("order-actions:"));
            if (!valid) rejectAgent(command.ticketId(), AgentHandoffRejection.INVALID_HANDOFF_SUMMARY);
        }
    }

    private void validateSummaryEvidence(RequestAgentHumanHandoff command) {
        for (AgentHumanHandoffFact fact : command.summary().facts()) {
            Integer matches = jdbc.queryForObject(
                    "select count(*) from investigation_fact where generation_id = ? "
                            + "and fact_type = ? and fact_value = ? and evidence_reference = ?",
                    Integer.class, command.generationId(), fact.type(), fact.value(), fact.evidenceReference());
            if (matches == null || matches != 1) {
                rejectAgent(command.ticketId(), AgentHandoffRejection.INVALID_HANDOFF_SUMMARY);
            }
        }
    }

    private static boolean controlledText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength
                && value.indexOf('\n') < 0 && value.indexOf('\r') < 0;
    }

    private String serializeSummary(AgentHumanHandoffSummary summary) {
        try {
            return objectMapper.writeValueAsString(summary);
        } catch (JacksonException exception) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_HANDOFF_SUMMARY");
        }
    }

    private static String agentHandoffDigest(RequestAgentHumanHandoff command) {
        String[] values = new String[2 + command.summary().facts().size() * 3];
        values[0] = command.reasonCode().name();
        values[1] = command.summary().conclusionCode();
        int offset = 2;
        for (AgentHumanHandoffFact fact : command.summary().facts()) {
            values[offset++] = fact.type();
            values[offset++] = fact.value();
            values[offset++] = fact.evidenceReference();
        }
        return StableParameterDigest.sha256(values);
    }

    private void acquireRequestIdentity(UUID ticketId, String requestId) {
        authorityLock.acquire(ticketId);
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                ticketId + "\n" + requestId);
    }

    private void appendPublicTransition(UUID ticketId, String publicMessage, Instant now, Timestamp at) {
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, CUSTOMER_PUBLIC_EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) "
                        + "values (?, ?, ?, 'SUPPORT', ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, publicMessage, at);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', "
                        + "jsonb_build_object('author', 'SUPPORT', 'body', ?, 'sentAt', ?::text), ?), "
                        + "(?, ?, ?, 'TICKET_HANDED_OFF', "
                        + "jsonb_build_object('handlingMode', 'HUMAN', 'clarification', null), ?)",
                ticketId, CUSTOMER_PUBLIC_EPOCH, eventSequence, publicMessage, now.toString(), at,
                ticketId, CUSTOMER_PUBLIC_EPOCH, eventSequence + 1, at);
    }

    private void audit(UUID ticketId, String eventType, String actorId, Timestamp at) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, ?, ?, ?)",
                ticketId, eventType, actorId, at);
    }

    private void rejectAgent(UUID ticketId, AgentHandoffRejection rejection) {
        auditAgentRejected(ticketId, rejection.name());
        throw new ResponseStatusException(rejection.status(), rejection.name());
    }

    @Override
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void auditAgentRejected(UUID ticketId, String reason) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "select id, ?, 'agent-machine', ? from support_ticket where id = ?",
                "AGENT_COMMAND_REJECTED_" + reason, Timestamp.from(clock.instant()), ticketId);
    }

    private static void notFound() {
        throw new ResponseStatusException(HttpStatus.NOT_FOUND, "human handoff request or ticket not found");
    }

    private record RequestRecord(String parameterDigest, String customerId) {}
    private record AgentHandoffRequestRecord(String parameterDigest, UUID ticketId, String reasonCode) {}
    private record TicketScope(String lifecycleState, String handlingMode, boolean customerHumanPreference) {}
    private record HandoffTransition(UUID generationId, Timestamp at, boolean publicTransitionRequired) {}

    private enum AgentHandoffRejection {
        OUT_OF_SCOPE_HANDOFF_REPLAY(HttpStatus.FORBIDDEN),
        HANDOFF_REQUEST_ID_CONFLICT(HttpStatus.CONFLICT),
        STALE_OR_OUT_OF_SCOPE_GENERATION(HttpStatus.FORBIDDEN),
        INVALID_HANDOFF_SUMMARY(HttpStatus.UNPROCESSABLE_ENTITY);

        private final HttpStatus status;

        AgentHandoffRejection(HttpStatus status) {
            this.status = status;
        }

        HttpStatus status() {
            return status;
        }
    }
}
