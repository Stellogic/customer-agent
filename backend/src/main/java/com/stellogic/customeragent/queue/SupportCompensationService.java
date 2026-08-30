package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.compensation.DelayCompensationPolicy;
import com.stellogic.customeragent.investigation.JdbcCompensationProposalStore;
import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
class SupportCompensationService {
    static final String SCHEMA = SupportWorkbenchProjectionService.EPOCH;
    static final String STANDARD_REASON = "LOGISTICS_DELAY";
    static final String EXCEPTION_REASON = "STANDARD_PLAN_INSUFFICIENT";
    static final String CURRENCY = "CNY";
    private static final List<SupportTicketLifecycleState> COMPENSATION_LIFECYCLES =
            List.of(
                    SupportTicketLifecycleState.NEW,
                    SupportTicketLifecycleState.INVESTIGATING,
                    SupportTicketLifecycleState.WAITING_FOR_CUSTOMER,
                    SupportTicketLifecycleState.WAITING_FOR_EXTERNAL);

    private final JdbcTemplate jdbc;
    private final TicketAuthorityLock ticketLock;
    private final DelayCompensationPolicy policy = new DelayCompensationPolicy();
    private final JdbcCompensationProposalStore proposalStore;
    private final CustomerPublicProjectionAppender publicProjection;

    SupportCompensationService(
            JdbcTemplate jdbc,
            TicketAuthorityLock ticketLock,
            JdbcCompensationProposalStore proposalStore,
            CustomerPublicProjectionAppender publicProjection) {
        this.jdbc = jdbc;
        this.ticketLock = ticketLock;
        this.proposalStore = proposalStore;
        this.publicProjection = publicProjection;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    SupportCompensationOptions listOptions(String supportId, UUID ticketId) {
        requireSupportPrincipal(supportId);
        AssignedTicket ticket = requireAssignedTicket(supportId, ticketId, false);
        OrderFacts order = loadOrder(ticket.orderReference(), ticketId);
        DelayCompensationPolicy.Plan plan =
                policy.currentPlan(Duration.ofSeconds(order.delaySeconds()), order.paidAmount());
        List<SupportCompensationPlan> plans =
                plan.eligible() && eligibleOrderState(order)
                        ? List.of(toPublicPlan(plan))
                        : List.of();
        return new SupportCompensationOptions(SCHEMA, DelayCompensationPolicy.VERSION, plans);
    }

    @Transactional
    SupportCompensationProposalResult submitProposal(
            String supportId,
            UUID ticketId,
            String planCode,
            String reasonCode,
            String idempotencyKey) {
        requireSupportPrincipal(supportId);
        String digest = StableParameterDigest.sha256(ticketId.toString(), planCode, reasonCode);
        ticketLock.acquire(ticketId);
        lockRequest(supportId, "SUPPORT_COMPENSATION_PROPOSAL", idempotencyKey);
        AssignedTicket ticket = requireAssignedHumanTicket(supportId, ticketId);
        List<ProposalReceipt> existing = findProposalReceipt(supportId, idempotencyKey);
        if (!existing.isEmpty()) {
            ProposalReceipt record = existing.getFirst();
            if (!record.ticketId().equals(ticketId) || !record.digest().equals(digest)) {
                throw new SupportCompensationIdentityConflictException();
            }
            return toProposalResult(record, idempotencyKey, true);
        }
        requireCompensationLifecycle(ticket);
        if (!STANDARD_REASON.equals(reasonCode)) {
            throw new SupportCompensationInvalidRequestException("PLAN_NOT_ALLOWED");
        }
        OrderFacts order = lockAndLoadOrder(ticket.orderReference(), ticketId);
        if (!eligibleOrderState(order)
                || order.existingCompensation()
                || order.pendingActionCount() != 0
                || !DelayCompensationPolicy.VERSION.equals(order.policyVersion())) {
            throw new SupportCompensationConflictException("COMPENSATION_PROPOSAL_INELIGIBLE");
        }
        DelayCompensationPolicy.Plan plan =
                policy.currentPlan(Duration.ofSeconds(order.delaySeconds()), order.paidAmount());
        if (!plan.eligible() || !plan.planCode().equals(planCode)) {
            throw new SupportCompensationConflictException("STALE_COMPENSATION_FACTS");
        }
        BigDecimal remainingAvailable =
                order.totalAvailableAmount().subtract(order.activeReservationAmount());
        if (remainingAvailable.compareTo(plan.amount()) < 0) {
            throw new SupportCompensationConflictException("COMPENSATION_ALLOWANCE_INSUFFICIENT");
        }
        JdbcCompensationProposalStore.StoredProposal proposal;
        try {
            proposal =
                    proposalStore.save(
                            new JdbcCompensationProposalStore.ProposalContent(
                                    ticketId,
                                    null,
                                    order.orderReference(),
                                    order.delayHours(),
                                    order.delaySeconds(),
                                    plan.method().name(),
                                    plan.amount(),
                                    List.of(
                                            "order:" + order.orderReference(),
                                            "logistics:" + order.orderReference()),
                                    order.policyVersion(),
                                    order.paidAmount(),
                                    order.totalAvailableAmount(),
                                    order.activeReservationAmount(),
                                    remainingAvailable,
                                    order.paid(),
                                    order.cancelled(),
                                    order.fullyRefunded(),
                                    order.existingCompensation()));
        } catch (JdbcCompensationProposalStore.ActiveIntentException exception) {
            throw new SupportCompensationConflictException(exception.reason());
        }
        Timestamp databaseTime = jdbc.queryForObject("select clock_timestamp()", Timestamp.class);
        Instant now = databaseTime == null ? Instant.now() : databaseTime.toInstant();
        String amountText = plan.amount().toPlainString();
        publicProjection.appendSupportCompensationReview(
                ticketId,
                UUID.randomUUID(),
                publicReviewMessage(plan.method().name(), amountText),
                plan.method().name(),
                amountText,
                now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                        + "values (?, ?, ?, ?, 'COMPENSATION_PROPOSAL_REVISION', ?)",
                ticketId,
                proposal.created()
                        ? "COMPENSATION_PROPOSAL_REVISION_CREATED_BY_SUPPORT"
                        : "COMPENSATION_PROPOSAL_REVISION_SUBMITTED_BY_SUPPORT",
                supportId,
                databaseTime,
                proposal.revisionId());
        if (proposal.created()) {
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                            + "values (?, 'COMPENSATION_PROPOSAL_REVISION_SUBMITTED_BY_SUPPORT', ?, ?, "
                            + "'COMPENSATION_PROPOSAL_REVISION', ?)",
                    ticketId,
                    supportId,
                    databaseTime,
                    proposal.revisionId());
        }
        jdbc.update(
                "insert into support_compensation_proposal_request "
                        + "(support_id, request_id, ticket_id, parameter_digest, proposal_revision_id, "
                        + "proposal_revision, outcome, received_at) values (?, ?, ?, ?, ?, ?, 'ACCEPTED', ?)",
                supportId,
                idempotencyKey,
                ticketId,
                digest,
                proposal.revisionId(),
                proposal.revisionNumber(),
                databaseTime);
        return new SupportCompensationProposalResult(
                SCHEMA,
                ticketId,
                idempotencyKey,
                proposal.revisionId(),
                proposal.revisionNumber(),
                plan.method().name(),
                plan.amount(),
                CURRENCY,
                "PENDING_APPROVAL",
                "ACCEPTED",
                false);
    }

    @Transactional(isolation = Isolation.REPEATABLE_READ)
    SupportCompensationProposalResult queryProposal(
            String supportId, UUID ticketId, String idempotencyKey) {
        requireSupportPrincipal(supportId);
        List<ProposalReceipt> requests = findProposalReceipt(supportId, idempotencyKey);
        if (requests.isEmpty() || !ticketId.equals(requests.getFirst().ticketId())) {
            throw new SupportTicketNotFoundException();
        }
        return toProposalResult(requests.getFirst(), idempotencyKey, true);
    }

    @Transactional
    SupportExceptionalCompensationResult submitException(
            String supportId,
            UUID ticketId,
            String reasonCode,
            String justification,
            String idempotencyKey) {
        requireSupportPrincipal(supportId);
        String normalized = justification.trim();
        String digest = StableParameterDigest.sha256(ticketId.toString(), reasonCode, normalized);
        ticketLock.acquire(ticketId);
        lockRequest(supportId, "SUPPORT_EXCEPTIONAL_COMPENSATION", idempotencyKey);
        AssignedTicket ticket = requireAssignedHumanTicket(supportId, ticketId);
        List<ExceptionReceipt> existing = findExceptionReceipt(supportId, idempotencyKey);
        if (!existing.isEmpty()) {
            ExceptionReceipt record = existing.getFirst();
            if (!record.ticketId().equals(ticketId) || !record.digest().equals(digest)) {
                throw new SupportCompensationIdentityConflictException();
            }
            return toExceptionResult(record, idempotencyKey, true);
        }
        requireCompensationLifecycle(ticket);
        if (!EXCEPTION_REASON.equals(reasonCode)) {
            throw new SupportCompensationInvalidRequestException("PLAN_NOT_ALLOWED");
        }
        lockAndLoadOrder(ticket.orderReference(), ticketId);
        Timestamp databaseTime = jdbc.queryForObject("select clock_timestamp()", Timestamp.class);
        UUID exceptionalId = UUID.randomUUID();
        jdbc.update(
                "insert into exceptional_compensation_request "
                        + "(id, ticket_id, order_reference, support_id, reason_code, justification, status, created_at) "
                        + "values (?, ?, ?, ?, ?, ?, 'SUBMITTED', ?)",
                exceptionalId,
                ticketId,
                ticket.orderReference(),
                supportId,
                reasonCode,
                normalized,
                databaseTime);
        jdbc.update(
                "insert into exceptional_compensation_request_receipt "
                        + "(support_id, request_id, ticket_id, parameter_digest, exceptional_request_id, outcome, received_at) "
                        + "values (?, ?, ?, ?, ?, 'ACCEPTED', ?)",
                supportId,
                idempotencyKey,
                ticketId,
                digest,
                exceptionalId,
                databaseTime);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                        + "values (?, 'EXCEPTIONAL_COMPENSATION_REQUEST_SUBMITTED', ?, ?, "
                        + "'EXCEPTIONAL_COMPENSATION_REQUEST', ?)",
                ticketId,
                supportId,
                databaseTime,
                exceptionalId);
        return new SupportExceptionalCompensationResult(
                SCHEMA,
                ticketId,
                idempotencyKey,
                exceptionalId,
                reasonCode,
                "SUBMITTED",
                "ACCEPTED",
                false);
    }

    @Transactional(isolation = Isolation.REPEATABLE_READ)
    SupportExceptionalCompensationResult queryException(
            String supportId, UUID ticketId, String idempotencyKey) {
        requireSupportPrincipal(supportId);
        List<ExceptionReceipt> requests = findExceptionReceipt(supportId, idempotencyKey);
        if (requests.isEmpty() || !ticketId.equals(requests.getFirst().ticketId())) {
            throw new SupportTicketNotFoundException();
        }
        return toExceptionResult(requests.getFirst(), idempotencyKey, true);
    }

    private AssignedTicket requireAssignedHumanTicket(String supportId, UUID ticketId) {
        AssignedTicket ticket = requireAssignedTicket(supportId, ticketId, true);
        if (ticket.handlingMode() != SupportHandlingMode.HUMAN) {
            throw new SupportCompensationNotAllowedException("HANDLING_MODE_CHANGED");
        }
        return ticket;
    }

    private AssignedTicket requireAssignedTicket(
            String supportId, UUID ticketId, boolean forUpdate) {
        String lock = forUpdate ? " for update of t, a" : "";
        List<AssignedTicket> tickets =
                jdbc.query(
                        "select t.order_reference, t.lifecycle_state, t.handling_mode "
                                + "from support_ticket t join support_assignment a on a.ticket_id = t.id "
                                + "where t.id = ? and a.support_id = ? and a.status = 'ACTIVE' "
                                + "and t.lifecycle_state not in ('RESOLVED', 'CLOSED')"
                                + lock,
                        (rs, row) ->
                                new AssignedTicket(
                                        rs.getString(1),
                                        SupportTicketLifecycleState.valueOf(rs.getString(2)),
                                        SupportHandlingMode.valueOf(rs.getString(3))),
                        ticketId,
                        supportId);
        if (tickets.isEmpty()) throw new SupportTicketNotFoundException();
        return tickets.getFirst();
    }

    private static void requireCompensationLifecycle(AssignedTicket ticket) {
        if (!COMPENSATION_LIFECYCLES.contains(ticket.lifecycleState())) {
            throw new SupportCompensationNotAllowedException("SUPPORT_COMPENSATION_NOT_ALLOWED");
        }
    }

    private OrderFacts lockAndLoadOrder(String orderReference, UUID ticketId) {
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                rs -> null,
                orderReference + "\nCOMPENSATION_ALLOWANCE");
        return loadOrder(orderReference, ticketId);
    }

    private OrderFacts loadOrder(String orderReference, UUID ticketId) {
        List<OrderFacts> orders =
                jdbc.query(
                        "select o.order_reference, o.delay_hours, o.delay_seconds, o.paid, o.cancelled, "
                                + "o.fully_refunded, o.existing_compensation, o.policy_version, o.paid_amount, "
                                + "o.available_compensation_amount, "
                                + "(select count(*) from synthetic_pending_action a "
                                + "where a.order_reference = o.order_reference), "
                                + "coalesce((select sum(r.amount) from compensation_reservation r "
                                + "where r.order_reference = o.order_reference and r.status = 'ACTIVE'), 0) "
                                + "from support_ticket t join synthetic_order o on o.order_reference = t.order_reference "
                                + "and o.customer_id = t.customer_id where t.id = ? and o.order_reference = ?",
                        (rs, row) ->
                                new OrderFacts(
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
                                        rs.getBigDecimal(12)),
                        ticketId,
                        orderReference);
        if (orders.isEmpty()) {
            throw new SupportCompensationConflictException("STALE_COMPENSATION_FACTS");
        }
        return orders.getFirst();
    }

    private List<ProposalReceipt> findProposalReceipt(String supportId, String idempotencyKey) {
        return jdbc.query(
                "select r.ticket_id, r.parameter_digest, r.proposal_revision_id, r.proposal_revision, "
                        + "p.compensation_method, p.amount "
                        + "from support_compensation_proposal_request r "
                        + "join compensation_proposal_revision p on p.id = r.proposal_revision_id "
                        + "where r.support_id = ? and r.request_id = ?",
                (rs, row) ->
                        new ProposalReceipt(
                                rs.getObject(1, UUID.class),
                                rs.getString(2),
                                rs.getObject(3, UUID.class),
                                rs.getInt(4),
                                rs.getString(5),
                                rs.getBigDecimal(6)),
                supportId,
                idempotencyKey);
    }

    private List<ExceptionReceipt> findExceptionReceipt(String supportId, String idempotencyKey) {
        return jdbc.query(
                "select r.ticket_id, r.parameter_digest, r.exceptional_request_id, e.reason_code "
                        + "from exceptional_compensation_request_receipt r "
                        + "join exceptional_compensation_request e on e.id = r.exceptional_request_id "
                        + "where r.support_id = ? and r.request_id = ?",
                (rs, row) ->
                        new ExceptionReceipt(
                                rs.getObject(1, UUID.class),
                                rs.getString(2),
                                rs.getObject(3, UUID.class),
                                rs.getString(4)),
                supportId,
                idempotencyKey);
    }

    private void lockRequest(String supportId, String scope, String idempotencyKey) {
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                resultSet -> null,
                supportId + "\n" + scope + "\n" + idempotencyKey);
    }

    private static SupportCompensationProposalResult toProposalResult(
            ProposalReceipt record, String idempotencyKey, boolean replayed) {
        return new SupportCompensationProposalResult(
                SCHEMA,
                record.ticketId(),
                idempotencyKey,
                record.revisionId(),
                record.revisionNumber(),
                record.compensationMethod(),
                record.amount(),
                CURRENCY,
                "PENDING_APPROVAL",
                "ACCEPTED",
                replayed);
    }

    private static SupportExceptionalCompensationResult toExceptionResult(
            ExceptionReceipt record, String idempotencyKey, boolean replayed) {
        return new SupportExceptionalCompensationResult(
                SCHEMA,
                record.ticketId(),
                idempotencyKey,
                record.exceptionalRequestId(),
                record.reasonCode(),
                "SUBMITTED",
                "ACCEPTED",
                replayed);
    }

    private static SupportCompensationPlan toPublicPlan(DelayCompensationPolicy.Plan plan) {
        return new SupportCompensationPlan(
                plan.planCode(),
                plan.method().name(),
                plan.amount(),
                plan.capAmount(),
                CURRENCY,
                List.of(STANDARD_REASON));
    }

    private static boolean eligibleOrderState(OrderFacts order) {
        return order.paid() && !order.cancelled() && !order.fullyRefunded();
    }

    private static String publicReviewMessage(String method, String amount) {
        String type = "COUPON".equals(method) ? "优惠券" : "模拟原路部分退款";
        return "补偿建议正在等待人工审批。建议类型：" + type + "，金额：" + amount + " CNY。最终结果将在处理完成后通知你。";
    }

    private static void requireSupportPrincipal(String supportId) {
        if (supportId == null || supportId.isBlank()) {
            throw new SupportIdentityRequiredException();
        }
    }

    private record AssignedTicket(
            String orderReference,
            SupportTicketLifecycleState lifecycleState,
            SupportHandlingMode handlingMode) {}

    private record OrderFacts(
            String orderReference,
            int delayHours,
            long delaySeconds,
            boolean paid,
            boolean cancelled,
            boolean fullyRefunded,
            boolean existingCompensation,
            String policyVersion,
            BigDecimal paidAmount,
            BigDecimal totalAvailableAmount,
            int pendingActionCount,
            BigDecimal activeReservationAmount) {}

    private record ProposalReceipt(
            UUID ticketId,
            String digest,
            UUID revisionId,
            int revisionNumber,
            String compensationMethod,
            BigDecimal amount) {}

    private record ExceptionReceipt(
            UUID ticketId, String digest, UUID exceptionalRequestId, String reasonCode) {}
}
