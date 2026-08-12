package com.stellogic.customeragent.approval;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class CompensationProposalExpiryTest {
    @SuppressWarnings("unchecked")
    @Test
    void samplesServerTimeOnlyAfterLockingPendingOrderRevisions() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        Clock clock = org.mockito.Mockito.mock(Clock.class);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of());
        Instant now = Instant.parse("2026-08-09T14:00:00Z");
        when(clock.instant()).thenReturn(now);
        var expiry = new CompensationProposalExpiry(jdbc, clock);

        org.assertj.core.api.Assertions.assertThat(expiry.expireDueForOrder("ORDER-DELAY-001"))
                .isEqualTo(now);

        InOrder order = inOrder(jdbc, clock);
        order.verify(jdbc)
                .query(contains("for update"), any(RowMapper.class), eq("ORDER-DELAY-001"));
        order.verify(clock).instant();
    }
}
