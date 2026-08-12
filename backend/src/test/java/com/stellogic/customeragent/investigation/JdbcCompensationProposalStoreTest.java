package com.stellogic.customeragent.investigation;

import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.approval.CompensationProposalExpiry;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;

class JdbcCompensationProposalStoreTest {
    @Test
    void reusesTheLockProtectedExpiryTimeForTheNewRevision() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        CompensationProposalExpiry expiry =
                org.mockito.Mockito.mock(CompensationProposalExpiry.class);
        Instant lockProtectedNow = Instant.parse("2026-08-09T14:00:00Z");
        when(expiry.expireDueForOrder("ORDER-DELAY-001")).thenReturn(lockProtectedNow);
        var store = new JdbcCompensationProposalStore(jdbc, expiry);

        store.save(
                new JdbcCompensationProposalStore.ProposalContent(
                        UUID.randomUUID(),
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

        verify(expiry).expireDueForOrder("ORDER-DELAY-001");
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
}
