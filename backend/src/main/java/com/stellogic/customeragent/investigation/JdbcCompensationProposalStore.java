package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.reliability.StableParameterDigest;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
class JdbcCompensationProposalStore {
    private final JdbcTemplate jdbc;
    private final Clock clock;

    JdbcCompensationProposalStore(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    StoredProposal save(ProposalContent content) {
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                rs -> null,
                content.orderReference() + "\nLOGISTICS_DELAY");
        List<ActiveProposal> active = jdbc.query(
                "select id, proposal_id, revision_number, ticket_id, content_digest, status "
                        + "from compensation_proposal_revision where order_reference = ? "
                        + "and reason_code = 'LOGISTICS_DELAY' "
                        + "and status in ('PENDING_APPROVAL', 'APPROVED') for update",
                (rs, row) -> new ActiveProposal(
                        rs.getObject(1, UUID.class), rs.getObject(2, UUID.class), rs.getInt(3),
                        rs.getObject(4, UUID.class), rs.getString(5), rs.getString(6)),
                content.orderReference());
        String contentDigest = content.digest();
        if (!active.isEmpty() && !active.getFirst().ticketId().equals(content.ticketId())) {
            throw new ActiveIntentException("ACTIVE_COMPENSATION_INTENT_CONFLICT");
        }
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
            jdbc.update(
                    "update compensation_proposal_revision set status = 'SUPERSEDED' where id = ?",
                    previous.id());
            proposalId = previous.proposalId();
            revisionNumber = previous.revisionNumber() + 1;
        }

        UUID revisionId = UUID.randomUUID();
        Instant now = clock.instant();
        Timestamp databaseTime = Timestamp.from(now);
        jdbc.update(
                "insert into compensation_proposal_revision "
                        + "(id, proposal_id, revision_number, ticket_id, order_reference, generation_id, "
                        + "delay_hours, delay_seconds, compensation_method, amount, reason_code, "
                        + "evidence_references, policy_version, content_digest, status, created_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LOGISTICS_DELAY', "
                        + "jsonb_build_array(?, ?), ?, ?, 'PENDING_APPROVAL', ?)",
                revisionId, proposalId, revisionNumber, content.ticketId(), content.orderReference(),
                content.generationId(), content.delayHours(), content.delaySeconds(), content.method(),
                content.amount(), content.evidenceReferences().get(0), content.evidenceReferences().get(1),
                content.policyVersion(), contentDigest, databaseTime);
        jdbc.update(
                "insert into approval_evidence_snapshot "
                        + "(proposal_revision_id, order_reference, delay_hours, delay_seconds, paid_amount, "
                        + "available_compensation_amount, active_reservation_amount, paid, cancelled, "
                        + "fully_refunded, existing_compensation, evidence_references, captured_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, jsonb_build_array(?, ?), ?)",
                revisionId, content.orderReference(), content.delayHours(), content.delaySeconds(),
                content.paidAmount(), content.availableAmount(), content.activeReservationAmount(),
                content.paid(), content.cancelled(), content.fullyRefunded(), content.existingCompensation(),
                content.evidenceReferences().get(0), content.evidenceReferences().get(1), databaseTime);
        return new StoredProposal(revisionId, revisionNumber, true);
    }

    record ProposalContent(
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
            BigDecimal availableAmount,
            BigDecimal activeReservationAmount,
            boolean paid,
            boolean cancelled,
            boolean fullyRefunded,
            boolean existingCompensation) {
        String digest() {
            return StableParameterDigest.sha256(
                    ticketId.toString(), orderReference, Long.toString(delaySeconds), method,
                    amount.toPlainString(), "LOGISTICS_DELAY", String.join("\n", evidenceReferences),
                    policyVersion, paidAmount.toPlainString(), availableAmount.toPlainString(),
                    activeReservationAmount.toPlainString(), Boolean.toString(paid),
                    Boolean.toString(cancelled), Boolean.toString(fullyRefunded),
                    Boolean.toString(existingCompensation));
        }
    }

    record StoredProposal(UUID revisionId, int revisionNumber, boolean created) {}

    static final class ActiveIntentException extends RuntimeException {
        private final String reason;

        ActiveIntentException(String reason) {
            this.reason = reason;
        }

        String reason() {
            return reason;
        }
    }

    private record ActiveProposal(
            UUID id, UUID proposalId, int revisionNumber, UUID ticketId,
            String contentDigest, String status) {}
}
