package com.stellogic.customeragent.approval;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class ApprovalControllerTest {
    private static final UUID REVISION_ID = UUID.fromString("20000000-0000-0000-0000-000000000001");
    private static final UUID LEASE_TOKEN = UUID.fromString("20000000-0000-0000-0000-000000000002");
    private static final String CONTENT_DIGEST =
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    private final ApprovalService service = org.mockito.Mockito.mock(ApprovalService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new ApprovalController(service)).build();

    @Test
    void approverQueueExposesOnlyTheMinimalProjection() throws Exception {
        when(service.queue()).thenReturn(List.of(new ApprovalModels.QueueItem(
                REVISION_ID, "SIMULATED_PARTIAL_REFUND", new BigDecimal("26.80"),
                Instant.parse("2026-08-09T14:00:00Z"), Instant.parse("2026-08-10T14:00:00Z"))));

        mvc.perform(get("/api/approver/compensation-proposals")
                        .header("X-Synthetic-Approver-Id", "approver-demo"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].proposalRevisionId").value(REVISION_ID.toString()))
                .andExpect(jsonPath("$[0].compensationMethod").value("SIMULATED_PARTIAL_REFUND"))
                .andExpect(jsonPath("$[0].amount").value(26.80))
                .andExpect(jsonPath("$[0].ticketId").doesNotExist())
                .andExpect(jsonPath("$[0].evidenceReferences").doesNotExist())
                .andExpect(jsonPath("$[0].execution").doesNotExist());
    }

    @Test
    void approverClaimsWithStableIdentityAndReceivesFencingCredentials() throws Exception {
        when(service.claim(any())).thenReturn(new ApprovalModels.LeaseResult(
                REVISION_ID, LEASE_TOKEN, 1, Instant.parse("2026-08-09T14:15:00Z"), false));

        mvc.perform(post("/api/approver/compensation-proposals/{revisionId}/claims", REVISION_ID)
                        .header("X-Synthetic-Approver-Id", "approver-demo")
                        .header("Idempotency-Key", "claim-20")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"requestedLeaseSeconds\":900}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.leaseToken").value(LEASE_TOKEN.toString()))
                .andExpect(jsonPath("$.leaseVersion").value(1))
                .andExpect(jsonPath("$.replayed").value(false));
    }

    @Test
    void currentLeaseHolderLoadsOnlyTheApprovalView() throws Exception {
        when(service.view(any())).thenReturn(new ApprovalModels.ApprovalView(
                "APPROVAL_VIEW", REVISION_ID, 1, "digest", "ORDER-DELAY-001", "LOGISTICS_DELAY",
                80, 288000, "SIMULATED_PARTIAL_REFUND",
                new BigDecimal("26.80"), new BigDecimal("26.80"), "delay-policy-v1", "OVER_72_HOURS",
                List.of("ORDER_PAID", "ORDER_NOT_CANCELLED", "ORDER_NOT_FULLY_REFUNDED",
                        "NO_EXISTING_COMPENSATION", "ALLOWANCE_SUFFICIENT"),
                List.of("order:ORDER-DELAY-001", "logistics:ORDER-DELAY-001"),
                Map.of("delaySeconds", 288000, "paidAmount", "268.00"),
                List.of(new ApprovalModels.ResponsibilityEvent(
                        "COMPENSATION_PROPOSAL_REVISION_CREATED", "spring-system",
                        Instant.parse("2026-08-09T14:00:00Z"), null)), LEASE_TOKEN, 1,
                Instant.parse("2026-08-09T14:15:00Z"), Instant.parse("2026-08-09T14:00:00Z"),
                Instant.parse("2026-08-10T14:00:00Z")));

        mvc.perform(get("/api/approver/compensation-proposals/{revisionId}/approval-view", REVISION_ID)
                        .header("X-Synthetic-Approver-Id", "approver-demo")
                        .header("X-Approval-Lease-Token", LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.view").value("APPROVAL_VIEW"))
                .andExpect(jsonPath("$.contentDigest").value("digest"))
                .andExpect(jsonPath("$.authoritativeAmount").value(26.80))
                .andExpect(jsonPath("$.ticket").doesNotExist())
                .andExpect(jsonPath("$.publicMessages").doesNotExist())
                .andExpect(jsonPath("$.internalNotes").doesNotExist())
                .andExpect(jsonPath("$.execution").doesNotExist());
    }

    @Test
    void leaseHolderCanReleaseWithAStableIdentity() throws Exception {
        when(service.release(any())).thenReturn(new ApprovalModels.ReleaseResult(REVISION_ID, true, false));

        mvc.perform(post("/api/approver/compensation-proposals/{revisionId}/release", REVISION_ID)
                        .header("X-Synthetic-Approver-Id", "approver-demo")
                        .header("X-Approval-Lease-Token", LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", "1")
                        .header("Idempotency-Key", "release-20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.released").value(true));
    }

    @Test
    void currentLeaseHolderRejectsTheBoundRevisionWithAnInternalReason() throws Exception {
        when(service.reject(any())).thenReturn(new ApprovalModels.RejectionResult(
                REVISION_ID, 1, "REJECTED", false));

        mvc.perform(post("/api/approver/compensation-proposals/{revisionId}/reject", REVISION_ID)
                        .header("X-Synthetic-Approver-Id", "approver-demo")
                        .header("X-Approval-Lease-Token", LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", "1")
                        .header("Idempotency-Key", "decision-21")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"proposalRevision":1,"contentDigest":"%s","internalReason":"政策证据需要人工复核"}
                                """.formatted(CONTENT_DIGEST)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.proposalRevisionId").value(REVISION_ID.toString()))
                .andExpect(jsonPath("$.proposalRevision").value(1))
                .andExpect(jsonPath("$.decision").value("REJECTED"))
                .andExpect(jsonPath("$.replayed").value(false))
                .andExpect(jsonPath("$.internalReason").doesNotExist());
    }

    @Test
    void rejectionRequiresANonEmptyInternalReasonBeforeCallingTheService() throws Exception {
        mvc.perform(post("/api/approver/compensation-proposals/{revisionId}/reject", REVISION_ID)
                        .header("X-Synthetic-Approver-Id", "approver-demo")
                        .header("X-Approval-Lease-Token", LEASE_TOKEN)
                        .header("X-Approval-Lease-Version", "1")
                        .header("Idempotency-Key", "decision-21-empty")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"proposalRevision":1,"contentDigest":"%s","internalReason":"   "}
                                """.formatted(CONTENT_DIGEST)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void customerOrSupportIdentityCannotUseApproverEndpoints() throws Exception {
        mvc.perform(get("/api/approver/compensation-proposals")
                        .header("X-Synthetic-Approver-Id", "support-demo"))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/api/approver/compensation-proposals")
                        .header("X-Synthetic-Approver-Id", "customer-demo"))
                .andExpect(status().isUnauthorized());
    }
}
