package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
class IntakeAssistanceService {
    static final String EPOCH = "intake-assistance-v1";
    private static final Duration CLAIM_DURATION = Duration.ofMinutes(15);
    private static final List<String> ALLOWED_ISSUE_KINDS =
            List.of(
                    "LOGISTICS_DELAY",
                    "PACKAGE_NOT_RECEIVED",
                    "DUPLICATE_CHARGE",
                    "ORDER_OPERATION_OR_RULE",
                    "OTHER");
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final ObjectMapper json;

    IntakeAssistanceService(JdbcTemplate jdbc, Clock clock, ObjectMapper json) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.json = json;
    }

    @Transactional(isolation = Isolation.REPEATABLE_READ)
    IntakeAssistanceSnapshot snapshot(String supportId) {
        requireSupport(supportId);
        expireClaims();
        List<IntakeAssistanceQueueItem> requests =
                jdbc.query(
                        "select id, status, reason_code, requested_at, claim_expires_at, "
                                + "coalesce(support_id = ?, false) from intake_assistance_request "
                                + "where status <> 'COMPLETED' order by requested_at, id",
                        (rs, row) ->
                                new IntakeAssistanceQueueItem(
                                        rs.getObject(1, UUID.class),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getTimestamp(4).toInstant(),
                                        instant(rs.getTimestamp(5)),
                                        rs.getBoolean(6)),
                        supportId);
        Long sequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) from intake_assistance_event where epoch = ?",
                        Long.class,
                        EPOCH);
        return new IntakeAssistanceSnapshot(EPOCH, sequence == null ? 0 : sequence, requests);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    List<IntakeAssistanceEvent> events(String supportId, String afterCursor) {
        requireSupport(supportId);
        long after = parseCursor(afterCursor);
        Long latest =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) from intake_assistance_event where epoch = ?",
                        Long.class,
                        EPOCH);
        if (after < 0 || latest == null || after > latest) {
            throw new IntakeAssistanceCursorException();
        }
        Long first =
                jdbc.queryForObject(
                        "select min(sequence) from intake_assistance_event where epoch = ?",
                        Long.class,
                        EPOCH);
        if (after < latest && first != null && first > after + 1) {
            throw new IntakeAssistanceCursorException();
        }
        return jdbc.query(
                "select epoch, sequence, event_type, payload::text from intake_assistance_event "
                        + "where epoch = ? and sequence > ? order by sequence",
                (rs, row) ->
                        new IntakeAssistanceEvent(
                                rs.getString(1), rs.getLong(2), rs.getString(3), rs.getString(4)),
                EPOCH,
                after);
    }

    @Transactional
    IntakeAssistanceClaim claim(String supportId, UUID requestId) {
        requireSupport(supportId);
        AssistanceRow row = lock(requestId);
        Instant now = clock.instant();
        if (expired(row, now)) {
            queueExpired(row.id(), now);
            row = lock(requestId);
        }
        if (supportId.equals(row.supportId())
                && List.of("CLAIMED", "WAITING_FOR_CUSTOMER").contains(row.status())) {
            return new IntakeAssistanceClaim(requestId, row.status(), row.claimExpiresAt(), true);
        }
        if (!"QUEUED".equals(row.status())) throw new IntakeAssistanceNotFoundException();
        Instant expiresAt = now.plus(CLAIM_DURATION);
        jdbc.update(
                "update intake_assistance_request set status = 'CLAIMED', support_id = ?, "
                        + "claimed_at = ?, claim_expires_at = ?, version = version + 1 where id = ?",
                supportId,
                timestamp(now),
                timestamp(expiresAt),
                requestId);
        appendUpsert(requestId, "CLAIMED", now);
        return new IntakeAssistanceClaim(requestId, "CLAIMED", expiresAt, false);
    }

    @Transactional
    IntakeAssistanceMutation release(String supportId, UUID requestId) {
        AssistanceRow row = requireCurrentClaim(supportId, requestId);
        long intakeVersion = intakeVersion(row.intakeId());
        Instant now = clock.instant();
        jdbc.update(
                "update intake_assistance_request set status = 'QUEUED', support_id = null, "
                        + "claimed_at = null, claim_expires_at = null, version = version + 1 where id = ?",
                requestId);
        appendUpsert(requestId, "QUEUED", now);
        return new IntakeAssistanceMutation(requestId, "QUEUED", intakeVersion, null, false);
    }

    @Transactional
    IntakeAssistanceDetails details(String supportId, UUID requestId) {
        AssistanceRow row = requireCurrentClaim(supportId, requestId);
        List<IntakeDetailRow> intakes =
                jdbc.query(
                        "select customer_id, original_message, candidate_order_reference, version "
                                + "from customer_intake where id = ?",
                        (rs, number) ->
                                new IntakeDetailRow(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getLong(4)),
                        row.intakeId());
        if (intakes.isEmpty()) throw new IntakeAssistanceNotFoundException();
        IntakeDetailRow intake = intakes.getFirst();
        List<IntakeAssistanceOrderCandidate> candidates =
                jdbc.query(
                        "select order_reference, paid, cancelled, fully_refunded from synthetic_order "
                                + "where customer_id = ? order by order_reference",
                        (rs, number) ->
                                new IntakeAssistanceOrderCandidate(
                                        rs.getString(1),
                                        rs.getBoolean(3)
                                                ? "已取消的合成订单"
                                                : rs.getBoolean(4)
                                                        ? "已退款的合成订单"
                                                        : rs.getBoolean(2)
                                                                ? "配送中的合成订单"
                                                                : "待支付的合成订单"),
                        intake.customerId());
        List<ProposedIntakeIssue> issues =
                jdbc.query(
                        "select issue_kind, issue_summary from customer_intake_issue "
                                + "where intake_id = ? order by ordinal",
                        (rs, number) -> new ProposedIntakeIssue(rs.getString(1), rs.getString(2)),
                        row.intakeId());
        return new IntakeAssistanceDetails(
                requestId,
                row.intakeId(),
                row.status(),
                row.reasonCode(),
                intake.originalMessage(),
                candidates,
                intake.orderReference(),
                issues,
                intake.version(),
                row.claimExpiresAt());
    }

    @Transactional
    IntakeAssistanceMutation propose(IntakeAssistanceProposalCommand command) {
        requireProposal(command);
        AssistanceRow assistance = requireCurrentClaim(command.supportId(), command.requestId());
        String digest =
                StableParameterDigest.sha256(
                        Long.toString(command.expectedIntakeVersion()),
                        command.orderReference(),
                        command.issues().toString());
        List<ProposalIdentity> prior =
                jdbc.query(
                        "select request_digest, resulting_intake_version "
                                + "from intake_assistance_proposal_request "
                                + "where assistance_request_id = ? and request_key = ?",
                        (rs, row) -> new ProposalIdentity(rs.getString(1), rs.getLong(2)),
                        command.requestId(),
                        command.requestKey());
        if (!prior.isEmpty()) {
            ProposalIdentity identity = prior.getFirst();
            if (!identity.digest().equals(digest)) throw new IntakeAssistanceConflictException();
            return new IntakeAssistanceMutation(
                    command.requestId(),
                    assistance.status(),
                    identity.intakeVersion(),
                    assistance.claimExpiresAt(),
                    true);
        }
        IntakeDetailRow intake = lockIntake(assistance.intakeId());
        if (intake.version() != command.expectedIntakeVersion()) {
            throw new IntakeAssistanceConflictException();
        }
        List<OrderShape> order =
                jdbc.query(
                        "select order_reference, paid, cancelled, fully_refunded, delay_seconds, policy_version "
                                + "from synthetic_order where customer_id = ? and order_reference = ?",
                        (rs, row) ->
                                new OrderShape(
                                        rs.getString(1),
                                        rs.getBoolean(2),
                                        rs.getBoolean(3),
                                        rs.getBoolean(4),
                                        rs.getLong(5),
                                        rs.getString(6)),
                        intake.customerId(),
                        command.orderReference());
        if (order.isEmpty()) throw new IntakeAssistanceConflictException();
        OrderShape selected = order.getFirst();
        String summary =
                selected.cancelled()
                        ? "已取消的合成订单"
                        : selected.refunded()
                                ? "已退款的合成订单"
                                : selected.paid() ? "配送中的合成订单" : "待支付的合成订单";
        String version =
                StableParameterDigest.sha256(
                        selected.reference(),
                        Boolean.toString(selected.paid()),
                        Boolean.toString(selected.cancelled()),
                        Boolean.toString(selected.refunded()),
                        Long.toString(selected.delaySeconds()),
                        selected.policyVersion());
        List<ProposedIntakeIssue> previousIssues =
                jdbc.query(
                        "select issue_kind, issue_summary from customer_intake_issue "
                                + "where intake_id = ? order by ordinal",
                        (rs, row) -> new ProposedIntakeIssue(rs.getString(1), rs.getString(2)),
                        assistance.intakeId());
        jdbc.update("delete from customer_intake_issue where intake_id = ?", assistance.intakeId());
        jdbc.update(
                "delete from customer_intake_pending_issue where intake_id = ?",
                assistance.intakeId());
        int ordinal = 0;
        for (ProposedIntakeIssue issue : command.issues()) {
            ordinal++;
            jdbc.update(
                    "insert into customer_intake_issue "
                            + "(intake_id, ordinal, issue_kind, issue_summary) values (?, ?, ?, ?)",
                    assistance.intakeId(),
                    ordinal,
                    issue.kind(),
                    issue.summary());
        }
        Instant now = clock.instant();
        long nextVersion = intake.version() + 1;
        jdbc.update(
                "update customer_intake set status = 'READY_TO_CONFIRM', "
                        + "candidate_order_reference = ?, candidate_order_version = ?, "
                        + "candidate_order_summary = ?, issue_kind = ?, issue_summary = ?, "
                        + "assistant_message = ?, updated_at = ?, expires_at = ?, "
                        + "version = version + 1 where id = ?",
                selected.reference(),
                version,
                summary,
                command.issues().getFirst().kind(),
                command.issues().getFirst().summary(),
                "客服已协助整理订单候选与问题集合；仍需由你确认后才会创建正式工单。",
                timestamp(now),
                timestamp(now.plus(Duration.ofDays(7))),
                assistance.intakeId());
        Instant expiresAt = now.plus(CLAIM_DURATION);
        jdbc.update(
                "update intake_assistance_request set status = 'WAITING_FOR_CUSTOMER', "
                        + "claim_expires_at = ?, version = version + 1 where id = ?",
                timestamp(expiresAt),
                command.requestId());
        jdbc.update(
                "insert into intake_assistance_proposal_request "
                        + "(assistance_request_id, request_key, request_digest, support_id, "
                        + "previous_order_reference, previous_issues, proposed_order_reference, "
                        + "proposed_issues, resulting_intake_version, created_at) "
                        + "values (?, ?, ?, ?, ?, cast(? as jsonb), ?, cast(? as jsonb), ?, ?)",
                command.requestId(),
                command.requestKey(),
                digest,
                command.supportId(),
                intake.orderReference(),
                serializeIssues(previousIssues),
                command.orderReference(),
                serializeIssues(command.issues()),
                nextVersion,
                timestamp(now));
        appendUpsert(command.requestId(), "WAITING_FOR_CUSTOMER", now);
        return new IntakeAssistanceMutation(
                command.requestId(), "WAITING_FOR_CUSTOMER", nextVersion, expiresAt, false);
    }

    @Transactional
    void createForIntake(UUID intakeId, String reasonCode) {
        Integer present =
                jdbc.queryForObject(
                        "select count(*) from intake_assistance_request "
                                + "where intake_id = ? and status <> 'COMPLETED'",
                        Integer.class,
                        intakeId);
        if (present != null && present > 0) return;
        if (!List.of(
                        "AGENT_UNAVAILABLE",
                        "TOOL_UNAVAILABLE",
                        "CUSTOMER_REQUESTED",
                        "UNSUPPORTED_REQUEST")
                .contains(reasonCode)) {
            throw new IllegalArgumentException("unsupported intake assistance reason");
        }
        UUID requestId = UUID.randomUUID();
        Instant now = clock.instant();
        jdbc.update(
                "insert into intake_assistance_request "
                        + "(id, intake_id, reason_code, status, requested_at) "
                        + "values (?, ?, ?, 'QUEUED', ?)",
                requestId,
                intakeId,
                reasonCode,
                timestamp(now));
        appendUpsert(requestId, "QUEUED", now);
    }

    @Transactional(readOnly = true)
    boolean hasOpenRequest(UUID intakeId) {
        Integer count =
                jdbc.queryForObject(
                        "select count(*) from intake_assistance_request "
                                + "where intake_id = ? and status <> 'COMPLETED'",
                        Integer.class,
                        intakeId);
        return count != null && count > 0;
    }

    @Transactional(readOnly = true)
    boolean awaitingCustomerConfirmation(UUID intakeId) {
        Integer count =
                jdbc.queryForObject(
                        "select count(*) from intake_assistance_request "
                                + "where intake_id = ? and status = 'WAITING_FOR_CUSTOMER' "
                                + "and claim_expires_at > ?",
                        Integer.class,
                        intakeId,
                        timestamp(clock.instant()));
        return count != null && count > 0;
    }

    @Transactional
    void completeForIntake(UUID intakeId) {
        List<UUID> requests =
                jdbc.queryForList(
                        "select id from intake_assistance_request "
                                + "where intake_id = ? and status <> 'COMPLETED' for update",
                        UUID.class,
                        intakeId);
        Instant now = clock.instant();
        for (UUID requestId : requests) {
            jdbc.update(
                    "update intake_assistance_request set status = 'COMPLETED', "
                            + "completed_at = ?, version = version + 1 where id = ?",
                    timestamp(now),
                    requestId);
            appendRemoved(requestId, now);
        }
    }

    private AssistanceRow requireCurrentClaim(String supportId, UUID requestId) {
        AssistanceRow row = currentClaim(supportId, requestId);
        if (!List.of("CLAIMED", "WAITING_FOR_CUSTOMER").contains(row.status())) {
            throw new IntakeAssistanceNotFoundException();
        }
        return row;
    }

    private AssistanceRow currentClaim(String supportId, UUID requestId) {
        requireSupport(supportId);
        AssistanceRow row = lock(requestId);
        if (!supportId.equals(row.supportId()) || expired(row, clock.instant())) {
            throw new IntakeAssistanceNotFoundException();
        }
        return row;
    }

    private AssistanceRow lock(UUID requestId) {
        List<AssistanceRow> rows =
                jdbc.query(
                        "select id, intake_id, reason_code, status, support_id, claim_expires_at "
                                + "from intake_assistance_request where id = ? for update",
                        (rs, row) ->
                                new AssistanceRow(
                                        rs.getObject(1, UUID.class),
                                        rs.getObject(2, UUID.class),
                                        rs.getString(3),
                                        rs.getString(4),
                                        rs.getString(5),
                                        instant(rs.getTimestamp(6))),
                        requestId);
        if (rows.isEmpty()) throw new IntakeAssistanceNotFoundException();
        return rows.getFirst();
    }

    private IntakeDetailRow lockIntake(UUID intakeId) {
        List<IntakeDetailRow> rows =
                jdbc.query(
                        "select customer_id, original_message, candidate_order_reference, version "
                                + "from customer_intake where id = ? for update",
                        (rs, row) ->
                                new IntakeDetailRow(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getLong(4)),
                        intakeId);
        if (rows.isEmpty()) throw new IntakeAssistanceNotFoundException();
        return rows.getFirst();
    }

    private long intakeVersion(UUID intakeId) {
        Long version =
                jdbc.queryForObject(
                        "select version from customer_intake where id = ?", Long.class, intakeId);
        if (version == null) throw new IntakeAssistanceNotFoundException();
        return version;
    }

    private void expireClaims() {
        List<UUID> expired =
                jdbc.queryForList(
                        "select id from intake_assistance_request where status in "
                                + "('CLAIMED', 'WAITING_FOR_CUSTOMER') and claim_expires_at <= ? for update",
                        UUID.class,
                        timestamp(clock.instant()));
        Instant now = clock.instant();
        for (UUID requestId : expired) queueExpired(requestId, now);
    }

    private void queueExpired(UUID requestId, Instant now) {
        jdbc.update(
                "update intake_assistance_request set status = 'QUEUED', support_id = null, "
                        + "claimed_at = null, claim_expires_at = null, version = version + 1 where id = ?",
                requestId);
        appendUpsert(requestId, "QUEUED", now);
    }

    private void appendUpsert(UUID requestId, String status, Instant now) {
        appendEvent(
                "ASSISTANCE_REQUEST_UPSERTED",
                "{\"requestId\":\"" + requestId + "\",\"status\":\"" + status + "\"}",
                now);
    }

    private void appendRemoved(UUID requestId, Instant now) {
        appendEvent("ASSISTANCE_REQUEST_REMOVED", "{\"requestId\":\"" + requestId + "\"}", now);
    }

    private void appendEvent(String type, String payload, Instant now) {
        jdbc.update(
                "insert into intake_assistance_event (epoch, event_type, payload, occurred_at) "
                        + "values (?, ?, cast(? as jsonb), ?)",
                EPOCH,
                type,
                payload,
                timestamp(now));
    }

    private static boolean expired(AssistanceRow row, Instant now) {
        return row.claimExpiresAt() != null && !row.claimExpiresAt().isAfter(now);
    }

    private static long parseCursor(String cursor) {
        if (cursor == null || cursor.isBlank()) return 0;
        int separator = cursor.lastIndexOf(':');
        if (separator < 1 || !EPOCH.equals(cursor.substring(0, separator))) {
            throw new IntakeAssistanceCursorException();
        }
        try {
            return Long.parseLong(cursor.substring(separator + 1));
        } catch (NumberFormatException exception) {
            throw new IntakeAssistanceCursorException();
        }
    }

    private static void requireProposal(IntakeAssistanceProposalCommand command) {
        if (command.supportId() == null
                || command.supportId().isBlank()
                || command.requestKey() == null
                || command.requestKey().isBlank()
                || command.requestKey().length() > 200
                || command.expectedIntakeVersion() <= 0
                || command.orderReference() == null
                || command.orderReference().isBlank()
                || command.issues() == null
                || command.issues().isEmpty()
                || command.issues().size() > 3) {
            throw new InvalidCustomerRequestException("受理协助修正字段无效");
        }
        HashSet<String> kinds = new HashSet<>();
        for (ProposedIntakeIssue issue : command.issues()) {
            if (issue == null
                    || !ALLOWED_ISSUE_KINDS.contains(issue.kind())
                    || !kinds.add(issue.kind())
                    || issue.summary() == null
                    || issue.summary().isBlank()
                    || issue.summary().length() > 500) {
                throw new InvalidCustomerRequestException("拟建问题无效");
            }
        }
    }

    private static void requireSupport(String supportId) {
        if (supportId == null || supportId.isBlank()) {
            throw new IntakeAssistanceNotFoundException();
        }
    }

    private String serializeIssues(List<ProposedIntakeIssue> issues) {
        try {
            return json.writeValueAsString(issues);
        } catch (JacksonException exception) {
            throw new IllegalStateException(
                    "intake assistance audit serialization failed", exception);
        }
    }

    private static Timestamp timestamp(Instant value) {
        return Timestamp.from(value);
    }

    private static Instant instant(Timestamp value) {
        return value == null ? null : value.toInstant();
    }

    private record AssistanceRow(
            UUID id,
            UUID intakeId,
            String reasonCode,
            String status,
            String supportId,
            Instant claimExpiresAt) {}

    private record IntakeDetailRow(
            String customerId, String originalMessage, String orderReference, long version) {}

    private record ProposalIdentity(String digest, long intakeVersion) {}

    private record OrderShape(
            String reference,
            boolean paid,
            boolean cancelled,
            boolean refunded,
            long delaySeconds,
            String policyVersion) {}
}
