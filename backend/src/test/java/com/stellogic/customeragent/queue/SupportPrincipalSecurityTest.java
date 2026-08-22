package com.stellogic.customeragent.queue;

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

    @Test
    void forgedSupportHeaderCannotReplaceTheAuthenticatedSupportPrincipal() throws Exception {
        when(service.snapshot("support-demo"))
                .thenReturn(
                        new SupportWorkbenchSnapshot(
                                "support-workbench-v1", 0, List.of(), List.of()));

        mvc.perform(
                        get("/api/support/workbench/snapshot")
                                .session(login("support-demo"))
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
                                .session(login("customer-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
        mvc.perform(
                        get("/api/support/workbench/snapshot")
                                .session(login("approver-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
    }

    @Test
    void supportClaimRequiresCurrentCsrfAndAlwaysUsesThePrincipalAsAssignee() throws Exception {
        when(service.claim("support-demo", TICKET_ID))
                .thenReturn(new SupportAssignmentClaim(TICKET_ID, "support-demo", false));
        MockHttpSession support = login("support-demo");

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
                                .header("X-CSRF-TOKEN", token(csrf))
                                .header("X-Synthetic-Support-Id", "internal-demo"))
                .andExpect(status().isCreated());

        verify(service).claim("support-demo", TICKET_ID);
    }

    private MockHttpSession login(String username) throws Exception {
        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession anonymous = (MockHttpSession) csrf.getRequest().getSession(false);
        MvcResult login =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(anonymous)
                                        .header("X-CSRF-TOKEN", token(csrf))
                                        .param("username", username)
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();
        return (MockHttpSession) login.getRequest().getSession(false);
    }

    private String token(MvcResult csrf) throws Exception {
        return json.readTree(csrf.getResponse().getContentAsString()).get("token").asText();
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestServices {
        @Bean
        SupportWorkbenchProjectionService supportWorkbenchProjectionService() {
            return mock(SupportWorkbenchProjectionService.class);
        }
    }
}
