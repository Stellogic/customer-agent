package com.stellogic.customeragent.group;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class OrderTicketGroupControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("15700000-0000-0000-0000-000000000001");
    private final OrderTicketGroupService service =
            org.mockito.Mockito.mock(OrderTicketGroupService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new OrderTicketGroupController(service))
                    .defaultRequest(get("/").session(session("customer-demo")))
                    .build();

    @Test
    void customerReadsOnlyOwnOrderGroupedTicketSummariesAndPendingItems() throws Exception {
        when(service.customerGroups("customer-demo"))
                .thenReturn(
                        List.of(
                                new CustomerOrderTicketGroup(
                                        "ORDER-157",
                                        List.of(
                                                new OrderTicketSummary(
                                                        TICKET_ID,
                                                        "PACKAGE_NOT_RECEIVED",
                                                        "WAITING_FOR_CUSTOMER",
                                                        "AGENT",
                                                        "WAITING_FOR_CUSTOMER",
                                                        true,
                                                        false)),
                                        List.of(
                                                new PendingCustomerItem(
                                                        TICKET_ID,
                                                        "CLARIFICATION",
                                                        "请确认包裹是否由本人签收")))));

        mvc.perform(get("/api/customer/v2/order-ticket-groups").principal(customer()))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.view").value("CUSTOMER_ORDER_TICKET_GROUPS"))
                .andExpect(jsonPath("$.schema").value("customer-order-ticket-groups-v1"))
                .andExpect(jsonPath("$.groups[0].orderReference").value("ORDER-157"))
                .andExpect(jsonPath("$.groups[0].tickets[0].ticketId").value(TICKET_ID.toString()))
                .andExpect(
                        jsonPath("$.groups[0].tickets[0].issueKind").value("PACKAGE_NOT_RECEIVED"))
                .andExpect(
                        jsonPath("$.groups[0].tickets[0].controlledProgress")
                                .value("WAITING_FOR_CUSTOMER"))
                .andExpect(
                        jsonPath("$.groups[0].pendingCustomerItems[0].ticketId")
                                .value(TICKET_ID.toString()))
                .andExpect(jsonPath("$.groups[0].tickets[0].conversation").doesNotExist())
                .andExpect(jsonPath("$.groups[0].tickets[0].internalNotes").doesNotExist())
                .andExpect(jsonPath("$.groups[0].tickets[0].agentThreadId").doesNotExist());
    }

    private static UsernamePasswordAuthenticationToken customer() {
        return UsernamePasswordAuthenticationToken.authenticated("customer-demo", "n/a", List.of());
    }
}
