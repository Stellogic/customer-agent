package com.stellogic.customeragent.approval;

import com.stellogic.customeragent.compensation.DelayCompensationPolicy;
import com.stellogic.customeragent.handoff.HumanHandoffService;
import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
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
    static final String APPROVAL_VIEW_EPOCH = "approval-view-v1";
    private static final String APPROVAL_PUBLIC_MESSAGE = "补偿方案已获批准，正在等待补偿处理。";
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final ObjectMapper objectMapper;
    private final CompensationProposalExpiry proposalExpiry;
    private final TicketAuthorityLock authorityLock;
    private final HumanHandoffService handoffService;
    private final CustomerPublicProjectionAppender publicProjection;
    private final int defaultLeaseSeconds;
    private final int maximumLeaseSeconds;
    private final DelayCompensationPolicy policy = new DelayCompensationPolicy();

    JdbcApprovalService(
            JdbcTemplate jdbc,
            Clock clock,
            ObjectMapper objectMapper,
            CompensationProposalExpiry proposalExpiry,
            TicketAuthorityLock authorityLock,
            HumanHandoffService handoffService,
            CustomerPublicProjectionAppender publicProjection,
            @Value("${baseline.approval.default-lease-seconds:900}") int defaultLeaseSeconds,
            @Value("${baseline.approval.maximum-lease-seconds:900}") int maximumLeaseSeconds) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.objectMapper = objectMapper;
        this.proposalExpiry = proposalExpiry;
        this.authorityLock = authorityLock;
        this.handoffService = handoffService;
        this.publicProjection = publicProjection;
        this.defaultLeaseSeconds = defaultLeaseSeconds;
        this.maximumLeaseSeconds = maximumLeaseSeconds;
    }

    @Override
    @Transactional
    public List<ApprovalModels.QueueItem> queue() {
        Instant serverNow = clock.instant();
        proposalExpiry.expireDue(serverNow);
        Timestamp now = Timestamp.from(serverNow);
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
    @Transactional(noRollbackFor = ResponseStatusException.class)
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

        List<ProposalScope> proposals = jdbc.query(
                "select ticket_id, status, expires_at from compensation_proposal_revision where id = ? for update",
                (rs, row) -> new ProposalScope(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getTimestamp(3).toInstant()),
                command.revisionId());
        if (proposals.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "approval proposal not found");
        }
        ProposalScope proposal = proposals.getFirst();
        if (!"PENDING_APPROVAL".equals(proposal.status())) {
            throw new ResponseStatusException(HttpStatus.GONE, "approval proposal is no longer claimable");
        }
        Instant now = clock.instant();
        if (!proposal.expiresAt().isAfter(now)) {
            proposalExpiry.expireIfDue(command.revisionId(), now);
            throw new ResponseStatusException(HttpStatus.GONE, "approval proposal is no longer claimable");
        }
        Timestamp at = Timestamp.from(now);
        List<Long> expiredVersions = jdbc.query(
                "select lease_version from approval_lease where proposal_revision_id = ? "
                        + "and status = 'ACTIVE' and expires_at <= ? for update",
                (rs, row) -> rs.getLong(1), command.revisionId(), at);
        expiredVersions.forEach(version -> expireLease(
                proposal.ticketId(), command.revisionId(), version, now));
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
        audit(proposal.ticketId(), command.revisionId(), version,
                "APPROVAL_LEASE_CLAIMED", command.approverId(), at);
        return new ApprovalModels.LeaseResult(command.revisionId(), token, version, expiresAt, false);
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public ApprovalModels.ApprovalView view(ApprovalModels.ViewCommand command) {
        lockProposal(command.revisionId());
        List<ViewRow> rows = jdbc.query(
                "select p.ticket_id, p.revision_number, p.content_digest, p.order_reference, p.reason_code, "
                        + "p.delay_hours, p.delay_seconds, p.compensation_method, p.amount, p.policy_version, "
                        + "s.paid_amount, s.available_compensation_amount, "
                        + "s.active_reservation_amount, s.paid, s.cancelled, s.fully_refunded, "
                        + "s.existing_compensation, s.evidence_references::text, l.expires_at, p.created_at, p.expires_at, "
                        + "p.status, l.status "
                        + "from approval_lease l join compensation_proposal_revision p on p.id = l.proposal_revision_id "
                        + "join approval_evidence_snapshot s on s.proposal_revision_id = p.id "
                        + "where p.id = ? and l.approver_id = ? and l.lease_token = ? and l.lease_version = ? "
                        + "for update of l",
                (rs, row) -> new ViewRow(
                        rs.getObject(1, UUID.class), rs.getInt(2), rs.getString(3), rs.getString(4),
                        rs.getString(5), rs.getInt(6), rs.getLong(7), rs.getString(8), rs.getBigDecimal(9),
                        rs.getString(10), rs.getBigDecimal(11), rs.getBigDecimal(12), rs.getBigDecimal(13),
                        rs.getBoolean(14), rs.getBoolean(15), rs.getBoolean(16), rs.getBoolean(17),
                        rs.getString(18), rs.getTimestamp(19).toInstant(), rs.getTimestamp(20).toInstant(),
                        rs.getTimestamp(21).toInstant(), rs.getString(22), rs.getString(23)),
                command.revisionId(), command.approverId(), command.leaseToken(), command.leaseVersion());
        if (rows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "current approval lease required");
        }
        ViewRow row = rows.getFirst();
        Instant now = clock.instant();
        requireCurrentLease(new CurrentLeaseScope(
                row.ticketId(), command.revisionId(), command.leaseVersion(), row.proposalStatus(),
                row.proposalExpiresAt(), row.leaseStatus(), row.leaseExpiresAt(), now));
        DelayCompensationPolicy.Decision authoritative =
                policy.evaluate(Duration.ofSeconds(row.delaySeconds()), row.paidAmount());
        if (!DelayCompensationPolicy.VERSION.equals(row.policyVersion())
                || !authoritative.eligible()
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
        List<ApprovalModels.ResponsibilityEvent> responsibility = jdbc.query(
                "select event_type, actor_id, occurred_at, authorization_version from audit_event "
                        + "where subject_type = 'COMPENSATION_PROPOSAL_REVISION' and subject_id = ? and event_type in "
                        + "('COMPENSATION_PROPOSAL_REVISION_CREATED', 'COMPENSATION_PROPOSAL_REVISION_REUSED', "
                        + "'APPROVAL_LEASE_CLAIMED', 'APPROVAL_LEASE_RELEASED', 'APPROVAL_LEASE_EXPIRED', "
                        + "'APPROVAL_LEASE_REVOKED') "
                        + "and (authorization_version is null or authorization_version <= ?) "
                        + "order by occurred_at, id",
                (rs, index) -> new ApprovalModels.ResponsibilityEvent(
                        rs.getString(1), rs.getString(2), rs.getTimestamp(3).toInstant(),
                        rs.getObject(4, Long.class)), command.revisionId(), command.leaseVersion());
        return new ApprovalModels.ApprovalView(
                "APPROVAL_VIEW", APPROVAL_VIEW_EPOCH, approvalCursor(command),
                command.revisionId(), row.revisionNumber(), row.contentDigest(),
                row.orderReference(), row.reasonCode(), row.delayHours(), row.delaySeconds(), row.method(),
                row.amount(), authoritative.amount(), row.policyVersion(), tier(row.delaySeconds()), checks,
                evidence, snapshot, responsibility, command.leaseToken(), command.leaseVersion(), row.leaseExpiresAt(),
                row.submittedAt(), row.proposalExpiresAt());
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public List<ApprovalModels.ApprovalViewEvent> events(
            ApprovalModels.ViewCommand command, String afterCursor) {
        view(command);
        long after = parseApprovalCursor(afterCursor);
        Long latest = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) from approval_view_event "
                        + "where proposal_revision_id = ? and lease_version = ?",
                Long.class, command.revisionId(), command.leaseVersion());
        long authoritySequence = latest == null ? 0 : latest;
        if (after < 0 || after > authoritySequence) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "approval view snapshot required");
        }
        Long firstRetained = jdbc.queryForObject(
                "select min(sequence) from approval_view_event "
                        + "where proposal_revision_id = ? and lease_version = ?",
                Long.class, command.revisionId(), command.leaseVersion());
        if (after < authoritySequence && firstRetained != null && firstRetained > after + 1) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "approval view snapshot required");
        }
        return jdbc.query(
                "select epoch, sequence, event_type, proposal_revision_id, lease_version, authority_state "
                        + "from approval_view_event where proposal_revision_id = ? and lease_version = ? "
                        + "and sequence > ? order by sequence",
                (rs, rowNumber) -> new ApprovalModels.ApprovalViewEvent(
                        rs.getString(1), rs.getLong(2), rs.getString(3),
                        rs.getObject(4, UUID.class), rs.getLong(5), rs.getString(6)),
                command.revisionId(), command.leaseVersion(), after);
    }

    private String approvalCursor(ApprovalModels.ViewCommand command) {
        Long sequence = jdbc.queryForObject(
                "select coalesce(max(sequence), 0) from approval_view_event "
                        + "where proposal_revision_id = ? and lease_version = ?",
                Long.class, command.revisionId(), command.leaseVersion());
        return APPROVAL_VIEW_EPOCH + ":" + (sequence == null ? 0 : sequence);
    }

    private static long parseApprovalCursor(String cursor) {
        if (cursor == null || cursor.isBlank()) return 0;
        int separator = cursor.lastIndexOf(':');
        if (separator < 1 || !APPROVAL_VIEW_EPOCH.equals(cursor.substring(0, separator))) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "approval view snapshot required");
        }
        try {
            long sequence = Long.parseLong(cursor.substring(separator + 1));
            if (sequence < 0) throw new NumberFormatException();
            return sequence;
        } catch (NumberFormatException exception) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "approval view snapshot required");
        }
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
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
        lockProposal(command.revisionId());
        List<LeaseScope> leases = jdbc.query(
                "select p.ticket_id, p.status, p.expires_at, l.status, l.expires_at from approval_lease l "
                        + "join compensation_proposal_revision p on p.id = l.proposal_revision_id "
                        + "where l.proposal_revision_id = ? and l.approver_id = ? and l.lease_token = ? "
                        + "and l.lease_version = ? for update of l",
                (rs, row) -> new LeaseScope(
                        rs.getObject(1, UUID.class), rs.getString(2), rs.getTimestamp(3).toInstant(),
                        rs.getString(4), rs.getTimestamp(5).toInstant()),
                command.revisionId(), command.approverId(), command.leaseToken(), command.leaseVersion());
        if (leases.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "current approval lease required");
        }
        LeaseScope lease = leases.getFirst();
        Instant now = clock.instant();
        requireCurrentLease(new CurrentLeaseScope(
                lease.ticketId(), command.revisionId(), command.leaseVersion(), lease.proposalStatus(),
                lease.proposalExpiresAt(), lease.leaseStatus(), lease.leaseExpiresAt(), now));
        Timestamp at = Timestamp.from(now);
        jdbc.update(
                "update approval_lease set status = 'RELEASED', released_at = ? "
                        + "where proposal_revision_id = ? and lease_version = ? and status = 'ACTIVE'",
                at, command.revisionId(), command.leaseVersion());
        jdbc.update(
                "insert into approval_release_request (approver_id, request_id, parameter_digest, "
                        + "proposal_revision_id, lease_token, lease_version, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                command.approverId(), command.requestId(), digest, command.revisionId(), command.leaseToken(),
                command.leaseVersion(), at);
        audit(lease.ticketId(), command.revisionId(), command.leaseVersion(),
                "APPROVAL_LEASE_RELEASED", command.approverId(), at);
        return new ApprovalModels.ReleaseResult(command.revisionId(), true, false);
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public ApprovalModels.RejectionResult reject(ApprovalModels.RejectionCommand command) {
        String digest = StableParameterDigest.sha256(
                "REJECTED", command.revisionId().toString(), Integer.toString(command.proposalRevision()),
                command.contentDigest(), command.leaseToken().toString(), Long.toString(command.leaseVersion()),
                command.internalReason());
        lockRequest(command.approverId(), command.requestId(), "PROPOSAL_DECISION");
        List<DecisionReplay> existing = jdbc.query(
                "select r.parameter_digest, r.proposal_revision_id, r.proposal_revision, r.decision_type "
                        + "from proposal_decision_request r where r.approver_id = ? and r.request_id = ?",
                (rs, row) -> new DecisionReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getInt(3),
                        ApprovalModels.ProposalDecision.valueOf(rs.getString(4))),
                command.approverId(), command.requestId());
        if (!existing.isEmpty()) {
            DecisionReplay replay = existing.getFirst();
            if (!replay.parameterDigest().equals(digest)) conflict();
            return new ApprovalModels.RejectionResult(
                    replay.revisionId(), replay.proposalRevision(), replay.decisionType(), true);
        }

        List<UUID> ticketIds = jdbc.query(
                "select ticket_id from compensation_proposal_revision where id = ?",
                (rs, row) -> rs.getObject(1, UUID.class), command.revisionId());
        if (ticketIds.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "approval proposal not found");
        }
        UUID ticketId = ticketIds.getFirst();
        authorityLock.acquire(ticketId);
        List<String> ticketStates = jdbc.query(
                "select lifecycle_state from support_ticket where id = ? for update",
                (rs, row) -> rs.getString(1), ticketId);
        if (ticketStates.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "approval proposal ticket not found");
        }
        if ("CLOSED".equals(ticketStates.getFirst())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "ticket is no longer current");
        }
        List<DecisionProposal> proposals = jdbc.query(
                "select ticket_id, revision_number, content_digest, status, expires_at "
                        + "from compensation_proposal_revision where id = ? for update",
                (rs, row) -> new DecisionProposal(
                        rs.getObject(1, UUID.class), rs.getInt(2), rs.getString(3),
                        rs.getString(4), rs.getTimestamp(5).toInstant()),
                command.revisionId());
        if (proposals.isEmpty() || !ticketId.equals(proposals.getFirst().ticketId())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "approval proposal not found");
        }
        DecisionProposal proposal = proposals.getFirst();
        Instant now = clock.instant();
        List<DecisionLease> leases = jdbc.query(
                "select status, expires_at from approval_lease where proposal_revision_id = ? "
                        + "and approver_id = ? and lease_token = ? and lease_version = ? for update",
                (rs, row) -> new DecisionLease(rs.getString(1), rs.getTimestamp(2).toInstant()),
                command.revisionId(), command.approverId(), command.leaseToken(), command.leaseVersion());
        if (leases.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "current approval lease required");
        }
        DecisionLease lease = leases.getFirst();
        requireCurrentLease(new CurrentLeaseScope(
                ticketId, command.revisionId(), command.leaseVersion(), proposal.status(),
                proposal.expiresAt(), lease.status(), lease.expiresAt(), now));
        if (proposal.revisionNumber() != command.proposalRevision()
                || !proposal.contentDigest().equals(command.contentDigest())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "proposal revision content mismatch");
        }

        Timestamp at = Timestamp.from(now);
        UUID decisionId = UUID.randomUUID();
        jdbc.update(
                "insert into proposal_decision (id, proposal_revision_id, proposal_revision, content_digest, "
                        + "approver_id, lease_token, lease_version, decision_type, internal_reason, decided_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, 'REJECTED', ?, ?)",
                decisionId, command.revisionId(), command.proposalRevision(), command.contentDigest(),
                command.approverId(), command.leaseToken(), command.leaseVersion(), command.internalReason(), at);
        jdbc.update(
                "insert into proposal_decision_request (approver_id, request_id, parameter_digest, decision_id, "
                        + "proposal_revision_id, proposal_revision, content_digest, lease_token, lease_version, "
                        + "decision_type, created_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'REJECTED', ?)",
                command.approverId(), command.requestId(), digest, decisionId, command.revisionId(),
                command.proposalRevision(), command.contentDigest(), command.leaseToken(),
                command.leaseVersion(), at);
        jdbc.update(
                "update approval_lease set status = 'DECIDED', decided_at = ? "
                        + "where proposal_revision_id = ? and lease_version = ? and status = 'ACTIVE'",
                at, command.revisionId(), command.leaseVersion());
        jdbc.update(
                "update compensation_proposal_revision set status = 'REJECTED' where id = ?",
                command.revisionId());
        auditDecision(ticketId, decisionId, command.leaseVersion(), command.approverId(), at);
        handoffService.handoffAfterProposalRejection(ticketId, command.approverId());
        return new ApprovalModels.RejectionResult(
                command.revisionId(), command.proposalRevision(), ApprovalModels.ProposalDecision.REJECTED, false);
    }

    @Override
    @Transactional(noRollbackFor = ResponseStatusException.class)
    public ApprovalModels.ApprovalResult approve(ApprovalModels.ApprovalCommand command) {
        String normalizedNote = command.internalNote() == null ? "" : command.internalNote();
        String digest = StableParameterDigest.sha256(
                "APPROVED", command.revisionId().toString(), Integer.toString(command.proposalRevision()),
                command.contentDigest(), command.leaseToken().toString(), Long.toString(command.leaseVersion()),
                normalizedNote);
        lockRequest(command.approverId(), command.requestId(), "PROPOSAL_DECISION");
        List<ApprovalReplay> existing = jdbc.query(
                "select r.parameter_digest, r.proposal_revision_id, r.proposal_revision, r.decision_type, "
                        + "e.id, e.status from proposal_decision_request r "
                        + "left join compensation_execution e on e.decision_id = r.decision_id "
                        + "where r.approver_id = ? and r.request_id = ?",
                (rs, row) -> new ApprovalReplay(
                        rs.getString(1), rs.getObject(2, UUID.class), rs.getInt(3),
                        ApprovalModels.ProposalDecision.valueOf(rs.getString(4)),
                        rs.getObject(5, UUID.class),
                        rs.getString(6) == null ? null
                                : ApprovalModels.CompensationExecutionStatus.valueOf(rs.getString(6))),
                command.approverId(), command.requestId());
        if (!existing.isEmpty()) {
            ApprovalReplay replay = existing.getFirst();
            if (!replay.parameterDigest().equals(digest)) conflict();
            if (replay.executionId() == null) conflict();
            return new ApprovalModels.ApprovalResult(
                    replay.revisionId(), replay.proposalRevision(), replay.decisionType(),
                    replay.executionId(), replay.executionStatus(), true);
        }

        List<UUID> ticketIds = jdbc.query(
                "select ticket_id from compensation_proposal_revision where id = ?",
                (rs, row) -> rs.getObject(1, UUID.class), command.revisionId());
        if (ticketIds.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "approval proposal not found");
        }
        UUID ticketId = ticketIds.getFirst();
        authorityLock.acquire(ticketId);
        List<String> ticketStates = jdbc.query(
                "select lifecycle_state from support_ticket where id = ? for update",
                (rs, row) -> rs.getString(1), ticketId);
        if (ticketStates.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "approval proposal ticket not found");
        }
        if ("CLOSED".equals(ticketStates.getFirst())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "ticket is no longer current");
        }

        List<ApprovalProposal> proposals = jdbc.query(
                "select p.ticket_id, p.revision_number, p.content_digest, p.status, p.expires_at, "
                        + "p.order_reference, p.delay_hours, p.delay_seconds, p.compensation_method, p.amount, "
                        + "p.reason_code, p.policy_version, s.paid_amount, s.available_compensation_amount, "
                        + "s.active_reservation_amount, s.paid, s.cancelled, s.fully_refunded, s.existing_compensation "
                        + "from compensation_proposal_revision p join approval_evidence_snapshot s "
                        + "on s.proposal_revision_id = p.id where p.id = ? for update of p",
                (rs, row) -> new ApprovalProposal(
                        rs.getObject(1, UUID.class), rs.getInt(2), rs.getString(3), rs.getString(4),
                        rs.getTimestamp(5).toInstant(), rs.getString(6), rs.getInt(7), rs.getLong(8),
                        DelayCompensationPolicy.Method.valueOf(rs.getString(9)), rs.getBigDecimal(10),
                        rs.getString(11), rs.getString(12), new ApprovalEvidenceFacts(
                                rs.getBigDecimal(13), rs.getBigDecimal(14), rs.getBigDecimal(15),
                                rs.getBoolean(16), rs.getBoolean(17), rs.getBoolean(18), rs.getBoolean(19))),
                command.revisionId());
        if (proposals.isEmpty() || !ticketId.equals(proposals.getFirst().ticketId())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "approval proposal not found");
        }
        ApprovalProposal proposal = proposals.getFirst();
        Instant now = clock.instant();
        List<DecisionLease> leases = jdbc.query(
                "select status, expires_at from approval_lease where proposal_revision_id = ? "
                        + "and approver_id = ? and lease_token = ? and lease_version = ? for update",
                (rs, row) -> new DecisionLease(rs.getString(1), rs.getTimestamp(2).toInstant()),
                command.revisionId(), command.approverId(), command.leaseToken(), command.leaseVersion());
        if (leases.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "current approval lease required");
        }
        DecisionLease lease = leases.getFirst();
        requireCurrentLease(new CurrentLeaseScope(
                ticketId, command.revisionId(), command.leaseVersion(), proposal.status(),
                proposal.expiresAt(), lease.status(), lease.expiresAt(), now));
        if (proposal.revisionNumber() != command.proposalRevision()
                || !proposal.contentDigest().equals(command.contentDigest())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "proposal revision content mismatch");
        }

        lockAllowance(proposal.orderReference());
        List<AuthoritativeOrderFacts> orders = jdbc.query(
                "select paid_amount, available_compensation_amount, delay_hours, delay_seconds, paid, cancelled, "
                        + "fully_refunded, existing_compensation, policy_version "
                        + "from lock_authoritative_order(?)",
                (rs, row) -> new AuthoritativeOrderFacts(
                        rs.getBigDecimal(1), rs.getBigDecimal(2), rs.getInt(3), rs.getLong(4),
                        rs.getBoolean(5), rs.getBoolean(6), rs.getBoolean(7), rs.getBoolean(8), rs.getString(9)),
                proposal.orderReference());
        if (orders.isEmpty()) {
            invalidateProposal(ticketId, command, now, "ORDER_MISSING");
        }
        AuthoritativeOrderFacts order = orders.getFirst();
        BigDecimal activeReservations = jdbc.queryForObject(
                "select coalesce(sum(amount), 0) from compensation_reservation "
                        + "where order_reference = ? and status = 'ACTIVE'",
                BigDecimal.class, proposal.orderReference());
        if (activeReservations == null) activeReservations = BigDecimal.ZERO;
        DelayCompensationPolicy.Decision authoritative =
                policy.evaluate(Duration.ofSeconds(order.delaySeconds()), order.paidAmount());
        boolean valid = matchesAuthoritativeFacts(proposal, order, activeReservations, authoritative);
        if (!valid) {
            invalidateProposal(ticketId, command, now, "AUTHORITATIVE_FACT_DRIFT");
        }

        Timestamp at = Timestamp.from(now);
        UUID decisionId = UUID.randomUUID();
        UUID executionId = stableUuid("compensation-execution\n" + command.revisionId());
        UUID reservationId = stableUuid("compensation-reservation\n" + command.revisionId());
        String executionKey = "compensation-execution:" + command.revisionId();
        String executionDigest = StableParameterDigest.sha256(
                executionId.toString(), executionKey, proposal.orderReference(), proposal.reasonCode(),
                proposal.method().name(), authoritative.amount().toPlainString());
        jdbc.update(
                "insert into proposal_decision (id, proposal_revision_id, proposal_revision, content_digest, "
                        + "approver_id, lease_token, lease_version, decision_type, internal_reason, decided_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, 'APPROVED', ?, ?)",
                decisionId, command.revisionId(), command.proposalRevision(), command.contentDigest(),
                command.approverId(), command.leaseToken(), command.leaseVersion(), command.internalNote(), at);
        jdbc.update(
                "insert into proposal_decision_request (approver_id, request_id, parameter_digest, decision_id, "
                        + "proposal_revision_id, proposal_revision, content_digest, lease_token, lease_version, "
                        + "decision_type, created_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'APPROVED', ?)",
                command.approverId(), command.requestId(), digest, decisionId, command.revisionId(),
                command.proposalRevision(), command.contentDigest(), command.leaseToken(),
                command.leaseVersion(), at);
        jdbc.update(
                "insert into compensation_reservation "
                        + "(id, order_reference, amount, status, created_at, proposal_revision_id) "
                        + "values (?, ?, ?, 'ACTIVE', ?, ?)",
                reservationId, proposal.orderReference(), authoritative.amount(), at, command.revisionId());
        jdbc.update(
                "insert into compensation_execution (id, proposal_revision_id, decision_id, reservation_id, "
                        + "order_reference, reason_code, compensation_method, amount, status, idempotency_key, "
                        + "assigned_executor_id, parameter_digest, created_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, 'READY', ?, 'compensation-executor', ?, ?)",
                executionId, command.revisionId(), decisionId, reservationId, proposal.orderReference(),
                proposal.reasonCode(), proposal.method().name(), authoritative.amount(), executionKey,
                executionDigest, at);
        jdbc.update(
                "update approval_lease set status = 'DECIDED', decided_at = ? "
                        + "where proposal_revision_id = ? and lease_version = ? and status = 'ACTIVE'",
                at, command.revisionId(), command.leaseVersion());
        jdbc.update("update compensation_proposal_revision set status = 'APPROVED' where id = ?",
                command.revisionId());
        auditApproved(ticketId, decisionId, command.leaseVersion(), command.approverId(), at);
        publicProjection.appendSupportMessage(ticketId, APPROVAL_PUBLIC_MESSAGE, now);
        return new ApprovalModels.ApprovalResult(
                command.revisionId(), command.proposalRevision(), ApprovalModels.ProposalDecision.APPROVED,
                executionId, ApprovalModels.CompensationExecutionStatus.READY, false);
    }

    private void lockRequest(String approverId, String requestId, String operation) {
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                approverId + "\n" + operation + "\n" + requestId);
    }

    private void lockProposal(UUID revisionId) {
        jdbc.query(
                "select id from compensation_proposal_revision where id = ? for update",
                (rs, row) -> rs.getObject(1, UUID.class), revisionId);
    }

    private void lockAllowance(String orderReference) {
        jdbc.query("select pg_advisory_xact_lock(hashtextextended(?, 0))", rs -> null,
                orderReference + "\nCOMPENSATION_ALLOWANCE");
    }

    private static boolean matchesAuthoritativeFacts(
            ApprovalProposal proposal,
            AuthoritativeOrderFacts order,
            BigDecimal activeReservations,
            DelayCompensationPolicy.Decision authoritative) {
        ApprovalEvidenceFacts snapshot = proposal.snapshot();
        return order.paid() && !order.cancelled() && !order.fullyRefunded()
                && !order.existingCompensation() && authoritative.eligible()
                && DelayCompensationPolicy.VERSION.equals(order.policyVersion())
                && DelayCompensationPolicy.VERSION.equals(proposal.policyVersion())
                && proposal.delayHours() == order.delayHours()
                && proposal.delaySeconds() == order.delaySeconds()
                && proposal.method() == authoritative.method()
                && proposal.amount().compareTo(authoritative.amount()) == 0
                && snapshot.paidAmount().compareTo(order.paidAmount()) == 0
                && snapshot.availableAmount().compareTo(order.availableAmount()) == 0
                && snapshot.reservedAmount().compareTo(activeReservations) == 0
                && snapshot.paid() == order.paid()
                && snapshot.cancelled() == order.cancelled()
                && snapshot.fullyRefunded() == order.fullyRefunded()
                && snapshot.existingCompensation() == order.existingCompensation()
                && activeReservations.add(authoritative.amount()).compareTo(order.availableAmount()) <= 0;
    }

    private void invalidateProposal(
            UUID ticketId, ApprovalModels.ApprovalCommand command, Instant now, String reason) {
        Timestamp at = Timestamp.from(now);
        jdbc.update("update compensation_proposal_revision set status = 'SUPERSEDED' "
                + "where id = ? and status = 'PENDING_APPROVAL'", command.revisionId());
        audit(ticketId, command.revisionId(), command.leaseVersion(),
                "COMPENSATION_PROPOSAL_INVALIDATED_" + reason, "spring-system", at);
        throw new ResponseStatusException(HttpStatus.CONFLICT,
                "proposal no longer matches authoritative facts");
    }

    private static UUID stableUuid(String value) {
        return UUID.nameUUIDFromBytes(value.getBytes(StandardCharsets.UTF_8));
    }

    private void expireLease(UUID ticketId, UUID revisionId, long leaseVersion, Instant now) {
        int updated = jdbc.update(
                "update approval_lease set status = 'EXPIRED' where proposal_revision_id = ? "
                        + "and lease_version = ? and status = 'ACTIVE'",
                revisionId, leaseVersion);
        if (updated == 1) {
            audit(ticketId, revisionId, leaseVersion,
                    "APPROVAL_LEASE_EXPIRED", "spring-system", Timestamp.from(now));
        }
    }

    private void requireCurrentLease(CurrentLeaseScope scope) {
        if ("PENDING_APPROVAL".equals(scope.proposalStatus())
                && !scope.proposalExpiresAt().isAfter(scope.serverNow())) {
            proposalExpiry.expireIfDue(scope.revisionId(), scope.serverNow());
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "current approval lease required");
        }
        if (!"PENDING_APPROVAL".equals(scope.proposalStatus())
                || !"ACTIVE".equals(scope.leaseStatus())
                || !scope.leaseExpiresAt().isAfter(scope.serverNow())) {
            if ("ACTIVE".equals(scope.leaseStatus())
                    && !scope.leaseExpiresAt().isAfter(scope.serverNow())) {
                expireLease(
                        scope.ticketId(), scope.revisionId(), scope.leaseVersion(), scope.serverNow());
            }
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "current approval lease required");
        }
    }

    private void audit(
            UUID ticketId, UUID revisionId, long leaseVersion,
            String eventType, String actorId, Timestamp at) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, "
                        + "subject_type, subject_id, authorization_version) "
                        + "values (?, ?, ?, ?, 'COMPENSATION_PROPOSAL_REVISION', ?, ?)",
                ticketId, eventType, actorId, at, revisionId, leaseVersion);
    }

    private void auditDecision(
            UUID ticketId, UUID decisionId, long leaseVersion, String actorId, Timestamp at) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, "
                        + "subject_type, subject_id, authorization_version) "
                        + "values (?, 'COMPENSATION_PROPOSAL_REJECTED', ?, ?, 'PROPOSAL_DECISION', ?, ?)",
                ticketId, actorId, at, decisionId, leaseVersion);
    }

    private void auditApproved(
            UUID ticketId, UUID decisionId, long leaseVersion, String actorId, Timestamp at) {
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, "
                        + "subject_type, subject_id, authorization_version) "
                        + "values (?, 'COMPENSATION_PROPOSAL_APPROVED', ?, ?, 'PROPOSAL_DECISION', ?, ?)",
                ticketId, actorId, at, decisionId, leaseVersion);
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
    private record DecisionReplay(
            String parameterDigest, UUID revisionId, int proposalRevision,
            ApprovalModels.ProposalDecision decisionType) {}
    private record ApprovalReplay(
            String parameterDigest, UUID revisionId, int proposalRevision,
            ApprovalModels.ProposalDecision decisionType, UUID executionId,
            ApprovalModels.CompensationExecutionStatus executionStatus) {}
    private record ProposalScope(UUID ticketId, String status, Instant expiresAt) {}
    private record DecisionProposal(
            UUID ticketId, int revisionNumber, String contentDigest, String status, Instant expiresAt) {}
    private record DecisionLease(String status, Instant expiresAt) {}
    private record ApprovalProposal(
            UUID ticketId, int revisionNumber, String contentDigest, String status, Instant expiresAt,
            String orderReference, int delayHours, long delaySeconds, DelayCompensationPolicy.Method method,
            BigDecimal amount, String reasonCode, String policyVersion, ApprovalEvidenceFacts snapshot) {}
    private record ApprovalEvidenceFacts(
            BigDecimal paidAmount, BigDecimal availableAmount, BigDecimal reservedAmount,
            boolean paid, boolean cancelled, boolean fullyRefunded, boolean existingCompensation) {}
    private record AuthoritativeOrderFacts(
            BigDecimal paidAmount, BigDecimal availableAmount, int delayHours, long delaySeconds,
            boolean paid, boolean cancelled, boolean fullyRefunded, boolean existingCompensation,
            String policyVersion) {}
    private record CurrentLeaseScope(
            UUID ticketId,
            UUID revisionId,
            long leaseVersion,
            String proposalStatus,
            Instant proposalExpiresAt,
            String leaseStatus,
            Instant leaseExpiresAt,
            Instant serverNow) {}
    private record LeaseScope(
            UUID ticketId, String proposalStatus, Instant proposalExpiresAt,
            String leaseStatus, Instant leaseExpiresAt) {}
    private record ViewRow(
            UUID ticketId, int revisionNumber, String contentDigest, String orderReference, String reasonCode,
            int delayHours, long delaySeconds, String method, BigDecimal amount, String policyVersion,
            BigDecimal paidAmount, BigDecimal availableAmount,
            BigDecimal reservedAmount, boolean paid, boolean cancelled, boolean fullyRefunded,
            boolean existingCompensation, String evidenceJson, Instant leaseExpiresAt,
            Instant submittedAt, Instant proposalExpiresAt, String proposalStatus, String leaseStatus) {}
}
