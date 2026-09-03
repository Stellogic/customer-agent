package com.stellogic.customeragent.handoff;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CustomerHumanHandoffControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("18000000-0000-0000-0000-000000000001");
    private final HumanHandoffService service = org.mockito.Mockito.mock(HumanHandoffService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new CustomerHumanHandoffController(service)).build();

    @Test
    void customerRequestsHumanHandlingWithAStableIdentity() throws Exception {
        when(service.request(any()))
                .thenReturn(new HumanHandoffResult("handoff-18", "HUMAN", false));

        mvc.perform(
                        post("/api/customer/v2/tickets/{ticketId}/human-handoff", TICKET_ID)
                                .principal(customer())
                                .header("Idempotency-Key", "handoff-18")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"reasonCode\":\"CUSTOMER_REQUESTED\"}"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.requestId").value("handoff-18"))
                .andExpect(jsonPath("$.handlingMode").value("HUMAN"))
                .andExpect(jsonPath("$.replayed").value(false))
                .andExpect(jsonPath("$.internalReason").doesNotExist());

        verify(service).request(argThat(command -> command.customerId().equals("customer-demo")));
    }

    @Test
    void customerCanReconcileAnUnknownResponseByStableIdentity() throws Exception {
        when(service.status("customer-demo", TICKET_ID, "handoff-18"))
                .thenReturn(new HumanHandoffResult("handoff-18", "HUMAN", true));

        mvc.perform(
                        get(
                                        "/api/customer/v2/tickets/{ticketId}/human-handoff-requests/{requestId}",
                                        TICKET_ID,
                                        "handoff-18")
                                .principal(customer()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.handlingMode").value("HUMAN"))
                .andExpect(jsonPath("$.replayed").value(true));
    }

    private UsernamePasswordAuthenticationToken customer() {
        return UsernamePasswordAuthenticationToken.authenticated("customer-demo", "n/a", List.of());
    }
}
