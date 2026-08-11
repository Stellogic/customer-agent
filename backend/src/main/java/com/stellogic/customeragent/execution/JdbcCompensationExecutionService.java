package com.stellogic.customeragent.execution;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
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
class JdbcCompensationExecutionService implements CompensationExecutionService {
    private static final String CUSTOMER_PUBLIC_EPOCH = "customer-public-v1";
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TicketAuthorityLock authorityLock;

    JdbcCompensationExecutionService(JdbcTemplate jdbc, Clock clock, TicketAuthorityLock authorityLock) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.authorityLock = authorityLock;
    }

    @Override
    @Transactional(readOnly = true)
    public List<CompensationExecutionModels.Assignment> assignments(String executorId) {
        return jdbc.query(
                "select id, compensation_method, amount, status from compensation_execution "
                        + "where assigned_executor_id = ? and status = 'READY' order by created_at, id",
                (rs, row) -> new CompensationExecutionModels.Assignment(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getBigDecimal(3), rs.getString(4)),
                executorId);
    }

    @Override
    @Transactional
    public CompensationExecutionModels.ClaimResult claim(CompensationExecutionModels.ClaimCommand command) {
        String requestDigest = StableParameterDigest.sha256(command.executionId().toString());
        lockRequest(command.executorId(), "CLAIM", command.requestId());
        List<ClaimReplay> replays = jdbc.query(
                "select a.parameter_digest, e.id, a.id, e.status, e.idempotency_key, e.parameter_digest, "
                        + "e.compensation_method, e.amount from compensation_execution_attempt a "
                        + "join compensation_execution e on e.id = a.execution_id "
                        + "where a.executor_id = ? and a.delivery_request_id = ?",
                (rs, row) -> new ClaimReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        rs.getString(4), rs.getString(5), rs.getString(6), rs.getString(7), rs.getBigDecimal(8)),
                command.executorId(), command.requestId());
        if (!replays.isEmpty()) {
            ClaimReplay replay = replays.getFirst();
            if (!requestDigest.equals(replay.requestDigest())) conflict("delivery identity conflict");
            return claimResult(replay, true);
        }

        ExecutionRow execution = lockExecution(command.executionId(), command.executorId());
        if (!"READY".equals(execution.status())) {
            if ("SUCCEEDED".equals(execution.status())) {
                UUID attemptId = jdbc.queryForObject(
                        "select attempt_id from compensation_execution_result where execution_id = ?",
                        UUID.class, command.executionId());
                return new CompensationExecutionModels.ClaimResult(
                        execution.id(), attemptId, execution.status(), execution.idempotencyKey(),
                        execution.parameterDigest(), execution.method(), execution.amount(), true);
            }
            conflict("execution already claimed");
        }
        if (execution.parameterDigest() == null) {
            throw new IllegalStateException("approved execution is missing its parameter digest");
        }
        UUID attemptId = stableUuid(command.executorId() + "\n" + command.requestId());
        Timestamp now = Timestamp.from(clock.instant());
        jdbc.update(
                "insert into compensation_execution_attempt "
                        + "(id, execution_id, executor_id, delivery_request_id, parameter_digest, started_at) "
                        + "values (?, ?, ?, ?, ?, ?)",
                attemptId, execution.id(), command.executorId(), command.requestId(), requestDigest, now);
        jdbc.update(
                "update compensation_execution set status = 'PROCESSING', processing_attempt_id = ? "
                        + "where id = ? and status = 'READY'",
                attemptId, execution.id());
        return new CompensationExecutionModels.ClaimResult(
                execution.id(), attemptId, "PROCESSING", execution.idempotencyKey(),
                execution.parameterDigest(), execution.method(), execution.amount(), false);
    }

    @Override
    @Transactional
    public CompensationExecutionModels.SuccessResult succeed(CompensationExecutionModels.SuccessCommand command) {
        String requestDigest = StableParameterDigest.sha256(
                command.executionId().toString(), command.attemptId().toString(),
                command.idempotencyKey(), command.parameterDigest());
        lockRequest(command.executorId(), "SUCCESS", command.requestId());
        List<SuccessReplay> replays = successReplay(command.executorId(), command.requestId());
        if (!replays.isEmpty()) {
            SuccessReplay replay = replays.getFirst();
            if (!requestDigest.equals(replay.requestDigest())) conflict("result identity conflict");
            return replay.result(true);
        }

        ExecutionRow execution = lockExecution(command.executionId(), command.executorId());
        requireBoundParameters(execution, command);
        if ("SUCCEEDED".equals(execution.status())) {
            SuccessReplay result = result(command.executionId(), requestDigest);
            recordSuccessRequest(command, requestDigest, result.attemptId());
            return result.result(true);
        }
        if (!"PROCESSING".equals(execution.status())
                || !command.attemptId().equals(execution.processingAttemptId())) {
            conflict("execution is not held by this attempt");
        }

        UUID ticketId = jdbc.queryForObject(
                "select p.ticket_id from compensation_execution e "
                        + "join compensation_proposal_revision p on p.id = e.proposal_revision_id where e.id = ?",
                UUID.class, execution.id());
        authorityLock.acquire(ticketId);
        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        String maskedDestination = "SIMULATED_PARTIAL_REFUND".equals(execution.method())
                ? "原支付方式（尾号 4242）" : null;
        String customerMessage = customerMessage(execution.method(), execution.amount(), maskedDestination);
        String resultReference = ("COUPON".equals(execution.method()) ? "coupon:" : "simulated-refund:")
                + execution.id();
        jdbc.update(
                "insert into compensation_execution_result (execution_id, attempt_id, result_reference, "
                        + "compensation_method, amount, masked_destination, customer_message, confirmed_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?)",
                execution.id(), command.attemptId(), resultReference, execution.method(), execution.amount(),
                maskedDestination, customerMessage, at);
        jdbc.update(
                "update compensation_execution set status = 'SUCCEEDED', succeeded_at = ? where id = ?",
                at, execution.id());
        jdbc.update("update compensation_reservation set status = 'CONSUMED' where id = ? and status = 'ACTIVE'",
                execution.reservationId());
        jdbc.update("update synthetic_order set existing_compensation = true where order_reference = ?",
                execution.orderReference());
        int resolved = jdbc.update(
                "update support_ticket set lifecycle_state = 'RESOLVED', "
                        + "resolution_elapsed_seconds = resolution_elapsed_seconds + "
                        + "case when resolution_running_since is null then 0 else greatest(0, "
                        + "extract(epoch from (?::timestamptz - resolution_running_since))::bigint) end, "
                        + "resolution_running_since = null where id = ? and lifecycle_state <> 'CLOSED'",
                at, ticketId);
        if (resolved != 1) conflict("ticket is no longer resolvable");
        appendCustomerResult(ticketId, customerMessage, now, at);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                        + "values (?, 'COMPENSATION_EXECUTION_SUCCEEDED', ?, ?, 'COMPENSATION_EXECUTION', ?), "
                        + "(?, 'TICKET_RESOLVED', 'spring-system', ?, 'COMPENSATION_EXECUTION', ?)",
                ticketId, command.executorId(), at, execution.id(), ticketId, at, execution.id());
        recordSuccessRequest(command, requestDigest, command.attemptId());
        return new CompensationExecutionModels.SuccessResult(
                execution.id(), command.attemptId(), "SUCCEEDED", execution.method(), execution.amount(),
                customerMessage, false);
    }

    private ExecutionRow lockExecution(UUID executionId, String executorId) {
        List<ExecutionRow> executions = jdbc.query(
                "select id, reservation_id, order_reference, compensation_method, amount, status, "
                        + "idempotency_key, parameter_digest, processing_attempt_id "
                        + "from compensation_execution where id = ? and assigned_executor_id = ? for update",
                (rs, row) -> new ExecutionRow(
                        rs.getObject(1, UUID.class), rs.getObject(2, UUID.class), rs.getString(3),
                        rs.getString(4), rs.getBigDecimal(5), rs.getString(6), rs.getString(7),
                        rs.getString(8), rs.getObject(9, UUID.class)),
                executionId, executorId);
        if (executions.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "assigned execution not found");
        }
        return executions.getFirst();
    }

    private void requireBoundParameters(ExecutionRow execution, CompensationExecutionModels.SuccessCommand command) {
        if (!execution.idempotencyKey().equals(command.idempotencyKey())
                || !execution.parameterDigest().equals(command.parameterDigest())) {
            conflict("execution parameters do not match the approved intent");
        }
    }

    private void lockRequest(String executorId, String operation, String requestId) {
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                executorId + "\n" + operation + "\n" + requestId);
    }

    private List<SuccessReplay> successReplay(String executorId, String requestId) {
        return jdbc.query(
                "select q.parameter_digest, r.execution_id, r.attempt_id, r.compensation_method, r.amount, "
                        + "r.customer_message from compensation_success_request q "
                        + "join compensation_execution_result r on r.execution_id = q.execution_id "
                        + "where q.executor_id = ? and q.request_id = ?",
                (rs, row) -> new SuccessReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        rs.getString(4), rs.getBigDecimal(5), rs.getString(6)),
                executorId, requestId);
    }

    private SuccessReplay result(UUID executionId, String requestDigest) {
        return jdbc.queryForObject(
                "select ?, execution_id, attempt_id, compensation_method, amount, customer_message "
                        + "from compensation_execution_result where execution_id = ?",
                (rs, row) -> new SuccessReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        rs.getString(4), rs.getBigDecimal(5), rs.getString(6)),
                requestDigest, executionId);
    }

    private void recordSuccessRequest(
            CompensationExecutionModels.SuccessCommand command, String requestDigest, UUID attemptId) {
        jdbc.update(
                "insert into compensation_success_request "
                        + "(executor_id, request_id, parameter_digest, execution_id, attempt_id, created_at) "
                        + "values (?, ?, ?, ?, ?, ?)",
                command.executorId(), command.requestId(), requestDigest, command.executionId(), attemptId,
                Timestamp.from(clock.instant()));
    }

    private void appendCustomerResult(UUID ticketId, String message, Instant now, Timestamp at) {
        Long messageSequence = jdbc.queryForObject(
                "select coalesce(max(message_sequence), 0) + 1 from public_message where ticket_id = ?",
                Long.class, ticketId);
        Long eventSequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                Long.class, ticketId, CUSTOMER_PUBLIC_EPOCH);
        jdbc.update(
                "insert into public_message (id, ticket_id, message_sequence, author, body, sent_at) "
                        + "values (?, ?, ?, 'SUPPORT', ?, ?)",
                UUID.randomUUID(), ticketId, messageSequence, message, at);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, 'PUBLIC_MESSAGE_APPENDED', "
                        + "jsonb_build_object('author', 'SUPPORT', 'body', ?, 'sentAt', ?::text), ?), "
                        + "(?, ?, ?, 'TICKET_RESOLVED', jsonb_build_object('lifecycleState', 'RESOLVED'), ?)",
                ticketId, CUSTOMER_PUBLIC_EPOCH, eventSequence, message, now.toString(), at,
                ticketId, CUSTOMER_PUBLIC_EPOCH, eventSequence + 1, at);
    }

    private static String customerMessage(String method, BigDecimal amount, String maskedDestination) {
        String formatted = amount.setScale(2).toPlainString();
        if ("COUPON".equals(method)) return "已发放 " + formatted + " CNY 优惠券。";
        return "已完成 " + formatted + " CNY 模拟部分退款，退回" + maskedDestination + "。";
    }

    private static CompensationExecutionModels.ClaimResult claimResult(ClaimReplay replay, boolean replayed) {
        return new CompensationExecutionModels.ClaimResult(
                replay.executionId(), replay.attemptId(), replay.status(), replay.idempotencyKey(),
                replay.executionDigest(), replay.method(), replay.amount(), replayed);
    }

    private static UUID stableUuid(String value) {
        return UUID.nameUUIDFromBytes(value.getBytes(StandardCharsets.UTF_8));
    }

    private static void conflict(String message) {
        throw new ResponseStatusException(HttpStatus.CONFLICT, message);
    }

    private record ExecutionRow(
            UUID id, UUID reservationId, String orderReference, String method, BigDecimal amount,
            String status, String idempotencyKey, String parameterDigest, UUID processingAttemptId) {}

    private record ClaimReplay(
            String requestDigest, UUID executionId, UUID attemptId, String status, String idempotencyKey,
            String executionDigest, String method, BigDecimal amount) {}

    private record SuccessReplay(
            String requestDigest, UUID executionId, UUID attemptId, String method,
            BigDecimal amount, String customerMessage) {
        CompensationExecutionModels.SuccessResult result(boolean replayed) {
            return new CompensationExecutionModels.SuccessResult(
                    executionId, attemptId, "SUCCEEDED", method, amount, customerMessage, replayed);
        }
    }
}
