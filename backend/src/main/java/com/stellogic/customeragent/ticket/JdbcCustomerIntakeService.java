package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import java.util.List;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@ConditionalOnProperty(name = "baseline.migrate-only", havingValue = "false", matchIfMissing = true)
class JdbcCustomerIntakeService implements CustomerIntakeService {
    private final JdbcTemplate jdbc;
    private final IntakeUnderstandingGateway agent;
    private final CustomerTicketService tickets;

    JdbcCustomerIntakeService(
            JdbcTemplate jdbc, IntakeUnderstandingGateway agent, CustomerTicketService tickets) {
        this.jdbc = jdbc;
        this.agent = agent;
        this.tickets = tickets;
    }

    @Override
    @Transactional
    public CustomerIntakeSnapshot start(StartCustomerIntake command) {
        String digest = StableParameterDigest.sha256(command.message());
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                resultSet -> null,
                command.customerId() + "\n" + command.requestId());
        List<IntakeRow> existing =
                jdbc.query(
                        "select "
                                + intakeColumns()
                                + " from customer_intake "
                                + "where customer_id = ? and start_request_key = ? for update",
                        (rs, row) -> map(rs),
                        command.customerId(),
                        command.requestId());
        if (!existing.isEmpty()) {
            IntakeRow row = existing.getFirst();
            if (!row.startDigest().equals(digest)) throw new RequestIdentityConflictException();
            return snapshot(row, true);
        }

        List<CustomerVisibleOrderSummary> orders = visibleOrders(command.customerId());
        IntakeUnderstanding understanding =
                agent.understand(
                        new IntakeUnderstandingRequest(command.message(), orders, null, null));
        requireUnderstanding(understanding, orders);
        String assistantMessage = CustomerIntakeSafetyPolicy.assistantMessage(understanding);
        UUID intakeId = UUID.randomUUID();
        CustomerVisibleOrderSummary candidate = candidate(understanding, orders);
        jdbc.update(
                "insert into customer_intake "
                        + "(id, customer_id, start_request_key, start_digest, original_message, status, "
                        + "candidate_order_reference, candidate_order_version, candidate_order_summary, issue_kind, "
                        + "issue_summary, assistant_message, created_at, updated_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp, current_timestamp)",
                intakeId,
                command.customerId(),
                command.requestId(),
                digest,
                command.message(),
                understanding.status(),
                understanding.candidateOrderReference(),
                candidate == null ? null : candidate.version(),
                candidate == null ? null : candidate.summary(),
                understanding.issueKind(),
                understanding.issueSummary(),
                assistantMessage);
        return snapshot(load(command.customerId(), intakeId), false);
    }

    @Override
    @Transactional
    public CustomerIntakeSnapshot reply(ReplyCustomerIntake command) {
        IntakeRow current = loadForUpdate(command.customerId(), command.intakeId());
        String digest = StableParameterDigest.sha256(command.message());
        List<MessageIdentity> prior =
                jdbc.query(
                        "select request_digest from customer_intake_message "
                                + "where intake_id = ? and request_key = ?",
                        (rs, row) -> new MessageIdentity(rs.getString(1)),
                        command.intakeId(),
                        command.requestId());
        if (!prior.isEmpty()) {
            if (!prior.getFirst().digest().equals(digest)) {
                throw new RequestIdentityConflictException();
            }
            return snapshot(current, true);
        }
        jdbc.update(
                "insert into customer_intake_message "
                        + "(intake_id, request_key, request_digest, customer_message, created_at) "
                        + "values (?, ?, ?, ?, current_timestamp)",
                command.intakeId(),
                command.requestId(),
                digest,
                command.message());
        if (current.ticketId() != null) return snapshot(current, true);

        List<CustomerVisibleOrderSummary> orders = visibleOrders(command.customerId());
        IntakeUnderstanding understanding =
                agent.understand(
                        new IntakeUnderstandingRequest(
                                command.message(),
                                orders,
                                current.orderReference(),
                                current.issueSummary()));
        if ("CONFIRM".equals(understanding.intent())) {
            if (!CustomerIntakeSafetyPolicy.isExplicitConfirmation(command.message())) {
                throw new IntakeAgentUnavailableException();
            }
            return confirm(command, current, "已确认，客服工单正在独立处理。");
        }
        requireUnderstanding(understanding, orders);
        String assistantMessage = CustomerIntakeSafetyPolicy.assistantMessage(understanding);
        CustomerVisibleOrderSummary candidate = candidate(understanding, orders);
        jdbc.update(
                "update customer_intake set status = ?, candidate_order_reference = ?, "
                        + "candidate_order_version = ?, candidate_order_summary = ?, issue_kind = ?, "
                        + "issue_summary = ?, assistant_message = ?, updated_at = current_timestamp where id = ?",
                understanding.status(),
                understanding.candidateOrderReference(),
                candidate == null ? null : candidate.version(),
                candidate == null ? null : candidate.summary(),
                understanding.issueKind(),
                understanding.issueSummary(),
                assistantMessage,
                command.intakeId());
        return snapshot(load(command.customerId(), command.intakeId()), false);
    }

    private CustomerIntakeSnapshot confirm(
            ReplyCustomerIntake command, IntakeRow current, String assistantMessage) {
        if (!"READY_TO_CONFIRM".equals(current.status())
                || current.orderReference() == null
                || current.issueKind() == null) {
            throw new IntakeNotReadyException();
        }
        CustomerVisibleOrderSummary authoritative =
                authoritativeOrderForConfirmation(command.customerId(), current.orderReference());
        if (!authoritative.version().equals(current.orderVersion())) {
            throw new IntakeCandidateStaleException();
        }
        TicketCreationResult created =
                tickets.create(
                        new CreateCustomerTicket(
                                command.customerId(),
                                "intake-confirm:" + command.intakeId(),
                                current.orderReference(),
                                current.issueSummary(),
                                current.issueKind()));
        jdbc.update(
                "update customer_intake set status = 'CONFIRMED', assistant_message = ?, ticket_id = ?, "
                        + "confirmed_at = current_timestamp, updated_at = current_timestamp where id = ?",
                assistantMessage,
                created.ticketId(),
                command.intakeId());
        return snapshot(load(command.customerId(), command.intakeId()), false);
    }

    private List<CustomerVisibleOrderSummary> visibleOrders(String customerId) {
        return jdbc.query(
                "select order_reference, paid, cancelled, fully_refunded, delay_seconds, policy_version "
                        + "from synthetic_order where customer_id = ? order by order_reference",
                (rs, row) -> orderSummary(rs),
                customerId);
    }

    private CustomerVisibleOrderSummary authoritativeOrderForConfirmation(
            String customerId, String orderReference) {
        List<CustomerVisibleOrderSummary> rows =
                jdbc.query(
                        "select order_reference, paid, cancelled, fully_refunded, delay_seconds, policy_version "
                                + "from synthetic_order where customer_id = ? and order_reference = ? for update",
                        (rs, row) -> orderSummary(rs),
                        customerId,
                        orderReference);
        if (rows.isEmpty()) throw new IntakeCandidateStaleException();
        return rows.getFirst();
    }

    private static CustomerVisibleOrderSummary orderSummary(java.sql.ResultSet rs)
            throws java.sql.SQLException {
        String reference = rs.getString(1);
        boolean paid = rs.getBoolean(2);
        boolean cancelled = rs.getBoolean(3);
        boolean refunded = rs.getBoolean(4);
        long delaySeconds = rs.getLong(5);
        String policy = rs.getString(6);
        String summary =
                cancelled ? "已取消的合成订单" : refunded ? "已退款的合成订单" : paid ? "配送中的合成订单" : "待支付的合成订单";
        String version =
                StableParameterDigest.sha256(
                        reference,
                        Boolean.toString(paid),
                        Boolean.toString(cancelled),
                        Boolean.toString(refunded),
                        Long.toString(delaySeconds),
                        policy);
        return new CustomerVisibleOrderSummary(reference, summary, version);
    }

    private static void requireUnderstanding(
            IntakeUnderstanding understanding, List<CustomerVisibleOrderSummary> orders) {
        if (!"UNDERSTANDING".equals(understanding.intent())
                || !List.of("READY_TO_CONFIRM", "NEEDS_CLARIFICATION")
                        .contains(understanding.status())
                || ("READY_TO_CONFIRM".equals(understanding.status())
                        && (understanding.candidateOrderReference() == null
                                || understanding.issueKind() == null
                                || understanding.issueSummary() == null))
                || (understanding.candidateOrderReference() != null
                        && orders.stream()
                                .noneMatch(
                                        order ->
                                                order.reference()
                                                        .equals(
                                                                understanding
                                                                        .candidateOrderReference())))) {
            throw new IntakeAgentUnavailableException();
        }
    }

    private static CustomerVisibleOrderSummary candidate(
            IntakeUnderstanding understanding, List<CustomerVisibleOrderSummary> orders) {
        if (understanding.candidateOrderReference() == null) return null;
        return orders.stream()
                .filter(order -> order.reference().equals(understanding.candidateOrderReference()))
                .findFirst()
                .orElseThrow(IntakeAgentUnavailableException::new);
    }

    private IntakeRow loadForUpdate(String customerId, UUID intakeId) {
        List<IntakeRow> rows =
                jdbc.query(
                        "select "
                                + intakeColumns()
                                + " from customer_intake "
                                + "where id = ? and customer_id = ? for update",
                        (rs, row) -> map(rs),
                        intakeId,
                        customerId);
        if (rows.isEmpty()) throw new IntakeNotFoundException();
        return rows.getFirst();
    }

    private IntakeRow load(String customerId, UUID intakeId) {
        List<IntakeRow> rows =
                jdbc.query(
                        "select "
                                + intakeColumns()
                                + " from customer_intake where id = ? and customer_id = ?",
                        (rs, row) -> map(rs),
                        intakeId,
                        customerId);
        if (rows.isEmpty()) throw new IntakeNotFoundException();
        return rows.getFirst();
    }

    private static String intakeColumns() {
        return "id, start_digest, status, candidate_order_reference, candidate_order_version, "
                + "candidate_order_summary, issue_kind, issue_summary, assistant_message, ticket_id";
    }

    private static IntakeRow map(java.sql.ResultSet rs) throws java.sql.SQLException {
        return new IntakeRow(
                rs.getObject(1, UUID.class),
                rs.getString(2),
                rs.getString(3),
                rs.getString(4),
                rs.getString(5),
                rs.getString(6),
                rs.getString(7),
                rs.getString(8),
                rs.getString(9),
                rs.getObject(10, UUID.class));
    }

    private static CustomerIntakeSnapshot snapshot(IntakeRow row, boolean replayed) {
        return new CustomerIntakeSnapshot(
                row.id(),
                row.status(),
                row.orderReference(),
                row.orderSummary(),
                row.issueKind(),
                row.issueSummary(),
                row.assistantMessage(),
                row.ticketId(),
                replayed);
    }

    private record MessageIdentity(String digest) {}

    private record IntakeRow(
            UUID id,
            String startDigest,
            String status,
            String orderReference,
            String orderVersion,
            String orderSummary,
            String issueKind,
            String issueSummary,
            String assistantMessage,
            UUID ticketId) {}
}
