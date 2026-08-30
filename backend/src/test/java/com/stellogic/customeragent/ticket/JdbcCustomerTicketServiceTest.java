package com.stellogic.customeragent.ticket;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

class JdbcCustomerTicketServiceTest {
    private static final UUID TICKET_ID = UUID.fromString("25000000-0000-0000-0000-000000000025");

    @Test
    void trimmedReplayHistoryRequiresAnAuthoritativeSnapshot() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        JdbcCustomerTicketService service =
                spy(
                        new JdbcCustomerTicketService(
                                jdbc,
                                Clock.fixed(Instant.parse("2026-08-11T00:00:00Z"), ZoneOffset.UTC),
                                mock(TicketAuthorityLock.class)));
        var snapshot =
                new CustomerPublicSnapshot(
                        TICKET_ID,
                        "INVESTIGATING",
                        "AGENT",
                        Instant.parse("2026-08-11T00:00:00Z"),
                        Instant.parse("2026-08-11T00:00:00Z"),
                        "customer-public-v1",
                        8,
                        1,
                        List.of(),
                        null,
                        null,
                        null);
        doReturn(snapshot).when(service).snapshot("customer-demo", TICKET_ID);
        when(jdbc.queryForObject(
                        anyString(), eq(Long.class), eq(TICKET_ID), eq("customer-public-v1")))
                .thenReturn(5L);

        assertThatThrownBy(() -> service.events("customer-demo", TICKET_ID, "customer-public-v1:2"))
                .isInstanceOf(ProjectionCursorException.class);
    }
}
