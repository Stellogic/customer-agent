package com.stellogic.customeragent.approval;

import com.stellogic.customeragent.compensation.DelayCompensationPolicy;
import com.stellogic.customeragent.reliability.StableParameterDigest;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

@Service
class JdbcApprovalService implements ApprovalService {
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final ObjectMapper objectMapper;
    private final int defaultLeaseSeconds;
    private final int maximumLeaseSeconds;
    private final DelayCompensationPolicy policy = new DelayCompensationPolicy();

    JdbcApprovalService(
            JdbcTemplate jdbc,
            Clock clock,
            ObjectMapper objectMapper,
            @Value("${baseline.approval.default-lease-seconds:900}") int defaultLeaseSeconds,
            @Value("${baseline.approval.maximum-lease-seconds:900}") int maximumLeaseSeconds) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.objectMapper = objectMapper;
        this.defaultLeaseSeconds = defaultLeaseSeconds;
        this.maximumLeaseSeconds = maximumLeaseSeconds;
    }

    @Override
    public List<ApprovalModels.QueueItem> queue() {
        Timestamp now = Timestamp.from(clock.instant());
        return jdbc.query(
                "select p.id, p.compensation_method, p.amount, p.created_at, p.expires_at "
                        + "from compensation_proposal_revision p "
                        + "where p.status = 'PENDING_APPROVAL' and p.expires_at > ? "
                        + "and not exists (select 1 from approval_lease l where l.proposal_revision_id = p.id "
                        + "and l.status = 'ACTIVE' and l.expires_at > ?) "
                        + "order by p.created_at, p.id",
                (rs, row) -> new ApprovalModels.QueueItem(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getBigDecimal(3),
                        rs.getTimestamp(4).toInstant(), rs.getTimestamp(5).toInstant()),
                now, now);
    }

    @Override
    @Transactional
    public ApprovalModels.LeaseResult claim(ApprovalModels.ClaimCommand command) {
        int leaseSeconds = command.requestedLeaseSeconds() == null
                ? defaultLeaseSeconds : command.requestedLeaseSeconds();
        String digest = StableParameterDigest.sha256(
                command.revisionId().toString(), Integer.toString(leaseSeconds));
        lockRequest(command.approverId(), command.requestId(), "APPROVAL_CLAIM");
        List<ClaimReplay> existing = jdbc.query(
                "select parameter_digest, proposal_revision_id, lease_token, lease_version, expires_at "
                        + "from approval_claim_request where approver_id = ? and request_id = ?",
                (rs, row) -> new ClaimReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        rs.getLong(4), rs.getTimestamp(5).toInstant()),
                command.approverId(), command.requestId());
        if (!existing.isEmpty()) {
            ClaimReplay replay = existing.getFirst();
            if (!replay.parameterDigest().equals(digest)) conflict();
            return new ApprovalModels.LeaseResult(
                    replay.revisionId(), replay.token(), replay.version(), replay.expiresAt(), true);
        }
        if (leaseSeconds < 1 || leaseSeconds > maximumLeaseSeconds) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "unsupported approval lease duration");
        }

        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        List<ProposalScope> proposals = jdbc.query(
                "select ticket_id, status, expires_at from compensation_proposal_revision where id = ? for update",
                (rs, row) -> new ProposalScope(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getTimestamp(3).toInstant()),
                command.revisionId());
        if (proposals.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "approval proposal not found");
        }
        ProposalScope proposal = proposals.getFirst();
        if (!"PENDING_APPROVAL".equals(proposal.status()) || !proposal.expiresAt().isAfter(now)) {
            throw new ResponseStatusException(HttpStatus.GONE, "approval proposal is no longer claimable");
        }
        jdbc.update(
                "update approval_lease set status = 'EXPIRED' "
                        + "where proposal_revision_id = ? and status = 'ACTIVE' and expires_at <= ?",
                command.revisionId(), at);
        Integer active = jdbc.queryForObject(
                "select count(*) from approval_lease where proposal_revision_id = ? and status = 'ACTIVE'",
                Integer.class, command.revisionId());
        if (active != null && active > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "approval lease is already held");
        }

        Long previousVersion = jdbc.queryForObject(
                "select coalesce(max(lease_version), 0) from approval_lease where proposal_revision_id = ?",
                Long.class, command.revisionId());
        long version = (previousVersion == null ? 0 : previousVersion) + 1;
        UUID leaseId = UUID.randomUUID();
        UUID token = UUID.randomUUID();
        Instant expiresAt = now.plusSeconds(leaseSeconds);
        if (expiresAt.isAfter(proposal.expiresAt())) expiresAt = proposal.expiresAt();
        jdbc.update(
                "insert into approval_lease (id, proposal_revision_id, approver_id, lease_token, lease_version, "
                        + "status, claimed_at, expires_at) values (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)",
                leaseId, command.revisionId(), command.approverId(), token, version, at,
                Timestamp.from(expiresAt));
        jdbc.update(
                "insert into approval_claim_request (approver_id, request_id, parameter_digest, "
                        + "proposal_revision_id, lease_id, lease_token, lease_version, expires_at, created_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                command.approverId(), command.requestId(), digest, command.revisionId(), leaseId,
                token, version, Timestamp.from(expiresAt), at);
        audit(proposal.ticketId(), "APPROVAL_LEASE_CLAIMED", command.approverId(), at);
        return new ApprovalModels.LeaseResult(command.revisionId(), token, version, expiresAt, false);
    }

    @Override
    @Transactional(readOnly = true)
    public ApprovalModels.ApprovalView view(ApprovalModels.ViewCommand command) {
        Instant now = clock.instant();
        List<ViewRow> rows = jdbc.query(
                "select p.ticket_id, p.revision_number, p.content_digest, p.order_reference, p.reason_code, "
                        + "p.delay_hours, p.delay_seconds, p.compensation_method, p.amount, p.policy_version, "
                        + "s.paid_amount, s.available_compensation_amount, "
                        + "s.active_reservation_amount, s.paid, s.cancelled, s.fully_refunded, "
                        + "s.existing_compensation, s.evidence_references::text, l.expires_at, p.created_at, p.expires_at "
                        + "from approval_lease l join compensation_proposal_revision p on p.id = l.proposal_revision_id "
                        + "join approval_evidence_snapshot s on s.proposal_revision_id = p.id "
                        + "where p.id = ? and p.status = 'PENDING_APPROVAL' and p.expires_at > ? "
                        + "and l.approver_id = ? and l.lease_token = ? and l.lease_version = ? "
                        + "and l.status = 'ACTIVE' and l.expires_at > ?",
                (rs, row) -> new ViewRow(
                        rs.getObject(1, UUID.class), rs.getInt(2), rs.getString(3), rs.getString(4),
                        rs.getString(5), rs.getInt(6), rs.getLong(7), rs.getString(8), rs.getBigDecimal(9),
                        rs.getString(10), rs.getBigDecimal(11), rs.getBigDecimal(12), rs.getBigDecimal(13),
                        rs.getBoolean(14), rs.getBoolean(15), rs.getBoolean(16), rs.getBoolean(17),
                        rs.getString(18), rs.getTimestamp(19).toInstant(), rs.getTimestamp(20).toInstant(),
                        rs.getTimestamp(21).toInstant()),
                command.revisionId(), Timestamp.from(now), command.approverId(), command.leaseToken(),
                command.leaseVersion(), Timestamp.from(now));
        if (rows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "current approval lease required");
        }
        ViewRow row = rows.getFirst();
        DelayCompensationPolicy.Decision authoritative =
                policy.evaluate(Duration.ofSeconds(row.delaySeconds()), row.paidAmount());
        if (!authoritative.eligible()
                || !authoritative.method().name().equals(row.method())
                || authoritative.amount().compareTo(row.amount()) != 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "proposal no longer matches authoritative policy");
        }
        List<String> evidence = parseEvidence(row.evidenceJson());
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("delaySeconds", row.delaySeconds());
        snapshot.put("paidAmount", row.paidAmount().toPlainString());
        snapshot.put("availableCompensationAmount", row.availableAmount().toPlainString());
        snapshot.put("activeReservationAmount", row.reservedAmount().toPlainString());
        List<String> checks = eligibilityChecks(row, authoritative.amount());
        List<String> responsibility = jdbc.query(
                "select event_type from audit_event where ticket_id = ? and event_type in "
                        + "('COMPENSATION_PROPOSAL_REVISION_CREATED', 'COMPENSATION_PROPOSAL_REVISION_REUSED', "
                        + "'APPROVAL_LEASE_CLAIMED') order by occurred_at, id",
                (rs, index) -> rs.getString(1), row.ticketId());
        return new ApprovalModels.ApprovalView(
                "APPROVAL_VIEW", command.revisionId(), row.revisionNumber(), row.contentDigest(),
                row.orderReference(), row.reasonCode(), row.delayHours(), row.delaySeconds(), row.method(),
                row.amount(), authoritative.amount(), row.policyVersion(), tier(row.delaySeconds()), checks,
                evidence, snapshot, responsibility, command.leaseToken(), command.leaseVersion(), row.leaseExpiresAt(),
                row.submittedAt(), row.proposalExpiresAt());
    }

    @Override
    @Transactional
    public ApprovalModels.ReleaseResult release(ApprovalModels.ReleaseCommand command) {
        String digest = StableParameterDigest.sha256(
                command.revisionId().toString(), command.leaseToken().toString(), Long.toString(command.leaseVersion()));
        lockRequest(command.approverId(), command.requestId(), "APPROVAL_RELEASE");
        List<ReleaseReplay> existing = jdbc.query(
                "select parameter_digest, proposal_revision_id from approval_release_request "
                        + "where approver_id = ? and request_id = ?",
                (rs, row) -> new ReleaseReplay(rs.getString(1), rs.getObject(2, UUID.class)),
                command.approverId(), command.requestId());
        if (!existing.isEmpty()) {
            if (!existing.getFirst().parameterDigest().equals(digest)) conflict();
            return new ApprovalModels.ReleaseResult(existing.getFirst().revisionId(), true, true);
        }
        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        List<LeaseScope> leases = jdbc.query(
                "select p.ticket_id, l.status, l.expires_at from approval_lease l "
                        + "join compensation_proposal_revision p on p.id = l.proposal_revision_id "
                        + "where l.proposal_revision_id = ? and l.approver_id = ? and l.lease_token = ? "
                        + "and l.lease_version = ? for update of l, p",
                (rs, row) -> new LeaseScope(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getTimestamp(3).toInstant()),
                command.revisionId(), command.approverId(), command.leaseToken(), command.leaseVersion());
        if (leases.isEmpty() || !"ACTIVE".equals(leases.getFirst().status())
                || !leases.getFirst().expiresAt().isAfter(now)) {
            if (!leases.isEmpty() && "ACTIVE".equals(leases.getFirst().status())) {
                jdbc.update("update approval_lease set status = 'EXPIRED' where proposal_revision_id = ? "
                                + "and lease_version = ? and status = 'ACTIVE'",
                        command.revisionId(), command.leaseVersion());
            }
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "current approval lease required");
        }
        LeaseScope lease = leases.getFirst();
        jdbc.update(
                "update approval_lease set status = 'RELEASED', released_at = ? "
                        + "where proposal_revision_id = ? and lease_version = ? and status = 'ACTIVE'",
                at, command.revisionId(), command.leaseVersion());
        jdbc.update(
                "insert into approval_release_request (approver_id, request_id, parameter_digest, "
                        + "proposal_revision_id, lease_token, lease_version, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                command.approverId(), command.requestId(), digest, command.revisionId(), command.leaseToken(),
                command.leaseVersion(), at);
        audit(lease.ticketId(), "APPROVAL_LEASE_RELEASED", command.approverId(), at);
        return new ApprovalModels.ReleaseResult(command.revisionId(), true, false);
    }

    private void lockRequest(String approverId, String requestId, String operation) {
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                approverId + "\n" + operation + "\n" + requestId);
    }

    private void audit(UUID ticketId, String eventType, String actorId, Timestamp at) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, ?, ?, ?)",
                ticketId, eventType, actorId, at);
    }

    private List<String> parseEvidence(String json) {
        try {
            return objectMapper.readValue(
                    json, objectMapper.getTypeFactory().constructCollectionType(List.class, String.class));
        } catch (Exception exception) {
            throw new IllegalStateException("invalid approval evidence snapshot", exception);
        }
    }

    private static List<String> eligibilityChecks(ViewRow row, BigDecimal authoritativeAmount) {
        return List.of(
                row.paid() ? "ORDER_PAID" : "ORDER_NOT_PAID",
                !row.cancelled() ? "ORDER_NOT_CANCELLED" : "ORDER_CANCELLED",
                !row.fullyRefunded() ? "ORDER_NOT_FULLY_REFUNDED" : "ORDER_FULLY_REFUNDED",
                !row.existingCompensation() ? "NO_EXISTING_COMPENSATION" : "EXISTING_COMPENSATION",
                row.availableAmount().compareTo(authoritativeAmount) >= 0
                        ? "ALLOWANCE_SUFFICIENT" : "ALLOWANCE_INSUFFICIENT");
    }

    private static String tier(long delaySeconds) {
        if (delaySeconds < Duration.ofHours(48).toSeconds()) return "24_TO_UNDER_48_HOURS";
        if (delaySeconds <= Duration.ofHours(72).toSeconds()) return "48_TO_72_HOURS";
        return "OVER_72_HOURS";
    }

    private static void conflict() {
        throw new ResponseStatusException(HttpStatus.CONFLICT, "request identity reused with different parameters");
    }

    private record ClaimReplay(String parameterDigest, UUID revisionId, UUID token, long version, Instant expiresAt) {}
    private record ReleaseReplay(String parameterDigest, UUID revisionId) {}
    private record ProposalScope(UUID ticketId, String status, Instant expiresAt) {}
    private record LeaseScope(UUID ticketId, String status, Instant expiresAt) {}
    private record ViewRow(
            UUID ticketId, int revisionNumber, String contentDigest, String orderReference, String reasonCode,
            int delayHours, long delaySeconds, String method, BigDecimal amount, String policyVersion,
            BigDecimal paidAmount, BigDecimal availableAmount,
            BigDecimal reservedAmount, boolean paid, boolean cancelled, boolean fullyRefunded,
            boolean existingCompensation, String evidenceJson, Instant leaseExpiresAt,
            Instant submittedAt, Instant proposalExpiresAt) {}
}
