package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.compensation.DelayCompensationPolicy;
import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter;
import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
import com.stellogic.customeragent.ticket.CustomerKnowledgeProjection;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

@Service
class JdbcAgentInvestigationService implements AgentInvestigationService {
    private final JdbcTemplate jdbc;
    private final AgentAccessAudit accessAudit;
    private final Clock clock;
    private final JdbcCompensationProposalStore proposalStore;
    private final TicketAuthorityLock authorityLock;
    private final CustomerPublicProjectionAppender publicProjection;
    private final ObjectMapper json;
    private final AgentKnowledgeRetrievalAdapter knowledge;
    private final DelayCompensationPolicy policy = new DelayCompensationPolicy();

    @Autowired
    JdbcAgentInvestigationService(
            JdbcTemplate jdbc,
            AgentAccessAudit accessAudit,
            Clock clock,
            JdbcCompensationProposalStore proposalStore,
            TicketAuthorityLock authorityLock,
            CustomerPublicProjectionAppender publicProjection,
            ObjectMapper json,
            AgentKnowledgeRetrievalAdapter knowledge) {
        this.jdbc = jdbc;
        this.accessAudit = accessAudit;
        this.clock = clock;
        this.proposalStore = proposalStore;
        this.authorityLock = authorityLock;
        this.publicProjection = publicProjection;
        this.json = json;
        this.knowledge = knowledge;
    }

    @Override
    @Transactional
    public InvestigationCapabilityCatalog capabilities(UUID ticketId, UUID generationId) {
        authorityLock.acquire(ticketId);
        requireActiveGeneration(ticketId, generationId);
        return new InvestigationCapabilityCatalog(
                "investigation-capability-catalog-v1",
                java.util.Arrays.stream(InvestigationCapability.values())
                        .map(InvestigationCapability::definition)
                        .toList());
    }

    @Override
    @Transactional
    public AgentKnowledgeResult authorizeKnowledgeSearch(
            UUID ticketId, UUID generationId, String requestId, String query) {
        authorityLock.acquire(ticketId);
        requireActiveGeneration(ticketId, generationId);
        return knowledgeReceipt(generationId, requestId, query);
    }

    @Override
    @Transactional
    public AgentKnowledgeResult acceptKnowledgeSearch(
            UUID ticketId, UUID generationId, String requestId, String query, AgentKnowledgeResult result) {
        authorityLock.acquire(ticketId);
        requireActiveGeneration(ticketId, generationId);
        AgentKnowledgeResult previous = knowledgeReceipt(generationId, requestId, query);
        if (previous != null) {
            if (!previous.equals(result)) {
                throw new ResponseStatusException(
                        HttpStatus.CONFLICT, "knowledge receipt changed during concurrent request");
            }
            return previous;
        }
        jdbc.update(
                "insert into agent_command_request (generation_id,request_id,operation,parameter_digest,response_payload,created_at) "
                        + "values (?,?,'SEARCH_KNOWLEDGE',?,?::jsonb,?)",
                generationId, requestId, knowledgeQueryDigest(query),
                json.writeValueAsString(result), Timestamp.from(clock.instant()));
        return result;
    }

    private AgentKnowledgeResult knowledgeReceipt(UUID generationId, String requestId, String query) {
        return jdbc.query(
                "select operation,parameter_digest,response_payload::text from agent_command_request "
                        + "where generation_id=? and request_id=?",
                (rs, row) -> {
                    if (!"SEARCH_KNOWLEDGE".equals(rs.getString(1))
                            || !knowledgeQueryDigest(query).equals(rs.getString(2))) {
                        throw new ResponseStatusException(HttpStatus.CONFLICT, "knowledge request identity reused");
                    }
                    return json.readValue(rs.getString(3), AgentKnowledgeResult.class);
                }, generationId, requestId).stream().findFirst().orElse(null);
    }

    private static String knowledgeQueryDigest(String query) {
        // 复用现有请求表必需的参数摘要，不另建知识请求身份机制。
        return StableParameterDigest.sha256("SEARCH_KNOWLEDGE", query, "CUSTOMER_PUBLIC");
    }

    @Override
    @Transactional
    public CustomerCommunicationContext customerCommunicationContext(
            UUID ticketId, UUID generationId) {
        requireActiveGeneration(ticketId, generationId);
        List<String> descriptions =
                jdbc.query(
                        "select description from support_ticket where id = ?",
                        (rs, row) -> rs.getString(1),
                        ticketId);
        if (descriptions.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "ticket not found");
        }
        List<CustomerCommunicationMessage> conversation =
                jdbc.query(
                        "select author, body from public_message where ticket_id = ? "
                                + "order by message_sequence",
                        (rs, row) ->
                                new CustomerCommunicationMessage(rs.getString(1), rs.getString(2)),
                        ticketId);
        return new CustomerCommunicationContext(
                "customer-communication-input-v1", descriptions.getFirst(), conversation);
    }

    @Override
    @Transactional(isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    public SiblingTicketSummary siblingTicketSummary(UUID ticketId, UUID generationId) {
        String orderReference = requireActiveGeneration(ticketId, generationId);
        List<SiblingTicketSummaryItem> siblings =
                jdbc.query(
                        "select sibling.issue_kind, sibling.lifecycle_state, "
                                + "case when exists (select 1 from customer_clarification_request c "
                                + "where c.ticket_id = sibling.id and c.status = 'OPEN') then 'CUSTOMER_CLARIFICATION' "
                                + "when sibling.lifecycle_state = 'WAITING_FOR_EXTERNAL' then 'WAITING_FOR_EXTERNAL' else 'NONE' end, "
                                + "exists (select 1 from compensation_proposal_revision p where p.ticket_id = sibling.id) "
                                + "from support_ticket current_ticket join support_ticket sibling "
                                + "on sibling.customer_id = current_ticket.customer_id "
                                + "and sibling.order_reference = current_ticket.order_reference "
                                + "where current_ticket.id = ? and current_ticket.order_reference = ? "
                                + "and (exists (select 1 from synthetic_order owned_order "
                                + "where owned_order.customer_id = current_ticket.customer_id "
                                + "and owned_order.order_reference = current_ticket.order_reference) "
                                + "or (select count(distinct alias.order_reference) from synthetic_order_alias alias "
                                + "where alias.customer_id = current_ticket.customer_id "
                                + "and alias.alias = current_ticket.order_reference) = 1) "
                                + "and sibling.id <> current_ticket.id "
                                + "order by sibling.created_at, sibling.id limit 20",
                        (rs, row) ->
                                new SiblingTicketSummaryItem(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getBoolean(4)),
                        ticketId,
                        orderReference);
        return new SiblingTicketSummary("sibling-ticket-summary-v1", siblings);
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public InvestigationCapabilityResult invoke(
            UUID ticketId,
            UUID generationId,
            String requestId,
            InvestigationCapability capability,
            InvestigationCapabilityParameters parameters) {
        authorityLock.acquire(ticketId);
        String scopedOrderReference = requireActiveGeneration(ticketId, generationId);
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                rs -> null,
                generationId + "\n" + requestId);
        boolean duplicate =
                !jdbc.query(
                                "select 1 from agent_command_request where generation_id = ? and request_id = ?",
                                (rs, row) -> rs.getInt(1),
                                generationId,
                                requestId)
                        .isEmpty();
        if (duplicate) {
            auditRejectedInTransaction(ticketId, "DUPLICATE_CAPABILITY_REQUEST");
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT, "capability request identity was already used");
        }
        InvestigationCapabilityResult result;
        if (capability == InvestigationCapability.CONFIRM_ORDER) {
            result = confirmOrder(ticketId, generationId, scopedOrderReference);
        } else {
            ScopedOrder order = currentOrder(ticketId, scopedOrderReference);
            if (parameters == null
                    || parameters.orderReference() == null
                    || !parameters.orderReference().equals(order.orderReference())) {
                auditRejectedInTransaction(ticketId, "OUT_OF_SCOPE_CAPABILITY_PARAMETERS");
                throw new ResponseStatusException(
                        HttpStatus.FORBIDDEN, "capability parameters are outside the ticket scope");
            }
            Instant now = clock.instant();
            result =
                    switch (capability) {
                        case READ_LOGISTICS -> logistics(generationId, order, now);
                        case READ_PAYMENT_AND_REFUNDS ->
                                paymentAndRefunds(generationId, order, now);
                        case READ_COMPENSATION_AND_PENDING_ACTIONS ->
                                compensationAndActions(generationId, order, now);
                        case READ_APPLICABLE_POLICY -> policy(generationId, order, now);
                        case READ_ORDER_RULES -> orderRules(generationId, order, now);
                        case CONFIRM_ORDER -> throw new IllegalStateException("handled above");
                    };
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, ?, 'agent-machine', ?)",
                    ticketId,
                    "AGENT_CAPABILITY_USED_" + capability.name(),
                    Timestamp.from(now));
        }
        Instant completedAt = clock.instant();
        String parameterDigest =
                StableParameterDigest.sha256(
                        capability.name(),
                        parameters == null || parameters.orderReference() == null
                                ? ""
                                : parameters.orderReference());
        jdbc.update(
                "insert into agent_command_request (generation_id, request_id, operation, parameter_digest, response_payload, created_at) "
                        + "values (?, ?, 'USE_INVESTIGATION_CAPABILITY', ?, jsonb_build_object('capability', ?), ?)",
                generationId,
                requestId,
                parameterDigest,
                capability.name(),
                Timestamp.from(completedAt));
        return result;
    }

    private InvestigationCapabilityResult confirmOrder(
            UUID ticketId, UUID generationId, String scopedOrderReference) {
        List<String> ambiguous =
                jdbc.query(
                        "select t.order_reference from support_ticket t where t.id = ? "
                                + "and t.order_reference = ? and (select count(*) from synthetic_order_alias a "
                                + "where a.alias = t.order_reference and a.customer_id = t.customer_id) > 1 "
                                + "for update of t",
                        (rs, row) -> rs.getString(1),
                        ticketId,
                        scopedOrderReference);
        if (!ambiguous.isEmpty()) {
            Instant now = clock.instant();
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                            + "values (?, 'AGENT_ORDER_AMBIGUITY_READ', 'agent-machine', ?)",
                    ticketId,
                    Timestamp.from(now));
            return new OrderConfirmationResult(
                    InvestigationCapability.CONFIRM_ORDER,
                    "AMBIGUOUS",
                    ambiguous.getFirst(),
                    List.of());
        }
        ScopedOrder order = currentOrder(ticketId, scopedOrderReference);
        Instant now = clock.instant();
        recordFact(
                generationId,
                "ORDER",
                order.orderReference(),
                "order:" + order.orderReference(),
                now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, 'AGENT_CAPABILITY_USED_CONFIRM_ORDER', 'agent-machine', ?)",
                ticketId,
                Timestamp.from(now));
        return new OrderConfirmationResult(
                InvestigationCapability.CONFIRM_ORDER,
                "UNIQUE",
                order.orderReference(),
                List.of("order:" + order.orderReference()));
    }

    private LogisticsFactsResult logistics(UUID generationId, ScopedOrder order, Instant now) {
        String evidence = "logistics:" + order.orderReference();
        recordFact(
                generationId,
                "LOGISTICS_DELAY_HOURS",
                Integer.toString(order.delayHours()),
                evidence,
                now);
        recordFact(
                generationId,
                "LOGISTICS_DELAY_SECONDS",
                Long.toString(order.delaySeconds()),
                evidence,
                now);
        recordFact(generationId, "LOGISTICS_STATUS", order.logisticsStatus(), evidence, now);
        return new LogisticsFactsResult(
                InvestigationCapability.READ_LOGISTICS,
                order.delayHours(),
                order.delaySeconds(),
                order.logisticsStatus(),
                List.of(evidence));
    }

    private PaymentRefundFactsResult paymentAndRefunds(
            UUID generationId, ScopedOrder order, Instant now) {
        String evidence = "payment:" + order.orderReference();
        recordFact(generationId, "PAYMENT", order.paid() ? "PAID" : "UNPAID", evidence, now);
        recordFact(
                generationId,
                "ORDER_CANCELLATION",
                order.cancelled() ? "CANCELLED" : "NOT_CANCELLED",
                evidence,
                now);
        recordFact(
                generationId,
                "REFUND_STATUS",
                order.fullyRefunded() ? "FULLY_REFUNDED" : "NOT_FULLY_REFUNDED",
                evidence,
                now);
        recordFact(
                generationId,
                "DUPLICATE_CHARGE_SUSPECTED",
                Boolean.toString(order.duplicateChargeSuspected()),
                evidence,
                now);
        return new PaymentRefundFactsResult(
                InvestigationCapability.READ_PAYMENT_AND_REFUNDS,
                order.paid(),
                order.cancelled(),
                order.fullyRefunded(),
                order.duplicateChargeSuspected(),
                List.of(evidence));
    }

    private CompensationActionsFactsResult compensationAndActions(
            UUID generationId, ScopedOrder order, Instant now) {
        String compensationEvidence = "compensation:" + order.orderReference();
        String actionsEvidence = "order-actions:" + order.orderReference();
        recordFact(
                generationId,
                "EXISTING_COMPENSATION",
                Boolean.toString(order.existingCompensation()),
                compensationEvidence,
                now);
        recordFact(
                generationId,
                "PENDING_ACTION_COUNT",
                Integer.toString(order.pendingActionCount()),
                actionsEvidence,
                now);
        return new CompensationActionsFactsResult(
                InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS,
                order.existingCompensation(),
                order.pendingActionCount(),
                List.of(compensationEvidence, actionsEvidence));
    }

    private ApplicablePolicyResult policy(UUID generationId, ScopedOrder order, Instant now) {
        String evidence = "policy:" + order.policyVersion();
        recordFact(generationId, "POLICY", order.policyVersion(), evidence, now);
        return new ApplicablePolicyResult(
                InvestigationCapability.READ_APPLICABLE_POLICY,
                order.policyVersion(),
                List.of(evidence));
    }

    private OrderRuleFactsResult orderRules(UUID generationId, ScopedOrder order, Instant now) {
        String evidence = "order-rule:" + order.orderReference();
        recordFact(generationId, "ORDER_RULE", order.orderRuleSummary(), evidence, now);
        return new OrderRuleFactsResult(
                InvestigationCapability.READ_ORDER_RULES,
                order.orderRuleSummary(),
                List.of(evidence));
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public ConclusionAcceptance submit(
            UUID ticketId,
            UUID generationId,
            String requestId,
            InvestigationConclusion conclusion) {
        authorityLock.acquire(ticketId);
        validateShape(ticketId, conclusion);
        String parameterDigest =
                StableParameterDigest.sha256(
                        Boolean.toString(conclusion.compensationRequired()),
                        conclusion.reasonCode().name(),
                        Integer.toString(conclusion.delayHours()),
                        Long.toString(conclusion.delaySeconds()),
                        conclusion.orderReference(),
                        String.join("\n", conclusion.evidenceRefs()),
                        conclusion.sufficiency().riskScenario().name(),
                        conclusion.sufficiency().policyVersion(),
                        evidenceDigest(conclusion.sufficiency().evidence()),
                        replyDigest(conclusion.customerReply()));
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                rs -> null,
                generationId + "\n" + requestId);
        List<CommandRecord> existing =
                jdbc.query(
                        "select r.parameter_digest, g.ticket_id, r.response_payload ->> 'lifecycleState', "
                                + "r.response_payload ->> 'proposalRevisionId', r.response_payload ->> 'proposalRevision', "
                                + "r.response_payload ->> 'proposalStatus' from agent_command_request r "
                                + "join agent_processing_generation g on g.id = r.generation_id "
                                + "where r.generation_id = ? and r.request_id = ?",
                        (rs, row) ->
                                new CommandRecord(
                                        rs.getString(1),
                                        rs.getObject(2, UUID.class),
                                        rs.getString(3),
                                        rs.getString(4),
                                        rs.getString(5),
                                        rs.getString(6)),
                        generationId,
                        requestId);
        if (!existing.isEmpty()) {
            CommandRecord record = existing.getFirst();
            if (!record.ticketId().equals(ticketId)) {
                accessAudit.rejected(ticketId, "OUT_OF_SCOPE_COMMAND_REPLAY");
                throw new ResponseStatusException(
                        HttpStatus.FORBIDDEN, "command identity belongs to another ticket");
            }
            if (!record.parameterDigest().equals(parameterDigest)) {
                accessAudit.rejected(ticketId, "REQUEST_ID_CONFLICT");
                throw new ResponseStatusException(
                        HttpStatus.CONFLICT, "command identity reused with different parameters");
            }
            if (!mayReplayCompletedCommand(ticketId, generationId)) {
                accessAudit.rejected(ticketId, "STALE_OR_OUT_OF_SCOPE_GENERATION");
                throw new ResponseStatusException(
                        HttpStatus.FORBIDDEN,
                        "generation is no longer authorized for command replay");
            }
            return record.asAcceptance();
        }

        ScopedOrder order = currentOrder(ticketId, generationId);
        List<PersistedInvestigationFact> persistedFacts = persistedFacts(ticketId, generationId);
        String evidenceFailure =
                EvidenceSufficiencyPolicy.validate(conclusion, persistedFacts, clock.instant());
        if (evidenceFailure != null) reject(ticketId, evidenceFailure);
        if (!factsStillMatchCurrentOrder(persistedFacts, order)) {
            reject(ticketId, "EVIDENCE_STALE");
        }
        List<String> expectedEvidence = order.evidenceRefs();
        boolean factsMatch =
                conclusion.delayHours() == order.delayHours()
                        && conclusion.delaySeconds() == order.delaySeconds()
                        && conclusion.orderReference().equals(order.orderReference())
                        && conclusion.evidenceRefs().equals(expectedEvidence);
        if (!factsMatch) reject(ticketId, "DETERMINISTIC_REVIEW_FAILED");
        validateCustomerReply(ticketId, conclusion, order);
        CustomerKnowledgeProjection knowledgeProjection = validateKnowledgeReply(generationId, conclusion.customerReply());

        if (!conclusion.compensationRequired()) {
            if (requiresHumanAfterGroundedReply(conclusion.reasonCode())) {
                return acceptGroundedReplyThenHandoff(
                        ticketId, generationId, requestId, parameterDigest, conclusion, knowledgeProjection);
            }
            return acceptNoCompensation(
                    ticketId, generationId, requestId, parameterDigest, conclusion, order, knowledgeProjection);
        }
        return acceptCompensationProposal(
                ticketId, generationId, requestId, parameterDigest, conclusion, order, knowledgeProjection);
    }

    private static boolean requiresHumanAfterGroundedReply(DecisionReasonCode reasonCode) {
        return reasonCode == DecisionReasonCode.LOGISTICS_STALLED
                || reasonCode == DecisionReasonCode.PACKAGE_SIGNED_NOT_RECEIVED
                || reasonCode == DecisionReasonCode.PACKAGE_SUSPECTED_LOST
                || reasonCode == DecisionReasonCode.DUPLICATE_CHARGE
                || reasonCode == DecisionReasonCode.OTHER_REQUIRES_HUMAN
                || reasonCode == DecisionReasonCode.FACTS_INSUFFICIENT;
    }

    private ConclusionAcceptance acceptGroundedReplyThenHandoff(
            UUID ticketId,
            UUID generationId,
            String requestId,
            String parameterDigest,
            InvestigationConclusion conclusion,
            CustomerKnowledgeProjection knowledgeProjection) {
        Instant now = clock.instant();
        Timestamp databaseTime = Timestamp.from(now);
        completeGeneration(generationId, databaseTime);
        publishCustomerReply(ticketId, generationId, conclusion.customerReply(), knowledgeProjection, now);
        int updated =
                jdbc.update(
                        "update support_ticket set handling_mode = 'HUMAN', human_handoff_reason_code = ? "
                                + "where id = ? and handling_mode = 'AGENT' and lifecycle_state = 'INVESTIGATING'",
                        conclusion.reasonCode().name(),
                        ticketId);
        if (updated != 1) reject(ticketId, "STALE_OR_OUT_OF_SCOPE_GENERATION");
        publicProjection.appendHandoffMessage(
                ticketId, generationId, "本次核验结论已给出，此工单已转由客服继续处理。", now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values "
                        + "(?, 'AGENT_CONCLUSION_ACCEPTED', 'agent-machine', ?), "
                        + "(?, 'HUMAN_HANDOFF_RECORDED', 'spring-system', ?)",
                ticketId,
                databaseTime,
                ticketId,
                databaseTime);
        jdbc.update(
                "insert into agent_command_request (generation_id, request_id, operation, parameter_digest, response_payload, created_at) "
                        + "values (?, ?, 'SUBMIT_INVESTIGATION_CONCLUSION', ?, "
                        + "jsonb_build_object('accepted', true, 'lifecycleState', 'INVESTIGATING'), ?)",
                generationId,
                requestId,
                parameterDigest,
                databaseTime);
        return new ConclusionAcceptance(true, TicketLifecycleState.INVESTIGATING, null, null, null);
    }

    private ConclusionAcceptance acceptNoCompensation(
            UUID ticketId,
            UUID generationId,
            String requestId,
            String parameterDigest,
            InvestigationConclusion conclusion,
            ScopedOrder order,
            CustomerKnowledgeProjection knowledgeProjection) {
        Instant now = clock.instant();
        String scenario = autoResolutionScenario(ticketId, conclusion, order);
        if (scenario == null) {
            return acceptGroundedReplyThenHandoff(
                    ticketId, generationId, requestId, parameterDigest, conclusion, knowledgeProjection);
        }
        Timestamp databaseTime = Timestamp.from(now);
        completeGeneration(generationId, databaseTime);
        publishCustomerReply(ticketId, generationId, conclusion.customerReply(), knowledgeProjection, now);
        if (conclusion.customerReply().knowledge() != null
                && conclusion.customerReply().knowledge().status() != CustomerKnowledgeStatus.SUPPORTED) {
            jdbc.update("insert into audit_event (ticket_id,event_type,actor_id,occurred_at) "
                    + "values (?,'AGENT_CONCLUSION_ACCEPTED','agent-machine',?)", ticketId, databaseTime);
            jdbc.update("insert into agent_command_request "
                    + "(generation_id,request_id,operation,parameter_digest,response_payload,created_at) "
                    + "values (?,?,'SUBMIT_INVESTIGATION_CONCLUSION',?, "
                    + "jsonb_build_object('accepted',true,'lifecycleState','INVESTIGATING'),?)",
                    generationId, requestId, parameterDigest, databaseTime);
            return new ConclusionAcceptance(true, TicketLifecycleState.INVESTIGATING, null, null, null);
        }
        Instant candidateCreatedAt = clock.instant();
        jdbc.update(
                "insert into ticket_auto_resolution (ticket_id, generation_id, policy_version, scenario, conclusion, "
                        + "reply_message_id, customer_message_sequence, status, due_at, created_at, updated_at) "
                        + "values (?, ?, ?, ?, ?::jsonb, "
                        + "(select id from public_message where ticket_id = ? and author = 'AGENT' order by message_sequence desc limit 1), "
                        + "(select coalesce(max(message_sequence), 0) from public_message where ticket_id = ? and author = 'CUSTOMER'), "
                        + "'PENDING', ?, ?, ?) on conflict (ticket_id) do update set "
                        + "generation_id = excluded.generation_id, policy_version = excluded.policy_version, scenario = excluded.scenario, "
                        + "conclusion = excluded.conclusion, reply_message_id = excluded.reply_message_id, "
                        + "customer_message_sequence = excluded.customer_message_sequence, status = 'PENDING', "
                        + "due_at = excluded.due_at, created_at = excluded.created_at, updated_at = excluded.updated_at",
                ticketId,
                generationId,
                AutoResolutionPolicy.VERSION,
                scenario,
                json.writeValueAsString(conclusion),
                ticketId,
                ticketId,
                Timestamp.from(candidateCreatedAt.plus(AutoResolutionPolicy.WAIT)),
                Timestamp.from(candidateCreatedAt),
                Timestamp.from(candidateCreatedAt));
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values "
                        + "(?, 'AGENT_CONCLUSION_ACCEPTED', 'agent-machine', ?), (?, 'AUTO_RESOLUTION_CANDIDATE_CREATED', 'spring-system', ?)",
                ticketId,
                databaseTime,
                ticketId,
                databaseTime);
        jdbc.update(
                "insert into agent_command_request (generation_id, request_id, operation, parameter_digest, response_payload, created_at) "
                        + "values (?, ?, 'SUBMIT_INVESTIGATION_CONCLUSION', ?, "
                        + "jsonb_build_object('accepted', true, 'lifecycleState', 'INVESTIGATING'), ?)",
                generationId,
                requestId,
                parameterDigest,
                databaseTime);
        return new ConclusionAcceptance(true, TicketLifecycleState.INVESTIGATING, null, null, null);
    }

    String revalidateAutoResolution(
            UUID ticketId, UUID generationId, InvestigationConclusion conclusion) {
        ScopedOrder order;
        try {
            order = currentOrder(ticketId, conclusion.orderReference());
        } catch (ResponseStatusException exception) {
            if (exception.getStatusCode() == HttpStatus.FORBIDDEN) return null;
            throw exception;
        }
        List<PersistedInvestigationFact> facts = persistedFacts(ticketId, generationId);
        if (EvidenceSufficiencyPolicy.validate(conclusion, facts, clock.instant()) != null
                || !factsStillMatchCurrentOrder(facts, order)
                || CustomerReplySafetyPolicy.rejectionReason(
                                conclusion, order.orderReference(), order.evidenceRefs())
                        != null) return null;
        return autoResolutionScenario(ticketId, conclusion, order);
    }

    private String autoResolutionScenario(
            UUID ticketId, InvestigationConclusion conclusion, ScopedOrder order) {
        Boolean hasProposal =
                jdbc.queryForObject(
                        "select exists(select 1 from compensation_proposal_revision where ticket_id = ? and status in ('PENDING_APPROVAL', 'APPROVED')) "
                                + "or exists(select 1 from customer_clarification_request where ticket_id = ? and status = 'OPEN')",
                        Boolean.class,
                        ticketId,
                        ticketId);
        if (Boolean.TRUE.equals(hasProposal)) return null;
        return jdbc.queryForObject(
                "select issue_kind, description || E'\\n' || coalesce((select string_agg(body, E'\\n' order by message_sequence) "
                        + "from public_message m where m.ticket_id = t.id and m.author = 'CUSTOMER' "
                        + "and not exists(select 1 from customer_clarification_request c where c.ticket_id = t.id "
                        + "and c.status = 'ANSWERED' and c.answered_at = m.sent_at and c.answer_summary = trim(m.body))), '') "
                        + "from support_ticket t where id = ?",
                (rs, row) ->
                        AutoResolutionPolicy.scenario(
                                conclusion, order, rs.getString(1), rs.getString(2)),
                ticketId);
    }

    private ConclusionAcceptance acceptCompensationProposal(
            UUID ticketId,
            UUID generationId,
            String requestId,
            String parameterDigest,
            InvestigationConclusion conclusion,
            ScopedOrder order,
            CustomerKnowledgeProjection knowledgeProjection) {
        if (conclusion.reasonCode() != DecisionReasonCode.LOGISTICS_DELAY
                || !eligibleOrderState(order)
                || order.existingCompensation()
                || order.pendingActionCount() != 0
                || !DelayCompensationPolicy.VERSION.equals(order.policyVersion())) {
            reject(ticketId, "COMPENSATION_PROPOSAL_INELIGIBLE");
        }
        DelayCompensationPolicy.Decision decision =
                policy.evaluate(Duration.ofSeconds(order.delaySeconds()), order.paidAmount());
        if (!decision.eligible()) reject(ticketId, "COMPENSATION_PROPOSAL_INELIGIBLE");
        BigDecimal remainingAvailable =
                order.totalAvailableCompensationAmount().subtract(order.activeReservationAmount());
        if (remainingAvailable.compareTo(decision.amount()) < 0) {
            reject(ticketId, "COMPENSATION_ALLOWANCE_INSUFFICIENT");
        }

        JdbcCompensationProposalStore.StoredProposal proposal;
        try {
            proposal =
                    proposalStore.save(
                            new JdbcCompensationProposalStore.ProposalContent(
                                    ticketId,
                                    generationId,
                                    order.orderReference(),
                                    order.delayHours(),
                                    order.delaySeconds(),
                                    decision.method().name(),
                                    decision.amount(),
                                    conclusion.evidenceRefs(),
                                    order.policyVersion(),
                                    order.paidAmount(),
                                    order.totalAvailableCompensationAmount(),
                                    order.activeReservationAmount(),
                                    remainingAvailable,
                                    order.paid(),
                                    order.cancelled(),
                                    order.fullyRefunded(),
                                    order.existingCompensation()));
        } catch (JdbcCompensationProposalStore.ActiveIntentException exception) {
            reject(ticketId, exception.reason());
            throw new IllegalStateException("unreachable");
        }

        Instant now = clock.instant();
        Timestamp databaseTime = Timestamp.from(now);
        completeGeneration(generationId, databaseTime);
        publishCustomerReply(ticketId, generationId, conclusion.customerReply(), knowledgeProjection, now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) values "
                        + "(?, ?, 'spring-system', ?, 'COMPENSATION_PROPOSAL_REVISION', ?), "
                        + "(?, 'AGENT_GENERATION_COMPLETED', 'spring-system', ?, null, null)",
                ticketId,
                proposal.created()
                        ? "COMPENSATION_PROPOSAL_REVISION_CREATED"
                        : "COMPENSATION_PROPOSAL_REVISION_REUSED",
                databaseTime,
                proposal.revisionId(),
                ticketId,
                databaseTime);
        jdbc.update(
                "insert into agent_command_request (generation_id, request_id, operation, parameter_digest, response_payload, created_at) "
                        + "values (?, ?, 'SUBMIT_INVESTIGATION_CONCLUSION', ?, "
                        + "jsonb_build_object('accepted', true, 'lifecycleState', 'INVESTIGATING', "
                        + "'proposalRevisionId', ?::text, 'proposalRevision', ?, 'proposalStatus', 'PENDING_APPROVAL'), ?)",
                generationId,
                requestId,
                parameterDigest,
                proposal.revisionId().toString(),
                proposal.revisionNumber(),
                databaseTime);
        return new ConclusionAcceptance(
                true,
                TicketLifecycleState.INVESTIGATING,
                proposal.revisionId(),
                proposal.revisionNumber(),
                ProposalRevisionStatus.PENDING_APPROVAL);
    }

    private void validateShape(UUID ticketId, InvestigationConclusion conclusion) {
        if (conclusion == null
                || conclusion.reasonCode() == null
                || conclusion.orderReference() == null
                || conclusion.evidenceRefs() == null
                || conclusion.evidenceRefs().size() != 2
                || conclusion.evidenceRefs().stream().anyMatch(Objects::isNull)
                || conclusion.sufficiency() == null
                || conclusion.sufficiency().riskScenario() == null
                || conclusion.sufficiency().policyVersion() == null
                || conclusion.sufficiency().evidence() == null
                || conclusion.customerReply() == null
                || conclusion.customerReply().schemaVersion() == null
                || conclusion.customerReply().body() == null
                || conclusion.customerReply().intent() == null
                || conclusion.customerReply().evidenceRefs() == null
                || conclusion.customerReply().evidenceRefs().size() != 2
                || conclusion.customerReply().evidenceRefs().stream().anyMatch(Objects::isNull)
                || conclusion.customerReply().referencedOrder() == null
                || (conclusion.customerReply().knowledge() != null
                    && (conclusion.customerReply().knowledgeRequestId() == null
                        || conclusion.customerReply().knowledgeRequestId().isBlank()))) {
            accessAudit.rejected(ticketId, "MALFORMED_CONCLUSION");
            throw new ResponseStatusException(
                    HttpStatus.UNPROCESSABLE_ENTITY, "malformed investigation conclusion");
        }
    }

    private void validateCustomerReply(
            UUID ticketId, InvestigationConclusion conclusion, ScopedOrder order) {
        String rejection =
                CustomerReplySafetyPolicy.rejectionReason(
                        conclusion, order.orderReference(), order.evidenceRefs());
        if (rejection != null) reject(ticketId, rejection);
    }

    private String replyDigest(CustomerReplyEnvelope reply) {
        if (reply == null) return "missing-customer-reply";
        String digest = StableParameterDigest.sha256(
                reply.schemaVersion(),
                reply.body(),
                reply.intent() == null ? "null" : reply.intent().name(),
                reply.evidenceRefs() == null ? "null" : String.join("\n", reply.evidenceRefs()),
                Boolean.toString(reply.escalationRequired()),
                reply.referencedOrder());
        return reply.knowledge() == null ? digest : StableParameterDigest.sha256(
                digest, reply.knowledgeRequestId(), json.writeValueAsString(reply.knowledge()));
    }

    private CustomerKnowledgeProjection validateKnowledgeReply(UUID generationId, CustomerReplyEnvelope reply) {
        if (reply.knowledge() == null) return null;
        if (reply.knowledgeRequestId() == null || reply.knowledgeRequestId().isBlank()
                || reply.knowledgeRequestId().length() > 200) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_KNOWLEDGE_CITATION");
        }
        List<AgentKnowledgeResult> receipts = jdbc.query(
                "select response_payload::text from agent_command_request "
                        + "where generation_id=? and request_id=? and operation='SEARCH_KNOWLEDGE'",
                (rs, row) -> json.readValue(rs.getString(1), AgentKnowledgeResult.class),
                generationId, reply.knowledgeRequestId());
        if (receipts.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_KNOWLEDGE_CITATION");
        }
        AgentKnowledgeResult receipt = knowledge.revalidateCustomerForPublication(receipts.getFirst());
        return CustomerKnowledgeReplyPolicy.validate(reply.knowledge(), receipt);
    }

    private void publishCustomerReply(UUID ticketId, UUID generationId, CustomerReplyEnvelope reply,
            CustomerKnowledgeProjection projection, Instant now) {
        if (projection == null) {
            publicProjection.completeAgentReplyStream(ticketId, generationId, reply.body(), now);
            publicProjection.appendAgentMessage(ticketId, generationId, reply.body(), now, false);
            return;
        }
        publicProjection.completeBufferedAgentReplyStream(ticketId, generationId, reply.publicBody(), now);
        publicProjection.appendAgentKnowledgeMessage(ticketId, generationId, reply.publicBody(), projection, now);
        if (reply.knowledge().status() == CustomerKnowledgeStatus.CONFLICT) {
            jdbc.update("insert into audit_event (ticket_id,event_type,actor_id,occurred_at) "
                    + "values (?,'KNOWLEDGE_CONFLICT','spring-system',?)", ticketId, Timestamp.from(now));
        }
    }

    private static String evidenceDigest(List<ConclusionEvidence> evidence) {
        if (evidence == null) return "missing-evidence";
        return evidence.stream()
                .map(
                        item ->
                                item == null
                                        ? "null"
                                        : item.evidenceReference()
                                                + ":"
                                                + (item.applicability() == null
                                                        ? "null"
                                                        : item.applicability().stream()
                                                                .map(Enum::name)
                                                                .sorted()
                                                                .collect(
                                                                        java.util.stream.Collectors
                                                                                .joining(","))))
                .sorted()
                .collect(java.util.stream.Collectors.joining("\n"));
    }

    private static boolean eligibleOrderState(ScopedOrder order) {
        return order.paid() && !order.cancelled() && !order.fullyRefunded();
    }

    private static boolean factsStillMatchCurrentOrder(
            List<PersistedInvestigationFact> facts, ScopedOrder order) {
        Map<String, String> currentValues =
                Map.ofEntries(
                        Map.entry("ORDER", order.orderReference()),
                        Map.entry("LOGISTICS_DELAY_HOURS", Integer.toString(order.delayHours())),
                        Map.entry("LOGISTICS_DELAY_SECONDS", Long.toString(order.delaySeconds())),
                        Map.entry("LOGISTICS_STATUS", order.logisticsStatus()),
                        Map.entry("PAYMENT", order.paid() ? "PAID" : "UNPAID"),
                        Map.entry(
                                "ORDER_CANCELLATION",
                                order.cancelled() ? "CANCELLED" : "NOT_CANCELLED"),
                        Map.entry(
                                "REFUND_STATUS",
                                order.fullyRefunded() ? "FULLY_REFUNDED" : "NOT_FULLY_REFUNDED"),
                        Map.entry(
                                "DUPLICATE_CHARGE_SUSPECTED",
                                Boolean.toString(order.duplicateChargeSuspected())),
                        Map.entry("ORDER_RULE", order.orderRuleSummary()),
                        Map.entry(
                                "EXISTING_COMPENSATION",
                                Boolean.toString(order.existingCompensation())),
                        Map.entry(
                                "PENDING_ACTION_COUNT",
                                Integer.toString(order.pendingActionCount())),
                        Map.entry("POLICY", order.policyVersion()));
        return facts.stream()
                .allMatch(
                        fact ->
                                currentValues.containsKey(fact.factType())
                                        && currentValues
                                                .get(fact.factType())
                                                .equals(fact.factValue()));
    }

    private void reject(UUID ticketId, String reason) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, ?, 'agent-machine', ?)",
                ticketId,
                "AGENT_COMMAND_REJECTED_" + reason,
                Timestamp.from(clock.instant()));
        throw new ResponseStatusException(
                HttpStatus.UNPROCESSABLE_ENTITY,
                "Spring deterministic review rejected the conclusion");
    }

    private void completeGeneration(UUID generationId, Timestamp at) {
        int updated =
                jdbc.update(
                        "update agent_processing_generation set status = 'COMPLETED', completed_at = ? where id = ? and status = 'ACTIVE'",
                        at,
                        generationId);
        if (updated != 1)
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "generation is no longer active");
        jdbc.update(
                "update agent_submission set status = 'COMPLETED' where generation_id = ?",
                generationId);
        jdbc.update(
                "update agent_resume_request set status = 'COMPLETED' where generation_id = ?",
                generationId);
    }

    @Override
    public void auditRejected(UUID ticketId, String reason) {
        accessAudit.rejected(ticketId, reason);
    }

    private ScopedOrder currentOrder(UUID ticketId, UUID generationId) {
        return currentOrder(ticketId, requireActiveGeneration(ticketId, generationId));
    }

    private ScopedOrder currentOrder(UUID ticketId, String orderReference) {
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                rs -> null,
                orderReference + "\nCOMPENSATION_ALLOWANCE");
        List<ScopedOrder> orders =
                jdbc.query(
                        "select o.order_reference, o.delay_hours, o.delay_seconds, o.paid, o.cancelled, o.fully_refunded, "
                                + "allowance.unquantified_existing_compensation, o.policy_version, o.paid_amount, allowance.total_available_compensation_amount, "
                                + "(select count(*) from synthetic_pending_action a where a.order_reference = o.order_reference), "
                                + "allowance.active_reservation_amount, "
                                + "o.logistics_status, o.order_rule_summary, o.duplicate_charge_suspected "
                                + "from support_ticket t join synthetic_order o on o.order_reference = t.order_reference "
                                + "and o.customer_id = t.customer_id "
                                + "join order_compensation_allowance allowance on allowance.order_reference = o.order_reference "
                                + "where t.id = ? and o.order_reference = ?",
                        (rs, row) ->
                                new ScopedOrder(
                                        rs.getString(1),
                                        rs.getInt(2),
                                        rs.getLong(3),
                                        rs.getBoolean(4),
                                        rs.getBoolean(5),
                                        rs.getBoolean(6),
                                        rs.getBoolean(7),
                                        rs.getString(8),
                                        rs.getBigDecimal(9),
                                        rs.getBigDecimal(10),
                                        rs.getInt(11),
                                        rs.getBigDecimal(12),
                                        rs.getString(13),
                                        rs.getString(14),
                                        rs.getBoolean(15)),
                        ticketId,
                        orderReference);
        if (orders.isEmpty()) {
            auditRejectedInTransaction(ticketId, "ORDER_OUTSIDE_TICKET_SCOPE");
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "ticket order is outside the current scope");
        }
        return orders.getFirst();
    }

    private String requireActiveGeneration(UUID ticketId, UUID generationId) {
        List<String> authorized =
                jdbc.query(
                        "select t.order_reference from agent_processing_generation g "
                                + "join support_ticket t on t.id = g.ticket_id "
                                + "where g.id = ? and g.ticket_id = ? and g.status = 'ACTIVE' "
                                + "and t.handling_mode = 'AGENT' and t.lifecycle_state = 'INVESTIGATING' "
                                + "and not t.customer_human_preference "
                                + "and g.generation_number = (select max(current_generation.generation_number) "
                                + "from agent_processing_generation current_generation where current_generation.ticket_id = t.id) "
                                + "for update of g, t",
                        (rs, row) -> rs.getString(1),
                        generationId,
                        ticketId);
        if (authorized.isEmpty()) {
            accessAudit.rejected(ticketId, "STALE_OR_OUT_OF_SCOPE_GENERATION");
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "generation is no longer current for this ticket");
        }
        return authorized.getFirst();
    }

    private void recordFact(
            UUID generationId, String type, String value, String evidence, Instant now) {
        jdbc.update(
                "insert into investigation_fact (generation_id, fact_type, fact_value, evidence_reference, "
                        + "recorded_at, source_authority, valid_until, conflict_status) "
                        + "values (?, ?, ?, ?, ?, 'SPRING_AUTHORIZED_CAPABILITY', ?, 'CLEAR') "
                        + "on conflict (generation_id, fact_type) do nothing",
                generationId,
                type,
                value,
                evidence,
                Timestamp.from(now),
                Timestamp.from(now.plus(Duration.ofHours(1))));
    }

    private List<PersistedInvestigationFact> persistedFacts(UUID ticketId, UUID generationId) {
        return jdbc.query(
                "select f.fact_type, f.fact_value, f.evidence_reference, f.source_authority, "
                        + "f.recorded_at, f.valid_until, f.conflict_status "
                        + "from investigation_fact f join agent_processing_generation g "
                        + "on g.id = f.generation_id where f.generation_id = ? and g.ticket_id = ? for share of f",
                (rs, row) ->
                        new PersistedInvestigationFact(
                                rs.getString(1),
                                rs.getString(2),
                                rs.getString(3),
                                rs.getString(4),
                                rs.getTimestamp(5).toInstant(),
                                rs.getTimestamp(6).toInstant(),
                                rs.getString(7)),
                generationId,
                ticketId);
    }

    private void auditRejectedInTransaction(UUID ticketId, String reason) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, ?, 'agent-machine', ?)",
                ticketId,
                "AGENT_COMMAND_REJECTED_" + reason,
                Timestamp.from(clock.instant()));
    }

    private boolean mayReplayCompletedCommand(UUID ticketId, UUID generationId) {
        return !jdbc.query(
                        "select 1 from agent_processing_generation g join support_ticket t on t.id = g.ticket_id "
                                + "where g.id = ? and g.ticket_id = ? and g.status in ('ACTIVE', 'COMPLETED') "
                                + "and t.handling_mode = 'AGENT' and not t.customer_human_preference",
                        (rs, row) -> rs.getInt(1),
                        generationId,
                        ticketId)
                .isEmpty();
    }

    private record CommandRecord(
            String parameterDigest,
            UUID ticketId,
            String lifecycleState,
            String proposalRevisionId,
            String proposalRevision,
            String proposalStatus) {
        ConclusionAcceptance asAcceptance() {
            return new ConclusionAcceptance(
                    true,
                    TicketLifecycleState.valueOf(lifecycleState),
                    proposalRevisionId == null ? null : UUID.fromString(proposalRevisionId),
                    proposalRevision == null ? null : Integer.valueOf(proposalRevision),
                    proposalStatus == null ? null : ProposalRevisionStatus.valueOf(proposalStatus));
        }
    }

    record ScopedOrder(
            String orderReference,
            int delayHours,
            long delaySeconds,
            boolean paid,
            boolean cancelled,
            boolean fullyRefunded,
            boolean existingCompensation,
            String policyVersion,
            BigDecimal paidAmount,
            BigDecimal totalAvailableCompensationAmount,
            int pendingActionCount,
            BigDecimal activeReservationAmount,
            String logisticsStatus,
            String orderRuleSummary,
            boolean duplicateChargeSuspected) {
        List<String> evidenceRefs() {
            return List.of("order:" + orderReference, "logistics:" + orderReference);
        }
    }
}
