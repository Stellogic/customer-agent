package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.approval.CompensationProposalExpiry;
import com.stellogic.customeragent.reliability.StableParameterDigest;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcCompensationProposalStore {
    private final JdbcTemplate jdbc;
    private final CompensationProposalExpiry expiry;

    public JdbcCompensationProposalStore(JdbcTemplate jdbc, CompensationProposalExpiry expiry) {
        this.jdbc = jdbc;
        this.expiry = expiry;
    }

    public StoredProposal save(ProposalContent content) {
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                rs -> null,
                content.orderReference() + "\nCOMPENSATION_ALLOWANCE");
        List<UUID> existingProposalIds =
                jdbc.query(
                        "select distinct proposal_id from compensation_proposal_revision "
                                + "where ticket_id = ? "
                                + "and status in ('PENDING_APPROVAL', 'APPROVED')",
                        (rs, row) -> rs.getObject(1, UUID.class),
                        content.ticketId());
        if (!existingProposalIds.isEmpty()) {
            jdbc.query(
                    "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                    rs -> null,
                    existingProposalIds.getFirst() + "\nPROPOSAL_SUPPORT_PARTICIPANT_LINEAGE");
        }
        Instant now = expiry.expireDueForTicket(content.ticketId());
        List<ActiveProposal> active =
                jdbc.query(
                        "select id, proposal_id, revision_number, ticket_id, content_digest, status "
                                + "from compensation_proposal_revision where ticket_id = ? "
                                + "and status in ('PENDING_APPROVAL', 'APPROVED') for update",
                        (rs, row) ->
                                new ActiveProposal(
                                        rs.getObject(1, UUID.class),
                                        rs.getObject(2, UUID.class),
                                        rs.getInt(3),
                                        rs.getObject(4, UUID.class),
                                        rs.getString(5),
                                        rs.getString(6)),
                        content.ticketId());
        String contentDigest = content.digest();
        if (!active.isEmpty() && "APPROVED".equals(active.getFirst().status())) {
            throw new ActiveIntentException("ACTIVE_APPROVED_COMPENSATION_INTENT_CONFLICT");
        }
        if (!active.isEmpty() && active.getFirst().contentDigest().equals(contentDigest)) {
            ActiveProposal same = active.getFirst();
            return new StoredProposal(same.id(), same.revisionNumber(), false);
        }

        UUID proposalId;
        int revisionNumber;
        if (active.isEmpty()) {
            proposalId = UUID.randomUUID();
            revisionNumber = 1;
        } else {
            ActiveProposal previous = active.getFirst();
            List<Long> revokedLeaseVersions =
                    jdbc.query(
                            "select lease_version from approval_lease where proposal_revision_id = ? "
                                    + "and status = 'ACTIVE' for update",
                            (rs, row) -> rs.getLong(1),
                            previous.id());
            jdbc.update(
                    "update compensation_proposal_revision set status = 'SUPERSEDED' where id = ?",
                    previous.id());
            if (!revokedLeaseVersions.isEmpty()) {
                jdbc.update(
                        "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, "
                                + "subject_id, authorization_version) values (?, 'APPROVAL_LEASE_REVOKED', "
                                + "'spring-system', ?, 'COMPENSATION_PROPOSAL_REVISION', ?, ?)",
                        previous.ticketId(),
                        Timestamp.from(now),
                        previous.id(),
                        revokedLeaseVersions.getFirst());
            }
            proposalId = previous.proposalId();
            revisionNumber = previous.revisionNumber() + 1;
        }

        UUID revisionId = UUID.randomUUID();
        Timestamp databaseTime = Timestamp.from(now);
        jdbc.update(
                "insert into compensation_proposal_revision "
                        + "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, "
                        + "delay_hours, delay_seconds, compensation_method, amount, reason_code, "
                        + "evidence_references, policy_version, content_digest, status, created_at, expires_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LOGISTICS_DELAY', "
                        + "jsonb_build_array(?, ?), ?, ?, 'PENDING_APPROVAL', ?, ?)",
                revisionId,
                proposalId,
                revisionNumber,
                content.ticketId(),
                content.orderReference(),
                content.generationId(),
                content.delayHours(),
                content.delaySeconds(),
                content.method(),
                content.amount(),
                content.evidenceReferences().get(0),
                content.evidenceReferences().get(1),
                content.policyVersion(),
                contentDigest,
                databaseTime,
                Timestamp.from(now.plusSeconds(24 * 60 * 60)));
        jdbc.update(
                "insert into approval_evidence_snapshot "
                        + "(proposal_revision_id, order_reference, delay_hours, delay_seconds, paid_amount, "
                        + "total_available_compensation_amount, active_reservation_amount, "
                        + "remaining_available_compensation_amount, paid, cancelled, fully_refunded, "
                        + "existing_compensation, evidence_references, captured_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, jsonb_build_array(?, ?), ?)",
                revisionId,
                content.orderReference(),
                content.delayHours(),
                content.delaySeconds(),
                content.paidAmount(),
                content.totalAvailableAmount(),
                content.activeReservationAmount(),
                content.remainingAvailableAmount(),
                content.paid(),
                content.cancelled(),
                content.fullyRefunded(),
                content.existingCompensation(),
                content.evidenceReferences().get(0),
                content.evidenceReferences().get(1),
                databaseTime);
        return new StoredProposal(revisionId, revisionNumber, true);
    }

    public record ProposalContent(
            UUID ticketId,
            UUID generationId,
            String orderReference,
            int delayHours,
            long delaySeconds,
            String method,
            BigDecimal amount,
            List<String> evidenceReferences,
            String policyVersion,
            BigDecimal paidAmount,
            BigDecimal totalAvailableAmount,
            BigDecimal activeReservationAmount,
            BigDecimal remainingAvailableAmount,
            boolean paid,
            boolean cancelled,
            boolean fullyRefunded,
            boolean existingCompensation) {
        public String digest() {
            return StableParameterDigest.sha256(
                    ticketId.toString(),
                    orderReference,
                    Integer.toString(delayHours),
                    Long.toString(delaySeconds),
                    method,
                    amount.toPlainString(),
                    "LOGISTICS_DELAY",
                    String.join("\n", evidenceReferences),
                    policyVersion,
                    paidAmount.toPlainString(),
                    totalAvailableAmount.toPlainString(),
                    activeReservationAmount.toPlainString(),
                    remainingAvailableAmount.toPlainString(),
                    Boolean.toString(paid),
                    Boolean.toString(cancelled),
                    Boolean.toString(fullyRefunded),
                    Boolean.toString(existingCompensation));
        }
    }

    public record StoredProposal(UUID revisionId, int revisionNumber, boolean created) {}

    public static final class ActiveIntentException extends RuntimeException {
        private final String reason;

        public ActiveIntentException(String reason) {
            this.reason = reason;
        }

        public String reason() {
            return reason;
        }
    }

    private record ActiveProposal(
            UUID id,
            UUID proposalId,
            int revisionNumber,
            UUID ticketId,
            String contentDigest,
            String status) {}
}
