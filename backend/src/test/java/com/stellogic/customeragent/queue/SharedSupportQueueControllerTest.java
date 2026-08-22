package com.stellogic.customeragent.queue;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class SharedSupportQueueControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("18000000-0000-0000-0000-000000000004");
    private final SharedSupportQueueProjectionService service =
            org.mockito.Mockito.mock(SharedSupportQueueProjectionService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new SharedSupportQueueController(service)).build();

    @Test
    void queueCarriesCustomerRequestedHandoffsWithoutLeakingDetails() throws Exception {
        when(service.queue())
                .thenReturn(
                        List.of(
                                new SharedQueueSummary(
                                        TICKET_ID,
                                        "WAITING_FOR_CUSTOMER",
                                        "HUMAN",
                                        List.of("CUSTOMER_REQUESTED_HANDOFF"),
                                        Instant.parse("2026-08-09T14:00:00Z"))));

        mvc.perform(get("/api/support/queue").principal(support()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].ticketId").value(TICKET_ID.toString()))
                .andExpect(jsonPath("$[0].lifecycleState").value("WAITING_FOR_CUSTOMER"))
                .andExpect(jsonPath("$[0].handlingMode").value("HUMAN"))
                .andExpect(jsonPath("$[0].reasonCodes[0]").value("CUSTOMER_REQUESTED_HANDOFF"))
                .andExpect(jsonPath("$[0].customerId").doesNotExist())
                .andExpect(jsonPath("$[0].description").doesNotExist())
                .andExpect(jsonPath("$[0].messages").doesNotExist());
    }

    private static UsernamePasswordAuthenticationToken support() {
        return UsernamePasswordAuthenticationToken.authenticated("support-demo", "n/a", List.of());
    }
}
