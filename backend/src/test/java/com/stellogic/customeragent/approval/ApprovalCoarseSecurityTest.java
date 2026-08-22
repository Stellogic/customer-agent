package com.stellogic.customeragent.approval;

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
            ApprovalController.class,
            AuthSessionController.class,
            DemoAccountController.class
        })
@Import({
    HumanSecurityConfiguration.class,
    LocalDemoHumanAccountsConfiguration.class,
    ApprovalCoarseSecurityTest.TestServices.class
})
@ActiveProfiles("local-demo")
class ApprovalCoarseSecurityTest {
    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper json;
    @Autowired private ApprovalService service;

    @Test
    void supportSessionCannotTurnAnApproverHeaderIntoApprovalCapability() throws Exception {
        mvc.perform(
                        get("/api/approver/compensation-proposals")
                                .session(login(mvc, json, "support-demo"))
                                .header("X-Synthetic-Approver-Id", "approver-demo"))
                .andExpect(status().isForbidden());
    }

    @Test
    void approverSessionKeepsTheExistingBusinessIdentityHeaderContract() throws Exception {
        when(service.queue()).thenReturn(List.of());

        mvc.perform(
                        get("/api/approver/compensation-proposals")
                                .session(login(mvc, json, "approver-demo"))
                                .header("X-Synthetic-Approver-Id", "approver-demo"))
                .andExpect(status().isOk());

        mvc.perform(
                        get("/api/approver/compensation-proposals")
                                .header("X-Synthetic-Approver-Id", "approver-demo"))
                .andExpect(status().isUnauthorized());
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestServices {
        @Bean
        ApprovalService approvalService() {
            return mock(ApprovalService.class);
        }
    }
}
