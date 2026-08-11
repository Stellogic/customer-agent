package com.stellogic.customeragent.investigation;

import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.approval.CompensationProposalExpiry;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.jdbc.core.JdbcTemplate;

class JdbcCompensationProposalStoreTest {
    @Test
    void samplesServerTimeAfterLockingAndExpiringPriorOrderIntent() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        Clock clock = org.mockito.Mockito.mock(Clock.class);
        CompensationProposalExpiry expiry = org.mockito.Mockito.mock(CompensationProposalExpiry.class);
        when(clock.instant()).thenReturn(Instant.parse("2026-08-09T14:00:00Z"));
        var store = new JdbcCompensationProposalStore(jdbc, clock, expiry);

        store.save(new JdbcCompensationProposalStore.ProposalContent(
                UUID.randomUUID(), UUID.randomUUID(), "ORDER-DELAY-001", 80, 288000,
                "SIMULATED_PARTIAL_REFUND", new BigDecimal("26.80"),
                List.of("order:ORDER-DELAY-001", "logistics:ORDER-DELAY-001"),
                "delay-policy-v1", new BigDecimal("268.00"), new BigDecimal("268.00"),
                new BigDecimal("0.00"), true, false, false, false));

        InOrder order = inOrder(expiry, clock);
        order.verify(expiry).expireDueForOrder("ORDER-DELAY-001");
        order.verify(clock).instant();
    }
}
