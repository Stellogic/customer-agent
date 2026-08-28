package com.stellogic.customeragent.ticket;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static com.stellogic.customeragent.identity.HumanTestPrincipals.support;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class IntakeAssistanceControllerTest {
    private static final UUID REQUEST_ID = UUID.fromString("15600000-0000-0000-0000-000000000001");
    private static final UUID INTAKE_ID = UUID.fromString("15600000-0000-0000-0000-000000000002");
    private final IntakeAssistanceService service =
            org.mockito.Mockito.mock(IntakeAssistanceService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new IntakeAssistanceController(service))
                    .setControllerAdvice(new IntakeAssistanceExceptionHandler())
                    .defaultRequest(get("/").session(session("support-demo")))
                    .build();

    @Test
    void queueSnapshotUsesASeparateViewAndOnlyAClippedSummary() throws Exception {
        when(service.snapshot("support-demo"))
                .thenReturn(
                        new IntakeAssistanceSnapshot(
                                "intake-assistance-v1",
                                7,
                                List.of(
                                        new IntakeAssistanceQueueItem(
                                                REQUEST_ID,
                                                "QUEUED",
                                                "AGENT_UNAVAILABLE",
                                                Instant.parse("2026-08-28T04:00:00Z"),
                                                null,
                                                false))));

        mvc.perform(get("/api/support/intake-assistance/snapshot").principal(support()))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.view").value("INTAKE_ASSISTANCE"))
                .andExpect(jsonPath("$.schema").value("intake-assistance-v1"))
                .andExpect(jsonPath("$.cursor").value("intake-assistance-v1:7"))
                .andExpect(jsonPath("$.requests[0].requestId").value(REQUEST_ID.toString()))
                .andExpect(jsonPath("$.requests[0].reasonCode").value("AGENT_UNAVAILABLE"))
                .andExpect(jsonPath("$.requests[0].customerId").doesNotExist())
                .andExpect(jsonPath("$.requests[0].intakeId").doesNotExist())
                .andExpect(jsonPath("$.requests[0].originalMessage").doesNotExist())
                .andExpect(jsonPath("$.requests[0].orderReference").doesNotExist());
    }

    @Test
    void currentClaimUnlocksOnlyTheInformationNeededToFinishIntake() throws Exception {
        when(service.details("support-demo", REQUEST_ID))
                .thenReturn(
                        new IntakeAssistanceDetails(
                                REQUEST_ID,
                                INTAKE_ID,
                                "CLAIMED",
                                "AGENT_UNAVAILABLE",
                                "订单 ORDER-DELAY-001 一直没有更新",
                                List.of(
                                        new IntakeAssistanceOrderCandidate(
                                                "ORDER-DELAY-001", "配送中的合成订单")),
                                "ORDER-DELAY-001",
                                List.of(new ProposedIntakeIssue("LOGISTICS_DELAY", "物流一直没有更新")),
                                3,
                                Instant.parse("2026-08-28T04:15:00Z")));

        mvc.perform(
                        get("/api/support/intake-assistance/requests/{requestId}", REQUEST_ID)
                                .principal(support()))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.intakeId").value(INTAKE_ID.toString()))
                .andExpect(jsonPath("$.originalMessage").value("订单 ORDER-DELAY-001 一直没有更新"))
                .andExpect(jsonPath("$.orderCandidates[0].summary").value("配送中的合成订单"))
                .andExpect(jsonPath("$.issues[0].kind").value("LOGISTICS_DELAY"))
                .andExpect(jsonPath("$.customerId").doesNotExist())
                .andExpect(jsonPath("$.paidAmount").doesNotExist())
                .andExpect(jsonPath("$.investigationFacts").doesNotExist())
                .andExpect(jsonPath("$.compensation").doesNotExist())
                .andExpect(jsonPath("$.publicConversation").doesNotExist());
    }

    @Test
    void supportProposalCannotConfirmOrCreateTickets() throws Exception {
        when(service.propose(
                        org.mockito.ArgumentMatchers.any(IntakeAssistanceProposalCommand.class)))
                .thenReturn(
                        new IntakeAssistanceMutation(
                                REQUEST_ID,
                                "WAITING_FOR_CUSTOMER",
                                4,
                                Instant.parse("2026-08-28T04:15:00Z"),
                                false));

        mvc.perform(
                        post(
                                        "/api/support/intake-assistance/requests/{requestId}/proposal",
                                        REQUEST_ID)
                                .principal(support())
                                .header("Idempotency-Key", "issue-156-proposal")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"intake-assistance-v1",
                                          "expectedIntakeVersion":3,
                                          "orderReference":"ORDER-DELAY-001",
                                          "issues":[{"kind":"LOGISTICS_DELAY","summary":"物流一直没有更新"}]
                                        }
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("WAITING_FOR_CUSTOMER"))
                .andExpect(jsonPath("$.intakeVersion").value(4))
                .andExpect(jsonPath("$.ticketId").doesNotExist())
                .andExpect(jsonPath("$.confirmed").doesNotExist());
    }
}
