package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.compensation.DelayCompensationPolicy;
import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.sla.SlaService;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
class JdbcAgentInvestigationService implements AgentInvestigationService {
    private static final String EPOCH = "customer-public-v1";
    private static final String PUBLIC_NO_COMPENSATION_CONCLUSION =
            "经核验，本次物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。";
    private static final String PUBLIC_WAITING_APPROVAL =
            "调查已完成，补偿建议正在等待人工审批；审批完成前不会执行补偿。";
    private final JdbcTemplate jdbc;
    private final AgentAccessAudit accessAudit;
    private final Clock clock;
    private final JdbcCompensationProposalStore proposalStore;
    private final SlaService slaService;
    private final DelayCompensationPolicy policy = new DelayCompensationPolicy();

    @Autowired
    JdbcAgentInvestigationService(
            JdbcTemplate jdbc,
            AgentAccessAudit accessAudit,
            Clock clock,
            JdbcCompensationProposalStore proposalStore,
            SlaService slaService) {
        this.jdbc = jdbc;
        this.accessAudit = accessAudit;
        this.clock = clock;
        this.proposalStore = proposalStore;
        this.slaService = slaService;
    }

    @Override
    @Transactional
    public InvestigationFacts facts(UUID ticketId, UUID generationId) {
        List<String> ambiguous = jdbc.query(
                "select t.order_reference from agent_processing_generation g "
                        + "join support_ticket t on t.id = g.ticket_id "
                        + "where g.id = ? and g.ticket_id = ? and g.status = 'ACTIVE' "
                        + "and t.handling_mode = 'AGENT' and t.lifecycle_state = 'INVESTIGATING' "
                        + "and not t.customer_human_preference "
                        + "and (select count(*) from synthetic_order_alias a "
                        + "where a.alias = t.order_reference and a.customer_id = t.customer_id) > 1 "
                        + "for update of g, t",
                (rs, row) -> rs.getString(1), generationId, ticketId);
        if (!ambiguous.isEmpty()) {
            Instant now = clock.instant();
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                            + "values (?, 'AGENT_ORDER_AMBIGUITY_READ', 'agent-machine', ?)",
                    ticketId, Timestamp.from(now));
            return new InvestigationFacts(
                    "AMBIGUOUS", ambiguous.getFirst(), null, null, null, null, null, null, null, null, List.of());
        }
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
            UUID ticketId, UUID generationId, String requestId, InvestigationConclusion conclusion) {
        validateShape(ticketId, conclusion);
        String parameterDigest = StableParameterDigest.sha256(
                Boolean.toString(conclusion.compensationRequired()), conclusion.reasonCode().name(),
                Integer.toString(conclusion.delayHours()), Long.toString(conclusion.delaySeconds()),
                conclusion.orderReference(),
                String.join("\n", conclusion.evidenceRefs()), nullable(conclusion.suggestedMethod()),
                nullable(conclusion.suggestedAmount()));
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                generationId + "\n" + requestId);
        List<CommandRecord> existing = jdbc.query(
                "select r.parameter_digest, g.ticket_id, r.response_payload ->> 'lifecycleState', "
                        + "r.response_payload ->> 'proposalRevisionId', r.response_payload ->> 'proposalRevision', "
                        + "r.response_payload ->> 'proposalStatus' from agent_command_request r "
                        + "join agent_processing_generation g on g.id = r.generation_id "
                        + "where r.generation_id = ? and r.request_id = ?",
                (rs, row) -> new CommandRecord(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getString(3),
                        rs.getString(4), rs.getString(5), rs.getString(6)),
                generationId, requestId);
        if (!existing.isEmpty()) {
            CommandRecord record = existing.getFirst();
            if (!record.ticketId().equals(ticketId)) {
                accessAudit.rejected(ticketId, "OUT_OF_SCOPE_COMMAND_REPLAY");
                throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                        "command identity belongs to another ticket");
            }
            if (!record.parameterDigest().equals(parameterDigest)) {
                accessAudit.rejected(ticketId, "REQUEST_ID_CONFLICT");
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                        "command identity reused with different parameters");
            }
            return record.asAcceptance();
        }

        ScopedOrder order = currentOrder(ticketId, generationId);
        List<String> expectedEvidence = order.evidenceRefs();
        boolean factsMatch = conclusion.delayHours() == order.delayHours()
                && conclusion.delaySeconds() == order.delaySeconds()
                && conclusion.orderReference().equals(order.orderReference())
                && conclusion.evidenceRefs().equals(expectedEvidence);
        if (!factsMatch) reject(ticketId, "DETERMINISTIC_REVIEW_FAILED");

        if (!conclusion.compensationRequired()) {
            return acceptNoCompensation(ticketId, generationId, requestId, parameterDigest, conclusion, order);
        }
        return acceptCompensationProposal(ticketId, generationId, requestId, parameterDigest, conclusion, order);
    }

    private ConclusionAcceptance acceptNoCompensation(
            UUID ticketId, UUID generationId, String requestId, String parameterDigest,
            InvestigationConclusion conclusion, ScopedOrder order) {
        boolean valid = conclusion.reasonCode() == DecisionReasonCode.DELAY_UNDER_24_HOURS
                && order.delaySeconds() < Duration.ofHours(24).toSeconds()
                && eligibleOrderState(order) && order.pendingActionCount() == 0;
        if (!valid) reject(ticketId, "DETERMINISTIC_REVIEW_FAILED");

        Instant now = clock.instant();
        Timestamp databaseTime = Timestamp.from(now);
        slaService.evaluateTicket(ticketId, now);
        int ticketUpdated = jdbc.update(
                "update support_ticket set lifecycle_state = 'RESOLVED', "
                        + "resolution_elapsed_seconds = resolution_elapsed_seconds + "
                        + "case when resolution_running_since is null then 0 else greatest(0, extract(epoch from (?::timestamptz - resolution_running_since))::bigint) end, "
                        + "resolution_running_since = null "
                        + "where id = ? and lifecycle_state = 'INVESTIGATING' and handling_mode = 'AGENT'",
                databaseTime, ticketId);
        if (ticketUpdated != 1) reject(ticketId, "STALE_OR_OUT_OF_SCOPE_GENERATION");
        completeGeneration(generationId, databaseTime);
        appendPublicMessage(ticketId, PUBLIC_NO_COMPENSATION_CONCLUSION, now, databaseTime, true);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values "
                        + "(?, 'AGENT_CONCLUSION_ACCEPTED', 'agent-machine', ?), (?, 'TICKET_RESOLVED', 'spring-system', ?)",
                ticketId, databaseTime, ticketId, databaseTime);
        jdbc.update(
                "insert into agent_command_request (generation_id, request_id, operation, parameter_digest, response_payload, created_at) "
                        + "values (?, ?, 'SUBMIT_INVESTIGATION_CONCLUSION', ?, "
                        + "jsonb_build_object('accepted', true, 'lifecycleState', 'RESOLVED'), ?)",
                generationId, requestId, parameterDigest, databaseTime);
        return new ConclusionAcceptance(true, TicketLifecycleState.RESOLVED, null, null, null);
    }

    private ConclusionAcceptance acceptCompensationProposal(
            UUID ticketId, UUID generationId, String requestId, String parameterDigest,
            InvestigationConclusion conclusion, ScopedOrder order) {
        if (conclusion.reasonCode() != DecisionReasonCode.LOGISTICS_DELAY
                || conclusion.suggestedMethod() == null || conclusion.suggestedAmount() == null
                || !eligibleOrderState(order) || order.existingCompensation()
                || !DelayCompensationPolicy.VERSION.equals(order.policyVersion())) {
            reject(ticketId, "COMPENSATION_PROPOSAL_INELIGIBLE");
        }
        DelayCompensationPolicy.Decision decision =
                policy.evaluate(Duration.ofSeconds(order.delaySeconds()), order.paidAmount());
        if (!decision.eligible()) reject(ticketId, "COMPENSATION_PROPOSAL_INELIGIBLE");
        BigDecimal available = order.availableCompensationAmount().subtract(order.activeReservationAmount());
        if (available.compareTo(decision.amount()) < 0) {
            reject(ticketId, "COMPENSATION_ALLOWANCE_INSUFFICIENT");
        }

        JdbcCompensationProposalStore.StoredProposal proposal;
        try {
            proposal = proposalStore.save(new JdbcCompensationProposalStore.ProposalContent(
                    ticketId, generationId, order.orderReference(), order.delayHours(), order.delaySeconds(),
                    decision.method().name(), decision.amount(), conclusion.evidenceRefs(),
                    order.policyVersion(), order.paidAmount(), available, order.activeReservationAmount(),
                    order.paid(), order.cancelled(), order.fullyRefunded(), order.existingCompensation()));
        } catch (JdbcCompensationProposalStore.ActiveIntentException exception) {
            reject(ticketId, exception.reason());
            throw new IllegalStateException("unreachable");
        }

        Instant now = clock.instant();
        Timestamp databaseTime = Timestamp.from(now);
        completeGeneration(generationId, databaseTime);
        appendPublicMessage(ticketId, PUBLIC_WAITING_APPROVAL, now, databaseTime, false);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values "
                        + "(?, ?, 'spring-system', ?), "
                        + "(?, 'AGENT_GENERATION_COMPLETED', 'spring-system', ?)",
                ticketId,
                proposal.created()
                        ? "COMPENSATION_PROPOSAL_REVISION_CREATED"
                        : "COMPENSATION_PROPOSAL_REVISION_REUSED",
                databaseTime, ticketId, databaseTime);
        jdbc.update(
                "insert into agent_command_request (generation_id, request_id, operation, parameter_digest, response_payload, created_at) "
                        + "values (?, ?, 'SUBMIT_INVESTIGATION_CONCLUSION', ?, "
                        + "jsonb_build_object('accepted', true, 'lifecycleState', 'INVESTIGATING', "
                        + "'proposalRevisionId', ?::text, 'proposalRevision', ?, 'proposalStatus', 'PENDING_APPROVAL'), ?)",
                generationId, requestId, parameterDigest, proposal.revisionId().toString(),
                proposal.revisionNumber(), databaseTime);
        return new ConclusionAcceptance(
                true, TicketLifecycleState.INVESTIGATING, proposal.revisionId(), proposal.revisionNumber(),
                ProposalRevisionStatus.PENDING_APPROVAL);
    }

    private void validateShape(UUID ticketId, InvestigationConclusion conclusion) {
        if (conclusion == null || conclusion.reasonCode() == null || conclusion.orderReference() == null
                || conclusion.evidenceRefs() == null || conclusion.evidenceRefs().size() != 2
                || conclusion.evidenceRefs().stream().anyMatch(Objects::isNull)) {
            accessAudit.rejected(ticketId, "MALFORMED_CONCLUSION");
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                    "malformed investigation conclusion");
        }
    }

    private static boolean eligibleOrderState(ScopedOrder order) {
        return order.paid() && !order.cancelled() && !order.fullyRefunded();
    }

    private void reject(UUID ticketId, String reason) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, ?, 'agent-machine', ?)",
                ticketId, "AGENT_COMMAND_REJECTED_" + reason, Timestamp.from(clock.instant()));
        throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                "Spring deterministic review rejected the conclusion");
    }

    private void completeGeneration(UUID generationId, Timestamp at) {
        int updated = jdbc.update(
                "update agent_processing_generation set status = 'COMPLETED', completed_at = ? where id = ? and status = 'ACTIVE'",
                at, generationId);
        if (updated != 1) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "generation is no longer active");
        jdbc.update("update agent_submission set status = 'COMPLETED' where generation_id = ?", generationId);
        jdbc.update("update agent_resume_request set status = 'COMPLETED' where generation_id = ?", generationId);
    }

    private void appendPublicMessage(
            UUID ticketId, String body, Instant now, Timestamp databaseTime, boolean resolved) {
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) values (?, ?, ?, 'AGENT', ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, body, databaseTime);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', jsonb_build_object('author', 'AGENT', 'body', ?, 'sentAt', ?::text), ?)",
                ticketId, EPOCH, eventSequence, body, now.toString(), databaseTime);
        if (resolved) {
            jdbc.update(
                    "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                            + "values (?, ?, ?, 'TICKET_RESOLVED', jsonb_build_object('lifecycleState', 'RESOLVED'), ?)",
                    ticketId, EPOCH, eventSequence + 1, databaseTime);
        }
    }

    @Override
    public void auditRejected(UUID ticketId, String reason) {
        accessAudit.rejected(ticketId, reason);
    }

    private ScopedOrder currentOrder(UUID ticketId, UUID generationId) {
        List<String> scope = jdbc.query(
                "select o.order_reference from agent_processing_generation g "
                        + "join support_ticket t on t.id = g.ticket_id "
                        + "join synthetic_order o on o.order_reference = t.order_reference "
                        + "and o.customer_id = t.customer_id "
                        + "where g.id = ? and g.ticket_id = ? and g.status = 'ACTIVE' "
                        + "and t.handling_mode = 'AGENT' and t.lifecycle_state = 'INVESTIGATING' "
                        + "for update of g, t",
                (rs, row) -> rs.getString(1),
                generationId, ticketId);
        if (scope.isEmpty()) {
            accessAudit.rejected(ticketId, "STALE_OR_OUT_OF_SCOPE_GENERATION");
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "generation is no longer current for this ticket");
        }
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                rs -> null,
                scope.getFirst() + "\nCOMPENSATION_ALLOWANCE");
        List<ScopedOrder> orders = jdbc.query(
                "select o.order_reference, o.delay_hours, o.delay_seconds, o.paid, o.cancelled, o.fully_refunded, "
                        + "o.existing_compensation, o.policy_version, o.paid_amount, o.available_compensation_amount, "
                        + "(select count(*) from synthetic_pending_action a where a.order_reference = o.order_reference), "
                        + "coalesce((select sum(r.amount) from compensation_reservation r where r.order_reference = o.order_reference and r.status = 'ACTIVE'), 0) "
                        + "from agent_processing_generation g join support_ticket t on t.id = g.ticket_id "
                        + "join synthetic_order o on o.order_reference = t.order_reference and o.customer_id = t.customer_id "
                        + "where g.id = ? and g.ticket_id = ?",
                (rs, row) -> new ScopedOrder(
                        rs.getString(1), rs.getInt(2), rs.getLong(3), rs.getBoolean(4),
                        rs.getBoolean(5), rs.getBoolean(6), rs.getBoolean(7), rs.getString(8),
                        rs.getBigDecimal(9), rs.getBigDecimal(10), rs.getInt(11), rs.getBigDecimal(12)),
                generationId, ticketId);
        return orders.getFirst();
    }

    private void recordFact(UUID generationId, String type, String value, String evidence, Instant now) {
        jdbc.update(
                "insert into investigation_fact (generation_id, fact_type, fact_value, evidence_reference, recorded_at) "
                        + "values (?, ?, ?, ?, ?) on conflict (generation_id, fact_type) do nothing",
                generationId, type, value, evidence, Timestamp.from(now));
    }

    private static String nullable(String value) {
        return value == null ? "" : value;
    }

    private record CommandRecord(
            String parameterDigest, UUID ticketId, String lifecycleState, String proposalRevisionId,
            String proposalRevision, String proposalStatus) {
        ConclusionAcceptance asAcceptance() {
            return new ConclusionAcceptance(
                    true, TicketLifecycleState.valueOf(lifecycleState),
                    proposalRevisionId == null ? null : UUID.fromString(proposalRevisionId),
                    proposalRevision == null ? null : Integer.valueOf(proposalRevision),
                    proposalStatus == null ? null : ProposalRevisionStatus.valueOf(proposalStatus));
        }
    }

    private record ScopedOrder(
            String orderReference, int delayHours, long delaySeconds, boolean paid, boolean cancelled,
            boolean fullyRefunded, boolean existingCompensation, String policyVersion,
            BigDecimal paidAmount, BigDecimal availableCompensationAmount,
            int pendingActionCount, BigDecimal activeReservationAmount) {
        InvestigationFacts asFacts() {
            return new InvestigationFacts(
                    "UNIQUE", orderReference, delayHours, delaySeconds, paid, cancelled, fullyRefunded, existingCompensation,
                    pendingActionCount, policyVersion, evidenceRefs());
        }

        List<String> evidenceRefs() {
            return List.of("order:" + orderReference, "logistics:" + orderReference);
        }
    }
}
