package com.stellogic.customeragent.investigation;

import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.approval.CompensationProposalExpiry;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.springframework.jdbc.core.JdbcTemplate;

class JdbcCompensationProposalStoreTest {
    @Test
    void immutableProposalDigestCoversBothDelayRepresentations() {
        UUID ticketId = UUID.randomUUID();
        UUID generationId = UUID.randomUUID();
        var original = proposalContent(ticketId, generationId, 80, 288000);
        var same = proposalContent(ticketId, UUID.randomUUID(), 80, 288000);
        var hoursChanged = proposalContent(ticketId, UUID.randomUUID(), 81, 288000);
        var secondsChanged = proposalContent(ticketId, UUID.randomUUID(), 80, 288001);

        org.assertj.core.api.Assertions.assertThat(same.digest()).isEqualTo(original.digest());
        org.assertj.core.api.Assertions.assertThat(hoursChanged.digest())
                .isNotEqualTo(original.digest());
        org.assertj.core.api.Assertions.assertThat(secondsChanged.digest())
                .isNotEqualTo(original.digest());
    }

    @Test
    void reusesTheLockProtectedExpiryTimeForTheNewRevision() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        CompensationProposalExpiry expiry =
                org.mockito.Mockito.mock(CompensationProposalExpiry.class);
        Instant lockProtectedNow = Instant.parse("2026-08-09T14:00:00Z");
        UUID ticketId = UUID.randomUUID();
        UUID existingProposalId = UUID.randomUUID();
        when(jdbc.query(
                        org.mockito.ArgumentMatchers.contains("select distinct proposal_id"),
                        org.mockito.ArgumentMatchers
                                .<org.springframework.jdbc.core.RowMapper<UUID>>any(),
                        org.mockito.ArgumentMatchers.eq(ticketId)))
                .thenReturn(List.of(existingProposalId));
        when(expiry.expireDueForTicket(ticketId)).thenReturn(lockProtectedNow);
        var store = new JdbcCompensationProposalStore(jdbc, expiry);

        store.save(
                new JdbcCompensationProposalStore.ProposalContent(
                        ticketId,
                        UUID.randomUUID(),
                        "ORDER-DELAY-001",
                        80,
                        288000,
                        "SIMULATED_PARTIAL_REFUND",
                        new BigDecimal("26.80"),
                        List.of("order:ORDER-DELAY-001", "logistics:ORDER-DELAY-001"),
                        "delay-policy-v1",
                        new BigDecimal("268.00"),
                        new BigDecimal("268.00"),
                        new BigDecimal("0.00"),
                        new BigDecimal("268.00"),
                        true,
                        false,
                        false,
                        false));

        verify(expiry).expireDueForTicket(ticketId);
        InOrder lockOrder = inOrder(jdbc, expiry);
        lockOrder
                .verify(jdbc)
                .query(
                        org.mockito.ArgumentMatchers.contains("select distinct proposal_id"),
                        org.mockito.ArgumentMatchers
                                .<org.springframework.jdbc.core.RowMapper<UUID>>any(),
                        org.mockito.ArgumentMatchers.eq(ticketId));
        lockOrder
                .verify(jdbc)
                .query(
                        org.mockito.ArgumentMatchers.contains(
                                "pg_advisory_xact_lock(hashtextextended"),
                        org.mockito.ArgumentMatchers
                                .<org.springframework.jdbc.core.ResultSetExtractor<Void>>any(),
                        org.mockito.ArgumentMatchers.eq(
                                existingProposalId + "\nPROPOSAL_SUPPORT_PARTICIPANT_LINEAGE"));
        lockOrder.verify(expiry).expireDueForTicket(ticketId);
        ArgumentCaptor<Object[]> arguments = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc, atLeastOnce())
                .update(
                        org.mockito.ArgumentMatchers.contains(
                                "insert into compensation_proposal_revision"),
                        arguments.capture());
        Object[] insertArguments = arguments.getValue();
        org.assertj.core.api.Assertions.assertThat(insertArguments)
                .contains(java.sql.Timestamp.from(lockProtectedNow));
        org.assertj.core.api.Assertions.assertThat(insertArguments)
                .contains(java.sql.Timestamp.from(lockProtectedNow.plusSeconds(24 * 60 * 60)));
    }

    private static JdbcCompensationProposalStore.ProposalContent proposalContent(
            UUID ticketId, UUID generationId, int delayHours, long delaySeconds) {
        return new JdbcCompensationProposalStore.ProposalContent(
                ticketId,
                generationId,
                "ORDER-DELAY-001",
                delayHours,
                delaySeconds,
                "SIMULATED_PARTIAL_REFUND",
                new BigDecimal("26.80"),
                List.of("order:ORDER-DELAY-001", "logistics:ORDER-DELAY-001"),
                "delay-policy-v1",
                new BigDecimal("268.00"),
                new BigDecimal("268.00"),
                new BigDecimal("0.00"),
                new BigDecimal("268.00"),
                true,
                false,
                false,
                false);
    }
}
