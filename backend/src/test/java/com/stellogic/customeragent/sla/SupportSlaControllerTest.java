package com.stellogic.customeragent.sla;

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

class SupportSlaControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("17000000-0000-0000-0000-000000000001");
    private final SupportSlaProjectionService service =
            org.mockito.Mockito.mock(SupportSlaProjectionService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new SupportSlaController(service)).build();

    @Test
    void currentAssigneeReceivesOnlyItsWarningProjection() throws Exception {
        when(service.notifications("support-demo"))
                .thenReturn(
                        List.of(
                                new SlaWarningNotification(
                                        TICKET_ID,
                                        "RESOLUTION",
                                        Instant.parse("2026-08-09T14:00:00Z"))));

        mvc.perform(get("/api/support/sla/notifications").principal(support()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].ticketId").value(TICKET_ID.toString()))
                .andExpect(jsonPath("$[0].objective").value("RESOLUTION"))
                .andExpect(jsonPath("$[0].description").doesNotExist());
    }

    @Test
    void sharedQueueExposesOnlyTheConfirmedMinimumSummary() throws Exception {
        when(service.escalations())
                .thenReturn(
                        List.of(
                                new SharedEscalationSummary(
                                        TICKET_ID,
                                        "INVESTIGATING",
                                        "AGENT",
                                        "SLA_BREACH",
                                        List.of("RESOLUTION"),
                                        Instant.parse("2026-08-09T14:00:00Z"))));

        mvc.perform(get("/api/support/escalations").principal(support()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].reasonCode").value("SLA_BREACH"))
                .andExpect(jsonPath("$[0].lifecycleState").value("INVESTIGATING"))
                .andExpect(jsonPath("$[0].customerId").doesNotExist())
                .andExpect(jsonPath("$[0].orderReference").doesNotExist())
                .andExpect(jsonPath("$[0].description").doesNotExist())
                .andExpect(jsonPath("$[0].messages").doesNotExist())
                .andExpect(jsonPath("$[0].investigationFacts").doesNotExist());
    }

    private static UsernamePasswordAuthenticationToken support() {
        return UsernamePasswordAuthenticationToken.authenticated("support-demo", "n/a", List.of());
    }
}
