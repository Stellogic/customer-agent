package com.stellogic.customeragent.approval;

import static com.stellogic.customeragent.identity.HumanSessionTestClient.login;
import static com.stellogic.customeragent.identity.HumanSessionTestClient.token;
import static org.mockito.ArgumentMatchers.argThat;
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
import java.time.Instant;
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
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
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
    private static final UUID MATRIX_REVISION_ID =
            UUID.fromString("76000000-0000-0000-0000-000000000010");
    private static final UUID MATRIX_LEASE_TOKEN =
            UUID.fromString("76000000-0000-0000-0000-000000000011");
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
    void approverSessionDoesNotNeedTheLegacyBusinessIdentityHeader() throws Exception {
        when(service.queue("approver-demo")).thenReturn(List.of());

        mvc.perform(
                        get("/api/approver/compensation-proposals")
                                .session(login(mvc, json, "approver-demo")))
                .andExpect(status().isOk());

        verify(service).queue("approver-demo");

        mvc.perform(
                        get("/api/approver/compensation-proposals")
                                .header("X-Synthetic-Approver-Id", "approver-demo"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void approvalWriteRequiresCurrentCsrfAndUsesThePrincipalDespiteAForgedHeader()
            throws Exception {
        UUID revisionId = UUID.fromString("76000000-0000-0000-0000-000000000001");
        UUID leaseToken = UUID.fromString("76000000-0000-0000-0000-000000000002");
        when(service.claim(org.mockito.ArgumentMatchers.any()))
                .thenReturn(
                        new ApprovalModels.LeaseResult(
                                revisionId,
                                leaseToken,
                                1,
                                Instant.parse("2026-08-22T08:15:00Z"),
                                false));
        MockHttpSession approver = login(mvc, json, "approver-demo");

        mvc.perform(
                        post("/api/approver/compensation-proposals/{revisionId}/claims", revisionId)
                                .session(approver)
                                .header("X-Synthetic-Approver-Id", "approver-other-demo")
                                .header("Idempotency-Key", "issue-76-claim")
                                .contentType("application/json")
                                .content("{\"requestedLeaseSeconds\":900}"))
                .andExpect(status().isForbidden());

        MvcResult csrf =
                mvc.perform(get("/api/auth/csrf").session(approver))
                        .andExpect(status().isOk())
                        .andReturn();
        mvc.perform(
                        post("/api/approver/compensation-proposals/{revisionId}/claims", revisionId)
                                .session(approver)
                                .header("X-CSRF-TOKEN", token(json, csrf))
                                .header("X-Synthetic-Approver-Id", "approver-other-demo")
                                .header("Idempotency-Key", "issue-76-claim")
                                .contentType("application/json")
                                .content("{\"requestedLeaseSeconds\":900}"))
                .andExpect(status().isCreated());

        verify(service).claim(argThat(command -> command.approverId().equals("approver-demo")));
    }

    @Test
    void everyApprovalApiRejectsAnonymousAndWrongRoleSessionsAtTheCoarseBoundary()
            throws Exception {
        MvcResult anonymousCsrf =
                mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession anonymous = (MockHttpSession) anonymousCsrf.getRequest().getSession(false);
        for (MockHttpServletRequestBuilder request :
                approvalApiRequests(anonymous, token(json, anonymousCsrf))) {
            mvc.perform(request.header("X-Synthetic-Approver-Id", "approver-demo"))
                    .andExpect(status().isUnauthorized());
        }

        for (String username : List.of("customer-demo", "support-demo")) {
            MockHttpSession wrongRole = login(mvc, json, username);
            MvcResult currentCsrf =
                    mvc.perform(get("/api/auth/csrf").session(wrongRole))
                            .andExpect(status().isOk())
                            .andReturn();
            for (MockHttpServletRequestBuilder request :
                    approvalApiRequests(wrongRole, token(json, currentCsrf))) {
                mvc.perform(request.header("X-Synthetic-Approver-Id", "approver-demo"))
                        .andExpect(status().isForbidden());
            }
        }
    }

    private static List<MockHttpServletRequestBuilder> approvalApiRequests(
            MockHttpSession session, String csrfToken) {
        String leaseVersion = "1";
        String contentDigest = "0".repeat(64);
        return List.of(
                get("/api/approver/compensation-proposals").session(session),
                post("/api/approver/compensation-proposals/{revisionId}/claims", MATRIX_REVISION_ID)
                        .session(session)
                        .header("X-CSRF-TOKEN", csrfToken)
                        .header("Idempotency-Key", "matrix-claim")
                        .contentType("application/json")
                        .content("{\"requestedLeaseSeconds\":900}"),
                get(
                                "/api/approver/compensation-proposals/{revisionId}/approval-view",
                                MATRIX_REVISION_ID)
                        .session(session)
                        .header("X-Approval-Lease-Token", MATRIX_LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", leaseVersion),
                get(
                                "/api/approver/compensation-proposals/{revisionId}/approval-view/events",
                                MATRIX_REVISION_ID)
                        .session(session)
                        .header("X-Approval-Lease-Token", MATRIX_LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", leaseVersion),
                post(
                                "/api/approver/compensation-proposals/{revisionId}/release",
                                MATRIX_REVISION_ID)
                        .session(session)
                        .header("X-CSRF-TOKEN", csrfToken)
                        .header("X-Approval-Lease-Token", MATRIX_LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", leaseVersion)
                        .header("Idempotency-Key", "matrix-release"),
                post(
                                "/api/approver/compensation-proposals/{revisionId}/approve",
                                MATRIX_REVISION_ID)
                        .session(session)
                        .header("X-CSRF-TOKEN", csrfToken)
                        .header("X-Approval-Lease-Token", MATRIX_LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", leaseVersion)
                        .header("Idempotency-Key", "matrix-approve")
                        .contentType("application/json")
                        .content(
                                "{\"proposalRevision\":1,\"contentDigest\":\""
                                        + contentDigest
                                        + "\"}"),
                post("/api/approver/compensation-proposals/{revisionId}/reject", MATRIX_REVISION_ID)
                        .session(session)
                        .header("X-CSRF-TOKEN", csrfToken)
                        .header("X-Approval-Lease-Token", MATRIX_LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", leaseVersion)
                        .header("Idempotency-Key", "matrix-reject")
                        .contentType("application/json")
                        .content(
                                "{\"proposalRevision\":1,\"contentDigest\":\""
                                        + contentDigest
                                        + "\",\"internalReason\":\"matrix\"}"));
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestServices {
        @Bean
        ApprovalService approvalService() {
            return mock(ApprovalService.class);
        }
    }
}
