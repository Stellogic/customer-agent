package com.stellogic.customeragent.identity;

import static com.stellogic.customeragent.identity.HumanSessionTestClient.login;
import static com.stellogic.customeragent.identity.HumanSessionTestClient.token;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import tools.jackson.databind.ObjectMapper;

@WebMvcTest({AuthSessionController.class, DemoAccountController.class})
@Import({HumanSecurityConfiguration.class, LocalDemoHumanAccountsConfiguration.class})
@ActiveProfiles("local-demo")
class HumanApiNegativeMatrixTest {
    private static final String ID = "79000000-0000-0000-0000-000000000001";
    private static final List<ApiRequest> CUSTOMER_APIS =
            List.of(
                    getApi("/api/customer/tickets"),
                    getApi("/api/customer/tickets/" + ID),
                    getApi("/api/customer/tickets/" + ID + "/events"),
                    postApi("/api/customer/v2/intakes"),
                    postApi("/api/customer/v2/intakes/" + ID + "/messages"),
                    postApi("/api/customer/tickets"),
                    postApi("/api/customer/tickets/" + ID + "/clarifications/" + ID + "/replies"),
                    getApi("/api/customer/tickets/" + ID + "/clarification-resumes/" + ID),
                    postApi("/api/customer/tickets/" + ID + "/human-handoff"),
                    getApi("/api/customer/tickets/" + ID + "/human-handoff-requests/request-79"),
                    postApi("/api/customer/tickets/" + ID + "/replies"));
    private static final List<ApiRequest> SUPPORT_APIS =
            List.of(
                    getApi("/api/support/queue"),
                    getApi("/api/support/sla/notifications"),
                    getApi("/api/support/escalations"),
                    getApi("/api/support/workbench/snapshot"),
                    getApi("/api/support/workbench/tickets/" + ID),
                    postApi("/api/support/workbench/tickets/" + ID + "/claims"),
                    getApi("/api/support/workbench/events"));
    private static final List<ApiRequest> APPROVAL_APIS =
            List.of(
                    getApi("/api/approver/compensation-proposals"),
                    postApi("/api/approver/compensation-proposals/" + ID + "/claims"),
                    getApi("/api/approver/compensation-proposals/" + ID + "/approval-view"),
                    getApi("/api/approver/compensation-proposals/" + ID + "/approval-view/events"),
                    postApi("/api/approver/compensation-proposals/" + ID + "/release"),
                    postApi("/api/approver/compensation-proposals/" + ID + "/reject"),
                    postApi("/api/approver/compensation-proposals/" + ID + "/approve"));

    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper json;

    @Test
    void everyHumanBusinessApiRejectsAnonymousRequestsEvenWithDeprecatedForgedHeaders()
            throws Exception {
        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession anonymous = (MockHttpSession) csrf.getRequest().getSession(false);
        assertStatus(allApis(), anonymous, token(json, csrf), 401);
    }

    @Test
    void everyHumanBusinessApiRejectsTheWrongCoarseRoleDespiteDeprecatedForgedHeaders()
            throws Exception {
        assertWrongRole(CUSTOMER_APIS, "support-demo");
        assertWrongRole(SUPPORT_APIS, "customer-demo");
        assertWrongRole(APPROVAL_APIS, "support-demo");
    }

    private void assertWrongRole(List<ApiRequest> requests, String username) throws Exception {
        MockHttpSession session = login(mvc, json, username);
        MvcResult csrf =
                mvc.perform(get("/api/auth/csrf").session(session))
                        .andExpect(status().isOk())
                        .andReturn();
        assertStatus(requests, session, token(json, csrf), 403);
    }

    private void assertStatus(
            List<ApiRequest> requests, MockHttpSession session, String csrfToken, int expected)
            throws Exception {
        for (ApiRequest request : requests) {
            mvc.perform(
                            request.builder(csrfToken)
                                    .session(session)
                                    .header("X-Synthetic-Customer-Id", "customer-demo")
                                    .header("X-Synthetic-Support-Id", "support-demo")
                                    .header("X-Synthetic-Approver-Id", "approver-demo"))
                    .andExpect(status().is(expected));
        }
    }

    private static List<ApiRequest> allApis() {
        return java.util.stream.Stream.of(CUSTOMER_APIS, SUPPORT_APIS, APPROVAL_APIS)
                .flatMap(List::stream)
                .toList();
    }

    private static ApiRequest getApi(String path) {
        return new ApiRequest("GET", path);
    }

    private static ApiRequest postApi(String path) {
        return new ApiRequest("POST", path);
    }

    private record ApiRequest(String method, String path) {
        MockHttpServletRequestBuilder builder(String csrfToken) {
            if ("POST".equals(method)) {
                return post(path)
                        .header("X-CSRF-TOKEN", csrfToken)
                        .header("Idempotency-Key", "issue-79-matrix")
                        .contentType("application/json")
                        .content("{}");
            }
            return get(path);
        }
    }
}
