package com.stellogic.customeragent.queue;

import static com.stellogic.customeragent.identity.HumanSessionTestClient.login;
import static com.stellogic.customeragent.identity.HumanSessionTestClient.token;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.stellogic.customeragent.identity.AuthSessionController;
import com.stellogic.customeragent.identity.DemoAccountController;
import com.stellogic.customeragent.identity.HumanSecurityConfiguration;
import com.stellogic.customeragent.identity.LocalDemoHumanAccountsConfiguration;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.ObjectMapper;

@WebMvcTest(
        controllers = {
            SupportWorkbenchController.class,
            SharedSupportQueueController.class,
            AuthSessionController.class,
            DemoAccountController.class
        })
@Import({
    HumanSecurityConfiguration.class,
    LocalDemoHumanAccountsConfiguration.class,
    SupportWorkbenchExceptionHandler.class,
    SupportPrincipalSecurityTest.TestServices.class
})
@ActiveProfiles("local-demo")
class SupportPrincipalSecurityTest {
    private static final UUID TICKET_ID = UUID.fromString("75000000-0000-0000-0000-000000000001");
    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper json;
    @Autowired private SupportWorkbenchProjectionService service;
    @Autowired private SharedSupportQueueProjectionService sharedQueue;

    @Test
    void forgedSupportHeaderCannotReplaceTheAuthenticatedSupportPrincipal() throws Exception {
        when(service.snapshot("support-demo"))
                .thenReturn(
                        new SupportWorkbenchSnapshot(
                                "support-workbench-v1", 0, List.of(), List.of()));

        mvc.perform(
                        get("/api/support/workbench/snapshot")
                                .session(login(mvc, json, "support-demo"))
                                .header("X-Synthetic-Support-Id", "internal-demo"))
                .andExpect(status().isOk());

        verify(service).snapshot("support-demo");
    }

    @Test
    void anonymousCustomerAndApproverCannotUseForgedSupportHeaders() throws Exception {
        mvc.perform(
                        get("/api/support/workbench/snapshot")
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isUnauthorized());
        mvc.perform(
                        get("/api/support/workbench/snapshot")
                                .session(login(mvc, json, "customer-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
        mvc.perform(
                        get("/api/support/workbench/snapshot")
                                .session(login(mvc, json, "approver-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
    }

    @Test
    void supportAndDualRolePrincipalsCanReadTheMinimalSharedQueue() throws Exception {
        when(sharedQueue.queue()).thenReturn(List.of());

        mvc.perform(
                        get("/api/support/queue")
                                .session(login(mvc, json, "support-demo"))
                                .header("X-Synthetic-Support-Id", "approver-demo"))
                .andExpect(status().isOk());
        mvc.perform(get("/api/support/queue").session(login(mvc, json, "internal-demo")))
                .andExpect(status().isOk());
        mvc.perform(
                        get("/api/support/queue")
                                .session(login(mvc, json, "customer-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/support/queue").header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void detailsAndEventsRemainBehindTheSameSupportRoleBoundary() throws Exception {
        when(service.details("support-demo", TICKET_ID))
                .thenThrow(new SupportTicketNotFoundException());

        mvc.perform(
                        get("/api/support/workbench/tickets/{ticketId}", TICKET_ID)
                                .session(login(mvc, json, "support-demo")))
                .andExpect(status().isNotFound());
        mvc.perform(
                        get("/api/support/workbench/tickets/{ticketId}", TICKET_ID)
                                .session(login(mvc, json, "customer-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
        mvc.perform(
                        get("/api/support/workbench/events")
                                .session(login(mvc, json, "approver-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
        mvc.perform(
                        get("/api/support/workbench/events")
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void supportClaimRequiresCurrentCsrfAndAlwaysUsesThePrincipalAsAssignee() throws Exception {
        when(service.claim("support-demo", TICKET_ID))
                .thenReturn(new SupportAssignmentClaim(TICKET_ID, "support-demo", false));
        MockHttpSession support = login(mvc, json, "support-demo");

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/claims", TICKET_ID)
                                .session(support))
                .andExpect(status().isForbidden());

        MvcResult csrf =
                mvc.perform(get("/api/auth/csrf").session(support))
                        .andExpect(status().isOk())
                        .andReturn();
        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/claims", TICKET_ID)
                                .session(support)
                                .header("X-CSRF-TOKEN", token(json, csrf))
                                .header("X-Synthetic-Support-Id", "internal-demo"))
                .andExpect(status().isCreated());

        verify(service).claim("support-demo", TICKET_ID);
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestServices {
        @Bean
        SupportWorkbenchProjectionService supportWorkbenchProjectionService() {
            return mock(SupportWorkbenchProjectionService.class);
        }

        @Bean
        SharedSupportQueueProjectionService sharedSupportQueueProjectionService() {
            return mock(SharedSupportQueueProjectionService.class);
        }
    }
}
