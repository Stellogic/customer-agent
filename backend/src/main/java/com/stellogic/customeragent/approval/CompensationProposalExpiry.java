package com.stellogic.customeragent.approval;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public final class CompensationProposalExpiry {
    private final JdbcTemplate jdbc;
    private final Clock clock;

    public CompensationProposalExpiry(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    public void expireDue(Instant now) {
        List<UUID> revisionIds = jdbc.query(
                "select id from compensation_proposal_revision "
                        + "where status = 'PENDING_APPROVAL' and expires_at <= ? for update skip locked",
                (rs, row) -> rs.getObject(1, UUID.class), Timestamp.from(now));
        revisionIds.forEach(revisionId -> expireLocked(revisionId, now));
    }

    public void expireDueForOrder(String orderReference) {
        List<PendingRevision> revisions = jdbc.query(
                "select id, expires_at from compensation_proposal_revision where order_reference = ? "
                        + "and reason_code = 'LOGISTICS_DELAY' and status = 'PENDING_APPROVAL' "
                        + "for update",
                (rs, row) -> new PendingRevision(
                        rs.getObject(1, UUID.class), rs.getTimestamp(2).toInstant()), orderReference);
        Instant now = clock.instant();
        revisions.stream()
                .filter(revision -> !revision.expiresAt().isAfter(now))
                .forEach(revision -> expireLocked(revision.id(), now));
    }

    public boolean expireIfDue(UUID revisionId, Instant now) {
        List<UUID> due = jdbc.query(
                "select id from compensation_proposal_revision where id = ? "
                        + "and status = 'PENDING_APPROVAL' and expires_at <= ? for update",
                (rs, row) -> rs.getObject(1, UUID.class), revisionId, Timestamp.from(now));
        if (due.isEmpty()) return false;
        expireLocked(revisionId, now);
        return true;
    }

    private void expireLocked(UUID revisionId, Instant now) {
        List<ExpiryScope> scopes = jdbc.query(
                "select p.ticket_id, l.lease_version from compensation_proposal_revision p "
                        + "left join approval_lease l on l.proposal_revision_id = p.id and l.status = 'ACTIVE' "
                        + "where p.id = ? and p.status = 'PENDING_APPROVAL' for update of p",
                (rs, row) -> new ExpiryScope(
                        rs.getObject(1, UUID.class), rs.getObject(2, Long.class)), revisionId);
        if (scopes.isEmpty()) return;
        ExpiryScope scope = scopes.getFirst();
        int updated = jdbc.update(
                "update compensation_proposal_revision set status = 'EXPIRED' "
                        + "where id = ? and status = 'PENDING_APPROVAL'",
                revisionId);
        if (updated != 1) return;
        Timestamp at = Timestamp.from(now);
        jdbc.update(
                "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id) "
                        + "values (?, 'COMPENSATION_PROPOSAL_REVISION_EXPIRED', 'spring-system', ?, "
                        + "'COMPENSATION_PROPOSAL_REVISION', ?)",
                scope.ticketId(), at, revisionId);
        if (scope.leaseVersion() != null) {
            jdbc.update(
                    "insert into audit_event (ticket_id, event_type, actor_id, occurred_at, subject_type, "
                            + "subject_id, authorization_version) values (?, 'APPROVAL_LEASE_REVOKED', "
                            + "'spring-system', ?, 'COMPENSATION_PROPOSAL_REVISION', ?, ?)",
                    scope.ticketId(), at, revisionId, scope.leaseVersion());
        }
    }

    private record ExpiryScope(UUID ticketId, Long leaseVersion) {}
    private record PendingRevision(UUID id, Instant expiresAt) {}
}
