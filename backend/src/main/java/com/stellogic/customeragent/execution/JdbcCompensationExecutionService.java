package com.stellogic.customeragent.execution;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
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
    private static final String CONFIRMING_MESSAGE = "补偿结果正在自动确认中，请勿重复提交。";
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TicketAuthorityLock authorityLock;
    private final CustomerPublicProjectionAppender publicProjection;

    JdbcCompensationExecutionService(
            JdbcTemplate jdbc,
            Clock clock,
            TicketAuthorityLock authorityLock,
            CustomerPublicProjectionAppender publicProjection) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.authorityLock = authorityLock;
        this.publicProjection = publicProjection;
    }

    @Override
    @Transactional(readOnly = true)
    public List<CompensationExecutionModels.Assignment> assignments(String executorId) {
        return jdbc.query(
                "select id, compensation_method, amount, status, idempotency_key from compensation_execution "
                        + "where assigned_executor_id = ? and (status in ('READY', 'PROCESSING') "
                        + "or (status = 'UNKNOWN' and reconciliation_count < 3)) "
                        + "order by created_at, id",
                (rs, row) -> new CompensationExecutionModels.Assignment(
                        rs.getObject(1, UUID.class), method(rs.getString(2)), rs.getBigDecimal(3),
                        status(rs.getString(4)), rs.getString(5)),
                executorId);
    }

    @Override
    @Transactional
    public CompensationExecutionModels.ClaimResult claim(CompensationExecutionModels.ClaimCommand command) {
        String requestDigest = StableParameterDigest.sha256(command.executionId().toString());
        lockRequest(command.executorId(), "CLAIM", command.requestId());
        List<ClaimReplay> replays = jdbc.query(
                "select q.parameter_digest, e.id, q.attempt_id, e.status, e.idempotency_key, "
                        + "e.parameter_digest, e.compensation_method, e.amount "
                        + "from compensation_claim_request q join compensation_execution e on e.id = q.execution_id "
                        + "where q.executor_id = ? and q.request_id = ?",
                (rs, row) -> new ClaimReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        status(rs.getString(4)), rs.getString(5), rs.getString(6),
                        method(rs.getString(7)), rs.getBigDecimal(8)),
                command.executorId(), command.requestId());
        if (!replays.isEmpty()) {
            ClaimReplay replay = replays.getFirst();
            if (!requestDigest.equals(replay.requestDigest())) conflict("delivery identity conflict");
            return claimResult(replay, true);
        }

        ExecutionRow execution = lockExecution(command.executionId(), command.executorId());
        if (execution.status() != CompensationExecutionModels.ExecutionStatus.READY) {
            if (execution.status() == CompensationExecutionModels.ExecutionStatus.SUCCEEDED) {
                UUID attemptId = jdbc.queryForObject(
                        "select attempt_id from compensation_execution_result where execution_id = ?",
                        UUID.class, command.executionId());
                recordClaimRequest(command, requestDigest, attemptId);
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
                        + "(id, execution_id, executor_id, delivery_request_id, parameter_digest, started_at, attempt_type) "
                        + "values (?, ?, ?, ?, ?, ?, 'EXECUTION')",
                attemptId, execution.id(), command.executorId(), command.requestId(), requestDigest, now);
        jdbc.update(
                "update compensation_execution set status = 'PROCESSING', processing_attempt_id = ? "
                        + "where id = ? and status = 'READY'",
                attemptId, execution.id());
        recordClaimRequest(command, requestDigest, attemptId);
        return new CompensationExecutionModels.ClaimResult(
                execution.id(), attemptId, CompensationExecutionModels.ExecutionStatus.PROCESSING,
                execution.idempotencyKey(),
                execution.parameterDigest(), execution.method(), execution.amount(), false);
    }

    @Override
    @Transactional
    public CompensationExecutionModels.SuccessResult succeed(CompensationExecutionModels.SuccessCommand command) {
        CompensationExecutionModels.BoundAttempt attempt = command.attempt();
        String requestDigest = StableParameterDigest.sha256(
                command.executionId().toString(), attempt.attemptId().toString(),
                attempt.idempotencyKey(), attempt.parameterDigest());
        lockRequest(command.executorId(), "SUCCESS", command.requestId());
        List<SuccessReplay> replays = successReplay(command.executorId(), command.requestId());
        if (!replays.isEmpty()) {
            SuccessReplay replay = replays.getFirst();
            if (!requestDigest.equals(replay.requestDigest())) conflict("result identity conflict");
            return replay.result(true);
        }

        UUID ticketId = ticketId(command.executionId(), command.executorId());
        authorityLock.acquire(ticketId);
        ExecutionRow execution = lockExecution(command.executionId(), command.executorId());
        requireBoundParameters(execution, attempt);
        requireProviderSuccess(execution);
        if (execution.status() == CompensationExecutionModels.ExecutionStatus.SUCCEEDED) {
            SuccessReplay result = result(command.executionId(), requestDigest);
            recordSuccessRequest(command, requestDigest, result.attemptId());
            return result.result(true);
        }
        if (execution.status() != CompensationExecutionModels.ExecutionStatus.PROCESSING
                || !attempt.attemptId().equals(execution.processingAttemptId())) {
            conflict("execution is not held by this attempt");
        }
        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        String maskedDestination = execution.method() == CompensationExecutionModels.CompensationMethod.SIMULATED_PARTIAL_REFUND
                ? "原支付方式（尾号 4242）" : null;
        String customerMessage = customerMessage(execution.method(), execution.amount(), maskedDestination);
        String resultReference = (execution.method() == CompensationExecutionModels.CompensationMethod.COUPON
                ? "coupon:" : "simulated-refund:")
                + execution.id();
        if (execution.method() == CompensationExecutionModels.CompensationMethod.COUPON) {
            jdbc.update(
                    "insert into simulated_coupon (execution_id, coupon_id, amount, issued_at) values (?, ?, ?, ?)",
                    execution.id(), resultReference, execution.amount(), at);
        } else {
            jdbc.update(
                    "insert into simulated_partial_refund "
                            + "(execution_id, refund_id, amount, masked_destination, completed_at) "
                            + "values (?, ?, ?, ?, ?)",
                    execution.id(), resultReference, execution.amount(), maskedDestination, at);
        }
        jdbc.update(
                "insert into compensation_execution_result (execution_id, attempt_id, result_reference, "
                        + "compensation_method, amount, masked_destination, customer_message, confirmed_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?)",
                execution.id(), attempt.attemptId(), resultReference, execution.method().name(), execution.amount(),
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
        publicProjection.appendSupportMessageAndResolutionEvent(ticketId, customerMessage, now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                        + "values (?, 'COMPENSATION_EXECUTION_SUCCEEDED', ?, ?, 'COMPENSATION_EXECUTION', ?), "
                        + "(?, 'TICKET_RESOLVED', 'spring-system', ?, 'COMPENSATION_EXECUTION', ?)",
                ticketId, command.executorId(), at, execution.id(), ticketId, at, execution.id());
        recordSuccessRequest(command, requestDigest, attempt.attemptId());
        return new CompensationExecutionModels.SuccessResult(
                execution.id(), attempt.attemptId(), CompensationExecutionModels.ExecutionStatus.SUCCEEDED,
                execution.method(), execution.amount(),
                customerMessage, false);
    }

    @Override
    @Transactional
    public CompensationExecutionModels.TransitionResult markUnknown(
            CompensationExecutionModels.UnknownCommand command) {
        CompensationExecutionModels.BoundAttempt attempt = command.attempt();
        String requestDigest = StableParameterDigest.sha256(
                command.executionId().toString(), attempt.attemptId().toString(),
                attempt.idempotencyKey(), attempt.parameterDigest());
        lockRequest(command.executorId(), "UNKNOWN", command.requestId());
        List<TransitionReplay> replays = transitionReplay(
                "compensation_unknown_request", command.executorId(), command.requestId());
        if (!replays.isEmpty()) {
            TransitionReplay replay = replays.getFirst();
            if (!requestDigest.equals(replay.requestDigest())) conflict("unknown identity conflict");
            return replay.result(CONFIRMING_MESSAGE, true);
        }

        UUID ticketId = ticketId(command.executionId(), command.executorId());
        authorityLock.acquire(ticketId);
        ExecutionRow execution = lockExecution(command.executionId(), command.executorId());
        requireBoundParameters(execution, attempt);
        if (execution.status() != CompensationExecutionModels.ExecutionStatus.PROCESSING
                || !attempt.attemptId().equals(execution.processingAttemptId())) {
            conflict("execution is not held by this attempt");
        }
        Timestamp at = Timestamp.from(clock.instant());
        jdbc.update("update compensation_execution set status = 'UNKNOWN', unknown_at = ? where id = ?",
                at, execution.id());
        jdbc.update("update compensation_execution_attempt set outcome = 'UNKNOWN', completed_at = ? where id = ?",
                at, attempt.attemptId());
        jdbc.update(
                "insert into compensation_unknown_request "
                        + "(executor_id, request_id, parameter_digest, execution_id, attempt_id, created_at) "
                        + "values (?, ?, ?, ?, ?, ?)",
                command.executorId(), command.requestId(), requestDigest, execution.id(), attempt.attemptId(), at);
        publicProjection.appendSupportMessage(ticketId, CONFIRMING_MESSAGE, clock.instant());
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                        + "values (?, 'COMPENSATION_EXECUTION_UNKNOWN', ?, ?, 'COMPENSATION_EXECUTION', ?)",
                ticketId, command.executorId(), at, execution.id());
        return new CompensationExecutionModels.TransitionResult(
                execution.id(), attempt.attemptId(), CompensationExecutionModels.ExecutionStatus.UNKNOWN,
                CONFIRMING_MESSAGE, false);
    }

    @Override
    @Transactional
    public CompensationExecutionModels.TransitionResult markFailed(
            CompensationExecutionModels.FailureCommand command) {
        CompensationExecutionModels.BoundAttempt attempt = command.attempt();
        String requestDigest = StableParameterDigest.sha256(
                command.executionId().toString(), attempt.attemptId().toString(),
                attempt.idempotencyKey(), attempt.parameterDigest());
        lockRequest(command.executorId(), "FAILURE", command.requestId());
        List<TransitionReplay> replays = transitionReplay(
                "compensation_failure_request", command.executorId(), command.requestId());
        if (!replays.isEmpty()) {
            TransitionReplay replay = replays.getFirst();
            if (!requestDigest.equals(replay.requestDigest())) conflict("failure identity conflict");
            return replay.result(null, true);
        }

        UUID ticketId = ticketId(command.executionId(), command.executorId());
        authorityLock.acquire(ticketId);
        ExecutionRow execution = lockExecution(command.executionId(), command.executorId());
        requireBoundParameters(execution, attempt);
        if (execution.status() != CompensationExecutionModels.ExecutionStatus.PROCESSING
                || !attempt.attemptId().equals(execution.processingAttemptId())) {
            conflict("execution is not held by this attempt");
        }
        Integer confirmedNotOccurred = jdbc.queryForObject(
                "select count(*) from simulated_compensation_provider_operation "
                        + "where execution_id = ? and idempotency_key = ? and parameter_digest = ? "
                        + "and scenario = 'BEFORE_EFFECT_FAILURE' and effect_status = 'NOT_OCCURRED'",
                Integer.class, execution.id(), execution.idempotencyKey(), execution.parameterDigest());
        if (confirmedNotOccurred == null || confirmedNotOccurred != 1) {
            conflict("provider has not confirmed that no compensation occurred");
        }
        Timestamp at = Timestamp.from(clock.instant());
        jdbc.update("update compensation_execution set status = 'FAILED', failed_at = ? where id = ?",
                at, execution.id());
        jdbc.update("update compensation_execution_attempt set outcome = 'NOT_FOUND', completed_at = ? where id = ?",
                at, attempt.attemptId());
        jdbc.update("update compensation_reservation set status = 'RELEASED' where id = ? and status = 'ACTIVE'",
                execution.reservationId());
        jdbc.update(
                "insert into compensation_failure_request "
                        + "(executor_id, request_id, parameter_digest, execution_id, attempt_id, created_at) "
                        + "values (?, ?, ?, ?, ?, ?)",
                command.executorId(), command.requestId(), requestDigest, execution.id(), attempt.attemptId(), at);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                        + "values (?, 'COMPENSATION_EXECUTION_CONFIRMED_NOT_OCCURRED', ?, ?, "
                        + "'COMPENSATION_EXECUTION', ?)",
                ticketId, command.executorId(), at, execution.id());
        return new CompensationExecutionModels.TransitionResult(
                execution.id(), attempt.attemptId(), CompensationExecutionModels.ExecutionStatus.FAILED,
                null, false);
    }

    @Override
    @Transactional
    public CompensationExecutionModels.TransitionResult reconcile(
            CompensationExecutionModels.ReconciliationCommand command) {
        String requestDigest = StableParameterDigest.sha256(
                command.executionId().toString(), command.queryId(), command.outcome().name(),
                command.resultReference() == null ? "" : command.resultReference());
        lockRequest(command.executorId(), "RECONCILE", command.requestId());
        List<TransitionReplay> replays = transitionReplay(
                "compensation_reconciliation_request", command.executorId(), command.requestId());
        if (!replays.isEmpty()) {
            TransitionReplay replay = replays.getFirst();
            if (!requestDigest.equals(replay.requestDigest())) conflict("reconciliation identity conflict");
            return replay.result(customerMessageFor(replay.executionId(), replay.status()), true);
        }
        List<TransitionReplay> queryReplays = jdbc.query(
                "select q.parameter_digest, q.execution_id, q.attempt_id, e.status "
                        + "from compensation_reconciliation_request q "
                        + "join compensation_execution e on e.id = q.execution_id "
                        + "where q.executor_id = ? and q.query_id = ?",
                (rs, row) -> new TransitionReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        status(rs.getString(4))),
                command.executorId(), command.queryId());
        if (!queryReplays.isEmpty()) {
            TransitionReplay replay = queryReplays.getFirst();
            if (!requestDigest.equals(replay.requestDigest())) conflict("provider query identity conflict");
            return replay.result(customerMessageFor(replay.executionId(), replay.status()), true);
        }

        UUID ticketId = ticketId(command.executionId(), command.executorId());
        authorityLock.acquire(ticketId);
        ExecutionRow execution = lockExecution(command.executionId(), command.executorId());
        if (execution.status() != CompensationExecutionModels.ExecutionStatus.UNKNOWN) {
            conflict("only an unknown execution can be reconciled");
        }
        if (execution.reconciliationCount() >= 3) {
            conflict("reconciliation budget is exhausted");
        }
        requireProviderQuery(command);
        if (command.outcome() == CompensationExecutionModels.ReconciliationOutcome.FOUND
                && !expectedResultReference(execution).equals(command.resultReference())) {
            conflict("provider result does not match this execution");
        }

        UUID attemptId = stableUuid(command.executorId() + "\nRECONCILE\n" + command.requestId());
        Timestamp at = Timestamp.from(clock.instant());
        jdbc.update(
                "insert into compensation_execution_attempt "
                        + "(id, execution_id, executor_id, delivery_request_id, parameter_digest, started_at, "
                        + "attempt_type, outcome, completed_at) values (?, ?, ?, ?, ?, ?, 'RECONCILIATION', ?, ?)",
                attemptId, execution.id(), command.executorId(), command.requestId(), requestDigest, at,
                command.outcome().name(), at);
        CompensationExecutionModels.ExecutionStatus status;
        String customerMessage = null;
        if (command.outcome() == CompensationExecutionModels.ReconciliationOutcome.FOUND) {
            jdbc.update(
                    "update compensation_execution set status = 'PROCESSING', processing_attempt_id = ?, "
                            + "reconciliation_count = reconciliation_count + 1 where id = ?",
                    attemptId, execution.id());
            CompensationExecutionModels.SuccessResult success = succeed(
                    new CompensationExecutionModels.SuccessCommand(
                            command.executorId(), execution.id(), command.requestId(),
                            new CompensationExecutionModels.BoundAttempt(
                                    attemptId, execution.idempotencyKey(), execution.parameterDigest())));
            status = success.status();
            customerMessage = success.customerMessage();
        } else if (command.outcome() == CompensationExecutionModels.ReconciliationOutcome.NOT_FOUND) {
            jdbc.update(
                    "update compensation_execution set status = 'FAILED', failed_at = ?, "
                            + "reconciliation_count = reconciliation_count + 1 where id = ?",
                    at, execution.id());
            jdbc.update("update compensation_reservation set status = 'RELEASED' where id = ? and status = 'ACTIVE'",
                    execution.reservationId());
            status = CompensationExecutionModels.ExecutionStatus.FAILED;
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                            + "values (?, 'COMPENSATION_EXECUTION_CONFIRMED_NOT_OCCURRED', ?, ?, "
                            + "'COMPENSATION_EXECUTION', ?)",
                    ticketId, command.executorId(), at, execution.id());
        } else {
            jdbc.update(
                    "update compensation_execution set reconciliation_count = reconciliation_count + 1 where id = ?",
                    execution.id());
            Integer attempts = jdbc.queryForObject(
                    "select reconciliation_count from compensation_execution where id = ?", Integer.class,
                    execution.id());
            if (attempts != null && attempts >= 3) {
                jdbc.update(
                        "insert into domain_operation_alert (id, execution_id, alert_type, created_at) "
                                + "values (?, ?, 'COMPENSATION_RECONCILIATION_EXHAUSTED', ?) "
                                + "on conflict (execution_id, alert_type) do nothing",
                        stableUuid("reconciliation-alert\n" + execution.id()), execution.id(), at);
            }
            status = CompensationExecutionModels.ExecutionStatus.UNKNOWN;
            customerMessage = CONFIRMING_MESSAGE;
        }
        jdbc.update(
                "insert into compensation_reconciliation_request "
                        + "(executor_id, request_id, parameter_digest, execution_id, attempt_id, query_id, outcome, "
                        + "result_reference, created_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                command.executorId(), command.requestId(), requestDigest, execution.id(), attemptId,
                command.queryId(), command.outcome().name(), command.resultReference(), at);
        return new CompensationExecutionModels.TransitionResult(
                execution.id(), attemptId, status, customerMessage, false);
    }

    private ExecutionRow lockExecution(UUID executionId, String executorId) {
        List<ExecutionRow> executions = jdbc.query(
                "select id, reservation_id, order_reference, compensation_method, amount, status, "
                        + "idempotency_key, parameter_digest, processing_attempt_id, reconciliation_count "
                        + "from compensation_execution where id = ? and assigned_executor_id = ? for update",
                (rs, row) -> new ExecutionRow(
                        rs.getObject(1, UUID.class), rs.getObject(2, UUID.class), rs.getString(3),
                        method(rs.getString(4)), rs.getBigDecimal(5), status(rs.getString(6)), rs.getString(7),
                        rs.getString(8), rs.getObject(9, UUID.class), rs.getInt(10)),
                executionId, executorId);
        if (executions.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "assigned execution not found");
        }
        return executions.getFirst();
    }

    private UUID ticketId(UUID executionId, String executorId) {
        List<UUID> tickets = jdbc.query(
                "select p.ticket_id from compensation_execution e "
                        + "join compensation_proposal_revision p on p.id = e.proposal_revision_id "
                        + "where e.id = ? and e.assigned_executor_id = ?",
                (rs, row) -> rs.getObject(1, UUID.class), executionId, executorId);
        if (tickets.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "assigned execution not found");
        }
        return tickets.getFirst();
    }

    private List<TransitionReplay> transitionReplay(String table, String executorId, String requestId) {
        return jdbc.query(
                "select q.parameter_digest, q.execution_id, q.attempt_id, e.status from " + table + " q "
                        + "join compensation_execution e on e.id = q.execution_id "
                        + "where q.executor_id = ? and q.request_id = ?",
                (rs, row) -> new TransitionReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        status(rs.getString(4))),
                executorId, requestId);
    }

    private String customerMessageFor(UUID executionId, CompensationExecutionModels.ExecutionStatus status) {
        if (status == CompensationExecutionModels.ExecutionStatus.UNKNOWN) return CONFIRMING_MESSAGE;
        if (status != CompensationExecutionModels.ExecutionStatus.SUCCEEDED) return null;
        return jdbc.queryForObject(
                "select customer_message from compensation_execution_result where execution_id = ?",
                String.class, executionId);
    }

    private static String expectedResultReference(ExecutionRow execution) {
        return (execution.method() == CompensationExecutionModels.CompensationMethod.COUPON
                ? "coupon:" : "simulated-refund:") + execution.id();
    }

    private void requireBoundParameters(ExecutionRow execution, CompensationExecutionModels.BoundAttempt attempt) {
        if (!execution.idempotencyKey().equals(attempt.idempotencyKey())
                || !execution.parameterDigest().equals(attempt.parameterDigest())) {
            conflict("execution parameters do not match the approved intent");
        }
    }

    private void requireProviderSuccess(ExecutionRow execution) {
        if (execution.method() != CompensationExecutionModels.CompensationMethod.SIMULATED_PARTIAL_REFUND) return;
        Integer matches = jdbc.queryForObject(
                "select count(*) from simulated_compensation_provider_operation "
                        + "where execution_id = ? and idempotency_key = ? and parameter_digest = ? "
                        + "and amount = ? and effect_status = 'SUCCEEDED'",
                Integer.class, execution.id(), execution.idempotencyKey(), execution.parameterDigest(),
                execution.amount());
        if (matches == null || matches != 1) {
            conflict("provider has not confirmed this compensation");
        }
    }

    private void requireProviderQuery(CompensationExecutionModels.ReconciliationCommand command) {
        Integer matches = jdbc.queryForObject(
                "select count(*) from simulated_compensation_provider_query "
                        + "where query_id = ? and execution_id = ? and outcome = ? "
                        + "and result_reference is not distinct from ?",
                Integer.class, command.queryId(), command.executionId(), command.outcome().name(),
                command.resultReference());
        if (matches == null || matches != 1) {
            conflict("reconciliation does not match an authoritative provider query");
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
                        method(rs.getString(4)), rs.getBigDecimal(5), rs.getString(6)),
                executorId, requestId);
    }

    private SuccessReplay result(UUID executionId, String requestDigest) {
        return jdbc.queryForObject(
                "select ?, execution_id, attempt_id, compensation_method, amount, customer_message "
                        + "from compensation_execution_result where execution_id = ?",
                (rs, row) -> new SuccessReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        method(rs.getString(4)), rs.getBigDecimal(5), rs.getString(6)),
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

    private void recordClaimRequest(
            CompensationExecutionModels.ClaimCommand command, String requestDigest, UUID attemptId) {
        jdbc.update(
                "insert into compensation_claim_request "
                        + "(executor_id, request_id, parameter_digest, execution_id, attempt_id, created_at) "
                        + "values (?, ?, ?, ?, ?, ?)",
                command.executorId(), command.requestId(), requestDigest, command.executionId(), attemptId,
                Timestamp.from(clock.instant()));
    }

    private static String customerMessage(
            CompensationExecutionModels.CompensationMethod method,
            BigDecimal amount,
            String maskedDestination) {
        String formatted = amount.setScale(2).toPlainString();
        if (method == CompensationExecutionModels.CompensationMethod.COUPON) {
            return "已发放 " + formatted + " CNY 优惠券。";
        }
        return "已完成 " + formatted + " CNY 模拟部分退款，退回" + maskedDestination + "。";
    }

    private static CompensationExecutionModels.ExecutionStatus status(String value) {
        return CompensationExecutionModels.ExecutionStatus.valueOf(value);
    }

    private static CompensationExecutionModels.CompensationMethod method(String value) {
        return CompensationExecutionModels.CompensationMethod.valueOf(value);
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
            UUID id, UUID reservationId, String orderReference,
            CompensationExecutionModels.CompensationMethod method, BigDecimal amount,
            CompensationExecutionModels.ExecutionStatus status, String idempotencyKey,
            String parameterDigest, UUID processingAttemptId, int reconciliationCount) {}

    private record ClaimReplay(
            String requestDigest, UUID executionId, UUID attemptId,
            CompensationExecutionModels.ExecutionStatus status, String idempotencyKey,
            String executionDigest, CompensationExecutionModels.CompensationMethod method, BigDecimal amount) {}

    private record SuccessReplay(
            String requestDigest, UUID executionId, UUID attemptId,
            CompensationExecutionModels.CompensationMethod method,
            BigDecimal amount, String customerMessage) {
        CompensationExecutionModels.SuccessResult result(boolean replayed) {
            return new CompensationExecutionModels.SuccessResult(
                    executionId, attemptId, CompensationExecutionModels.ExecutionStatus.SUCCEEDED,
                    method, amount, customerMessage, replayed);
        }
    }

    private record TransitionReplay(
            String requestDigest,
            UUID executionId,
            UUID attemptId,
            CompensationExecutionModels.ExecutionStatus status) {
        CompensationExecutionModels.TransitionResult result(String customerMessage, boolean replayed) {
            return new CompensationExecutionModels.TransitionResult(
                    executionId, attemptId, status, customerMessage, replayed);
        }
    }
}
