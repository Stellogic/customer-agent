package com.stellogic.customeragent.identity;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.ResultActions;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@WebMvcTest({AuthSessionController.class, DemoAccountController.class})
@Import({HumanSecurityConfiguration.class, LocalDemoHumanAccountsConfiguration.class})
@ActiveProfiles("local-demo")
@ExtendWith(OutputCaptureExtension.class)
class HumanSessionSecurityTest {
    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper json;

    @Test
    void localDemoListsOnlyFourHumanAccountsForFormPrefill() throws Exception {
        mvc.perform(get("/api/auth/demo-accounts"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(4))
                .andExpect(jsonPath("$[0].username").value("customer-demo"))
                .andExpect(jsonPath("$[1].username").value("support-demo"))
                .andExpect(jsonPath("$[2].username").value("approver-demo"))
                .andExpect(jsonPath("$[3].username").value("internal-demo"))
                .andExpect(jsonPath("$[0].password").value("local-demo-password"))
                .andExpect(jsonPath("$[?(@.username == 'agent-machine')]").isEmpty())
                .andExpect(jsonPath("$[?(@.username == 'executor-machine')]").isEmpty());
    }

    @Test
    void customerUsesPasswordLoginWithSessionFixationProtectionAndMinimalProjection()
            throws Exception {
        mvc.perform(get("/api/auth/session")).andExpect(status().isUnauthorized());

        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession anonymousSession = (MockHttpSession) csrf.getRequest().getSession(false);
        String anonymousSessionId = anonymousSession.getId();
        String token = json.readTree(csrf.getResponse().getContentAsString()).get("token").asText();

        MvcResult login =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(anonymousSession)
                                        .header("X-CSRF-TOKEN", token)
                                        .param("username", "customer-demo")
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();

        MockHttpSession authenticatedSession =
                (MockHttpSession) login.getRequest().getSession(false);
        assertThat(authenticatedSession.getId()).isNotEqualTo(anonymousSessionId);

        MvcResult current =
                mvc.perform(get("/api/auth/session").session(authenticatedSession))
                        .andExpect(status().isOk())
                        .andExpect(jsonPath("$.id").value("customer-demo"))
                        .andExpect(jsonPath("$.displayName").value("演示客户"))
                        .andExpect(jsonPath("$.subjectType").value("CUSTOMER"))
                        .andExpect(jsonPath("$.roles[0]").value("CUSTOMER"))
                        .andExpect(jsonPath("$.capabilities[0]").value("CUSTOMER_HELP_ACCESS"))
                        .andReturn();

        JsonNode projection = json.readTree(current.getResponse().getContentAsString());
        Set<String> fields = Set.copyOf(projection.propertyNames());
        assertThat(fields)
                .containsExactlyInAnyOrder(
                        "id", "displayName", "subjectType", "roles", "capabilities");
    }

    @Test
    void currentIdentityAndAuthenticationErrorsDoNotExposeCredentialsOrRouteAuthority()
            throws Exception {
        MvcResult anonymous =
                mvc.perform(get("/api/auth/session"))
                        .andExpect(status().isUnauthorized())
                        .andReturn();
        assertNoSensitiveContract(anonymous.getResponse().getContentAsString());

        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession session = (MockHttpSession) csrf.getRequest().getSession(false);
        MvcResult failedLogin =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(session)
                                        .header("X-CSRF-TOKEN", token(csrf))
                                        .param("username", "customer-demo")
                                        .param("password", "secret-value-79"))
                        .andExpect(status().isUnauthorized())
                        .andReturn();
        assertNoSensitiveContract(failedLogin.getResponse().getContentAsString());
    }

    @Test
    void csrfRotatesAcrossLoginAndLogoutAndRejectsMissingWrongOrOldTokens() throws Exception {
        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession anonymousSession = (MockHttpSession) csrf.getRequest().getSession(false);
        String anonymousToken = token(csrf);

        mvc.perform(
                        post("/api/auth/login")
                                .session(anonymousSession)
                                .param("username", "customer-demo")
                                .param("password", "local-demo-password"))
                .andExpect(status().isForbidden());
        mvc.perform(
                        post("/api/auth/login")
                                .session(anonymousSession)
                                .header("X-CSRF-TOKEN", "wrong-token")
                                .param("username", "customer-demo")
                                .param("password", "local-demo-password"))
                .andExpect(status().isForbidden());

        MvcResult login =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(anonymousSession)
                                        .header("X-CSRF-TOKEN", anonymousToken)
                                        .param("username", "customer-demo")
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();
        MockHttpSession authenticatedSession =
                (MockHttpSession) login.getRequest().getSession(false);

        MvcResult authenticatedCsrf =
                mvc.perform(get("/api/auth/csrf").session(authenticatedSession))
                        .andExpect(status().isOk())
                        .andReturn();
        String authenticatedToken = token(authenticatedCsrf);
        assertThat(authenticatedToken).isNotEqualTo(anonymousToken);

        mvc.perform(
                        post("/api/auth/logout")
                                .session(authenticatedSession)
                                .header("X-CSRF-TOKEN", anonymousToken))
                .andExpect(status().isForbidden());
        mvc.perform(
                        post("/api/auth/logout")
                                .session(authenticatedSession)
                                .header("X-CSRF-TOKEN", authenticatedToken))
                .andExpect(status().isNoContent());
        assertThat(authenticatedSession.isInvalid()).isTrue();
        mvc.perform(get("/api/auth/session")).andExpect(status().isUnauthorized());

        MvcResult postLogoutCsrf =
                mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        assertThat(token(postLogoutCsrf)).isNotEqualTo(authenticatedToken);
        MockHttpSession postLogoutSession =
                (MockHttpSession) postLogoutCsrf.getRequest().getSession(false);
        mvc.perform(
                        post("/api/auth/logout")
                                .session(postLogoutSession)
                                .header("X-CSRF-TOKEN", authenticatedToken))
                .andExpect(status().isForbidden());
    }

    @Test
    void everyLocalDemoAccountProjectsOnlyItsOwnRolesAndCapabilities() throws Exception {
        assertProjection(
                "customer-demo", "CUSTOMER", List.of("CUSTOMER"), List.of("CUSTOMER_HELP_ACCESS"));
        assertProjection(
                "support-demo",
                "INTERNAL",
                List.of("SUPPORT"),
                List.of("SUPPORT_WORKBENCH_ACCESS"));
        assertProjection(
                "approver-demo",
                "INTERNAL",
                List.of("APPROVER"),
                List.of("APPROVAL_WORKBENCH_ACCESS"));
        assertProjection(
                "internal-demo",
                "INTERNAL",
                List.of("SUPPORT", "APPROVER"),
                List.of("SUPPORT_WORKBENCH_ACCESS", "APPROVAL_WORKBENCH_ACCESS"));
    }

    @Test
    void loggingInAgainReplacesThePreviousSubjectInsteadOfCombiningIdentities() throws Exception {
        MvcResult anonymousCsrf =
                mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession session = (MockHttpSession) anonymousCsrf.getRequest().getSession(false);
        MvcResult customerLogin =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(session)
                                        .header("X-CSRF-TOKEN", token(anonymousCsrf))
                                        .param("username", "customer-demo")
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();
        MockHttpSession customerSession =
                (MockHttpSession) customerLogin.getRequest().getSession(false);
        MvcResult customerCsrf =
                mvc.perform(get("/api/auth/csrf").session(customerSession))
                        .andExpect(status().isOk())
                        .andReturn();
        String customerToken = token(customerCsrf);

        MvcResult supportLogin =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(customerSession)
                                        .header("X-CSRF-TOKEN", token(customerCsrf))
                                        .param("username", "support-demo")
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();
        MockHttpSession supportSession =
                (MockHttpSession) supportLogin.getRequest().getSession(false);
        MvcResult supportCsrf =
                mvc.perform(get("/api/auth/csrf").session(supportSession))
                        .andExpect(status().isOk())
                        .andReturn();
        String supportToken = token(supportCsrf);
        assertThat(supportToken).isNotEqualTo(customerToken);

        mvc.perform(get("/api/auth/session").session(supportSession))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("support-demo"))
                .andExpect(jsonPath("$.subjectType").value("INTERNAL"))
                .andExpect(jsonPath("$.roles.length()").value(1))
                .andExpect(jsonPath("$.roles[0]").value("SUPPORT"))
                .andExpect(jsonPath("$.capabilities.length()").value(1))
                .andExpect(jsonPath("$.capabilities[0]").value("SUPPORT_WORKBENCH_ACCESS"));
    }

    @Test
    void authenticationLifecycleWritesStructuredSecurityLogsWithoutCredentialsOrPayload(
            CapturedOutput output) throws Exception {
        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession session = (MockHttpSession) csrf.getRequest().getSession(false);

        mvc.perform(
                        post("/api/auth/login")
                                .session(session)
                                .header("X-CSRF-TOKEN", token(csrf))
                                .param("username", "customer-demo")
                                .param("password", "do-not-log-me-78"))
                .andExpect(status().isUnauthorized());

        MvcResult refreshedCsrf =
                mvc.perform(get("/api/auth/csrf").session(session))
                        .andExpect(status().isOk())
                        .andReturn();
        MvcResult login =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(session)
                                        .header("X-CSRF-TOKEN", token(refreshedCsrf))
                                        .param("username", "customer-demo")
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();
        MockHttpSession authenticated = (MockHttpSession) login.getRequest().getSession(false);
        MvcResult logoutCsrf =
                mvc.perform(get("/api/auth/csrf").session(authenticated))
                        .andExpect(status().isOk())
                        .andReturn();
        mvc.perform(
                        post("/api/auth/logout")
                                .session(authenticated)
                                .header("X-CSRF-TOKEN", token(logoutCsrf)))
                .andExpect(status().isNoContent());

        assertThat(output)
                .contains("security_event=human_login outcome=failure")
                .contains("security_event=human_login outcome=success subject_id=customer-demo")
                .contains("security_event=human_logout outcome=success subject_id=customer-demo")
                .doesNotContain("do-not-log-me-78")
                .doesNotContain("local-demo-password")
                .doesNotContain(token(logoutCsrf));
    }

    private void assertProjection(
            String username, String subjectType, List<String> roles, List<String> capabilities)
            throws Exception {
        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession session = (MockHttpSession) csrf.getRequest().getSession(false);
        MvcResult login =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(session)
                                        .header("X-CSRF-TOKEN", token(csrf))
                                        .param("username", username)
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();
        MockHttpSession authenticated = (MockHttpSession) login.getRequest().getSession(false);
        ResultActions current =
                mvc.perform(get("/api/auth/session").session(authenticated))
                        .andExpect(status().isOk())
                        .andExpect(jsonPath("$.id").value(username))
                        .andExpect(jsonPath("$.subjectType").value(subjectType))
                        .andExpect(jsonPath("$.roles.length()").value(roles.size()))
                        .andExpect(jsonPath("$.capabilities.length()").value(capabilities.size()));
        for (int index = 0; index < roles.size(); index++) {
            current.andExpect(jsonPath("$.roles[" + index + "]").value(roles.get(index)));
        }
        for (int index = 0; index < capabilities.size(); index++) {
            current.andExpect(
                    jsonPath("$.capabilities[" + index + "]").value(capabilities.get(index)));
        }
    }

    private String token(MvcResult csrf) throws Exception {
        return json.readTree(csrf.getResponse().getContentAsString()).get("token").asText();
    }

    private static void assertNoSensitiveContract(String responseBody) {
        assertThat(responseBody)
                .doesNotContainIgnoringCase("password")
                .doesNotContainIgnoringCase("cookie")
                .doesNotContainIgnoringCase("csrf")
                .doesNotContainIgnoringCase("route")
                .doesNotContainIgnoringCase("resource")
                .doesNotContain("secret-value-79");
    }
}
