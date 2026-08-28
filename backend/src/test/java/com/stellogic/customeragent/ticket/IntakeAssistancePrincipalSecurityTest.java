package com.stellogic.customeragent.ticket;

import static com.stellogic.customeragent.identity.HumanSessionTestClient.login;
import static org.mockito.Mockito.mock;
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
            IntakeAssistanceController.class,
            AuthSessionController.class,
            DemoAccountController.class
        })
@Import({
    HumanSecurityConfiguration.class,
    LocalDemoHumanAccountsConfiguration.class,
    IntakeAssistanceExceptionHandler.class,
    IntakeAssistancePrincipalSecurityTest.TestServices.class
})
@ActiveProfiles("local-demo")
class IntakeAssistancePrincipalSecurityTest {
    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper json;
    @Autowired private IntakeAssistanceService service;

    @Test
    void onlySupportRoleCanReadTheSeparateIntakeAssistanceQueue() throws Exception {
        when(service.snapshot("support-demo"))
                .thenReturn(new IntakeAssistanceSnapshot("intake-assistance-v1", 0, List.of()));

        mvc.perform(
                        get("/api/support/intake-assistance/snapshot")
                                .session(login(mvc, json, "support-demo")))
                .andExpect(status().isOk());
        mvc.perform(
                        get("/api/support/intake-assistance/snapshot")
                                .session(login(mvc, json, "customer-demo")))
                .andExpect(status().isForbidden());
        mvc.perform(
                        get("/api/support/intake-assistance/snapshot")
                                .session(login(mvc, json, "approver-demo")))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/support/intake-assistance/snapshot"))
                .andExpect(status().isUnauthorized());
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestServices {
        @Bean
        IntakeAssistanceService intakeAssistanceService() {
            return mock(IntakeAssistanceService.class);
        }
    }
}
