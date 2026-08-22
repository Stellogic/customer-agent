package com.stellogic.customeragent.sla;

import static com.stellogic.customeragent.identity.HumanSessionTestClient.login;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.stellogic.customeragent.identity.AuthSessionController;
import com.stellogic.customeragent.identity.DemoAccountController;
import com.stellogic.customeragent.identity.HumanSecurityConfiguration;
import com.stellogic.customeragent.identity.LocalDemoHumanAccountsConfiguration;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import tools.jackson.databind.ObjectMapper;

@WebMvcTest(
        controllers = {
            SupportSlaController.class,
            AuthSessionController.class,
            DemoAccountController.class
        })
@Import({
    HumanSecurityConfiguration.class,
    LocalDemoHumanAccountsConfiguration.class,
    SupportSlaPrincipalSecurityTest.TestServices.class
})
@ActiveProfiles("local-demo")
class SupportSlaPrincipalSecurityTest {
    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper json;
    @Autowired private SupportSlaProjectionService service;

    @Test
    void supportAndDualRolePrincipalsReadOnlyTheirAuthorizedSlaSurfaces() throws Exception {
        when(service.notifications("support-demo")).thenReturn(List.of());
        when(service.notifications("internal-demo")).thenReturn(List.of());
        when(service.escalations()).thenReturn(List.of());

        mvc.perform(get("/api/support/sla/notifications").session(login(mvc, json, "support-demo")))
                .andExpect(status().isOk());
        mvc.perform(
                        get("/api/support/sla/notifications")
                                .session(login(mvc, json, "internal-demo")))
                .andExpect(status().isOk());
        mvc.perform(get("/api/support/escalations").session(login(mvc, json, "support-demo")))
                .andExpect(status().isOk());

        verify(service).notifications("support-demo");
        verify(service).notifications("internal-demo");
    }

    @Test
    void anonymousCustomerAndApproverCannotForgeSupportSlaAccess() throws Exception {
        mvc.perform(
                        get("/api/support/escalations")
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isUnauthorized());
        mvc.perform(
                        get("/api/support/escalations")
                                .session(login(mvc, json, "customer-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
        mvc.perform(
                        get("/api/support/sla/notifications")
                                .session(login(mvc, json, "approver-demo"))
                                .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isForbidden());
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestServices {
        @Bean
        SupportSlaProjectionService supportSlaProjectionService() {
            return mock(SupportSlaProjectionService.class);
        }
    }
}
