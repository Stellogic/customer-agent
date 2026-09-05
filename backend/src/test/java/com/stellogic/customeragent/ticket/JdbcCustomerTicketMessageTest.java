package com.stellogic.customeragent.ticket;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockingDetails;

import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import java.time.Clock;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

class JdbcCustomerTicketMessageTest {
    @Test
    void persistsTheCustomerWordsSeparatelyFromTheModelSummary() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        JdbcCustomerTicketService service =
                new JdbcCustomerTicketService(
                        jdbc,
                        Clock.systemUTC(),
                        mock(TicketAuthorityLock.class),
                        new ObjectMapper());

        service.create(
                new CreateCustomerTicket(
                        "customer-demo",
                        "intake-request",
                        "ORDER-223",
                        "物流状态查询摘要",
                        List.of("请解释物流状态".repeat(150), "请立即补偿".repeat(200)),
                        "LOGISTICS_DELAY"));

        var writes = mockingDetails(jdbc).getInvocations().stream().toList();
        var ticket =
                writes.stream()
                        .filter(
                                call ->
                                        call.getArgument(0, String.class)
                                                .startsWith("insert into support_ticket"))
                        .findFirst()
                        .orElseThrow();
        var messages =
                writes.stream()
                        .filter(
                                call ->
                                        call.getArgument(0, String.class)
                                                .contains("values (?, ?, ?, 'CUSTOMER'"))
                        .toList();
        assertThat(ticket.getArgument(4, String.class)).isEqualTo("物流状态查询摘要");
        assertThat(messages).hasSize(2);
        assertThat(messages.get(0).getArgument(3, Integer.class)).isEqualTo(1);
        assertThat(messages.get(0).getArgument(4, String.class)).isEqualTo("请解释物流状态".repeat(150));
        assertThat(messages.get(1).getArgument(3, Integer.class)).isEqualTo(2);
        assertThat(messages.get(1).getArgument(4, String.class)).isEqualTo("请立即补偿".repeat(200));
    }
}
