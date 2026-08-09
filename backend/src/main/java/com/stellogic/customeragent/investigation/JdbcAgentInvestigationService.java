package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@Service
class JdbcAgentInvestigationService implements AgentInvestigationService {
    private static final String EPOCH = "customer-public-v1";
    private static final String PUBLIC_CONCLUSION =
            "经核验，本次物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。";
    private final JdbcTemplate jdbc;
    private final AgentAccessAudit accessAudit;
    private final Clock clock;

    @Autowired
    JdbcAgentInvestigationService(
            JdbcTemplate jdbc, AgentAccessAudit accessAudit, Clock clock) {
        this.jdbc = jdbc;
        this.accessAudit = accessAudit;
        this.clock = clock;
    }

    @Override
    @Transactional
    public InvestigationFacts facts(UUID ticketId, UUID generationId) {
        ScopedOrder order = currentOrder(ticketId, generationId);
        Instant now = clock.instant();
        recordFact(generationId, "ORDER", order.orderReference(), "order:" + order.orderReference(), now);
        recordFact(generationId, "LOGISTICS_DELAY_HOURS", Integer.toString(order.delayHours()),
                "logistics:" + order.orderReference(), now);
        recordFact(generationId, "PAYMENT", order.paid() ? "PAID" : "UNPAID",
                "payment:" + order.orderReference(), now);
        recordFact(generationId, "POLICY", order.policyVersion(), "policy:" + order.policyVersion(), now);
        recordFact(generationId, "PENDING_ACTION_COUNT", Integer.toString(order.pendingActionCount()),
                "order-actions:" + order.orderReference(), now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, 'AGENT_FACTS_READ', 'agent-machine', ?)",
                ticketId, Timestamp.from(now));
        return order.asFacts();
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public ConclusionAcceptance submit(
            UUID ticketId,
            UUID generationId,
            String requestId,
            InvestigationConclusion conclusion) {
        if (conclusion.reasonCode() == null
                || conclusion.orderReference() == null
                || conclusion.evidenceRefs() == null
                || conclusion.evidenceRefs().stream().anyMatch(java.util.Objects::isNull)) {
            accessAudit.rejected(ticketId, "MALFORMED_CONCLUSION");
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "malformed investigation conclusion");
        }
        String parameterDigest = StableParameterDigest.sha256(
                Boolean.toString(conclusion.compensationRequired()),
                conclusion.reasonCode().name(),
                Integer.toString(conclusion.delayHours()),
                conclusion.orderReference(),
                String.join("\n", conclusion.evidenceRefs()));
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                resultSet -> null,
                generationId + "\n" + requestId);
        List<CommandRecord> existing = jdbc.query(
                "select r.parameter_digest, g.ticket_id from agent_command_request r "
                        + "join agent_processing_generation g on g.id = r.generation_id "
                        + "where r.generation_id = ? and r.request_id = ?",
                (rs, row) -> new CommandRecord(rs.getString(1), rs.getObject(2, UUID.class)),
                generationId, requestId);
        if (!existing.isEmpty()) {
            if (!existing.getFirst().ticketId().equals(ticketId)) {
                accessAudit.rejected(ticketId, "OUT_OF_SCOPE_COMMAND_REPLAY");
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "command identity belongs to another ticket");
            }
            if (!existing.getFirst().parameterDigest().equals(parameterDigest)) {
                accessAudit.rejected(ticketId, "REQUEST_ID_CONFLICT");
                throw new ResponseStatusException(HttpStatus.CONFLICT, "command identity reused with different parameters");
            }
            return new ConclusionAcceptance(true, TicketLifecycleState.RESOLVED);
        }

        ScopedOrder order = currentOrder(ticketId, generationId);
        List<String> expectedEvidence = List.of(
                "order:" + order.orderReference(),
                "logistics:" + order.orderReference());
        boolean valid = !conclusion.compensationRequired()
                && conclusion.reasonCode() == DecisionReasonCode.DELAY_UNDER_24_HOURS
                && conclusion.delayHours() == order.delayHours()
                && conclusion.orderReference().equals(order.orderReference())
                && conclusion.evidenceRefs().equals(expectedEvidence)
                && order.delayHours() < 24
                && order.paid()
                && !order.cancelled()
                && !order.fullyRefunded()
                && !order.existingCompensation()
                && order.pendingActionCount() == 0;
        if (!valid) {
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, 'AGENT_COMMAND_REJECTED_DETERMINISTIC_REVIEW_FAILED', 'agent-machine', ?)",
                    ticketId, Timestamp.from(clock.instant()));
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                    "Spring deterministic review rejected the conclusion");
        }

        Instant now = clock.instant();
        Timestamp databaseTime = Timestamp.from(now);
        jdbc.update(
                "update support_ticket set lifecycle_state = 'RESOLVED' where id = ? and lifecycle_state = 'INVESTIGATING' and handling_mode = 'AGENT'",
                ticketId);
        jdbc.update(
                "update agent_processing_generation set status = 'COMPLETED', completed_at = ? where id = ? and status = 'ACTIVE'",
                databaseTime, generationId);
        jdbc.update(
                "update agent_submission set status = 'COMPLETED' where generation_id = ?",
                generationId);
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) values (?, ?, ?, 'AGENT', ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, PUBLIC_CONCLUSION, databaseTime);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) values (?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', jsonb_build_object('author', 'AGENT', 'body', ?, 'sentAt', ?::text), ?), (?, ?, ?, 'TICKET_RESOLVED', jsonb_build_object('lifecycleState', 'RESOLVED'), ?)",
                ticketId, EPOCH, eventSequence, PUBLIC_CONCLUSION, now.toString(), databaseTime,
                ticketId, EPOCH, eventSequence + 1, databaseTime);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, 'AGENT_CONCLUSION_ACCEPTED', 'agent-machine', ?), (?, 'TICKET_RESOLVED', 'spring-system', ?)",
                ticketId, databaseTime, ticketId, databaseTime);
        jdbc.update(
                "insert into agent_command_request (generation_id, request_id, operation, parameter_digest, response_payload, created_at) values (?, ?, 'SUBMIT_INVESTIGATION_CONCLUSION', ?, ?::jsonb, ?)",
                generationId, requestId, parameterDigest,
                "{\"accepted\":true,\"lifecycleState\":\"RESOLVED\"}", databaseTime);
        return new ConclusionAcceptance(true, TicketLifecycleState.RESOLVED);
    }

    @Override
    public void auditRejected(UUID ticketId, String reason) {
        accessAudit.rejected(ticketId, reason);
    }

    private ScopedOrder currentOrder(UUID ticketId, UUID generationId) {
        List<ScopedOrder> orders = jdbc.query(
                "select o.order_reference, o.delay_hours, o.paid, o.cancelled, o.fully_refunded, o.existing_compensation, o.policy_version, "
                        + "(select count(*) from synthetic_pending_action a where a.order_reference = o.order_reference) "
                        + "from agent_processing_generation g join support_ticket t on t.id = g.ticket_id "
                        + "join synthetic_order o on o.order_reference = t.order_reference and o.customer_id = t.customer_id "
                        + "where g.id = ? and g.ticket_id = ? and g.status = 'ACTIVE' "
                        + "and t.handling_mode = 'AGENT' and t.lifecycle_state = 'INVESTIGATING' "
                        + "for update of g, t",
                (rs, row) -> new ScopedOrder(
                        rs.getString(1), rs.getInt(2), rs.getBoolean(3), rs.getBoolean(4),
                        rs.getBoolean(5), rs.getBoolean(6), rs.getString(7), rs.getInt(8)),
                generationId, ticketId);
        if (orders.isEmpty()) {
            accessAudit.rejected(ticketId, "STALE_OR_OUT_OF_SCOPE_GENERATION");
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "generation is no longer current for this ticket");
        }
        return orders.getFirst();
    }

    private void recordFact(UUID generationId, String type, String value, String evidence, Instant now) {
        jdbc.update(
                "insert into investigation_fact (generation_id, fact_type, fact_value, evidence_reference, recorded_at) values (?, ?, ?, ?, ?) on conflict (generation_id, fact_type) do nothing",
                generationId, type, value, evidence, Timestamp.from(now));
    }

    private record CommandRecord(String parameterDigest, UUID ticketId) {}

    private record ScopedOrder(
            String orderReference,
            int delayHours,
            boolean paid,
            boolean cancelled,
            boolean fullyRefunded,
            boolean existingCompensation,
            String policyVersion,
            int pendingActionCount) {
        InvestigationFacts asFacts() {
            return new InvestigationFacts(
                    orderReference, delayHours, paid, cancelled, fullyRefunded, existingCompensation,
                    pendingActionCount, policyVersion,
                    List.of("order:" + orderReference, "logistics:" + orderReference));
        }
    }
}
