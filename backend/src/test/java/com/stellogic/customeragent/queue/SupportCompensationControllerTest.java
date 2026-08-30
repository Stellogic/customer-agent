package com.stellogic.customeragent.queue;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static com.stellogic.customeragent.identity.HumanTestPrincipals.support;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class SupportCompensationControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("16400000-0000-0000-0000-000000000001");
    private static final UUID REVISION_ID = UUID.fromString("16400000-0000-0000-0000-000000000101");
    private final SupportCompensationService service =
            org.mockito.Mockito.mock(SupportCompensationService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new SupportCompensationController(service))
                    .setControllerAdvice(new SupportWorkbenchExceptionHandler())
                    .defaultRequest(get("/").session(session("support-demo")))
                    .build();

    @Test
    void assignedSupportReadsSpringComputedStandardPlansWithoutClientAmounts() throws Exception {
        when(service.listOptions("support-demo", TICKET_ID))
                .thenReturn(
                        new SupportCompensationOptions(
                                "support-workbench-v2",
                                "delay-policy-v1",
                                List.of(
                                        new SupportCompensationPlan(
                                                "COUPON",
                                                "COUPON",
                                                new BigDecimal("10.00"),
                                                new BigDecimal("10.00"),
                                                "CNY",
                                                List.of("LOGISTICS_DELAY")))));

        mvc.perform(
                        get(
                                        "/api/support/workbench/tickets/{ticketId}/compensation-options",
                                        TICKET_ID)
                                .principal(support()))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.schema").value("support-workbench-v2"))
                .andExpect(jsonPath("$.policyVersion").value("delay-policy-v1"))
                .andExpect(jsonPath("$.plans[0].planCode").value("COUPON"))
                .andExpect(jsonPath("$.plans[0].compensationMethod").value("COUPON"))
                .andExpect(jsonPath("$.plans[0].amount").value(10.00))
                .andExpect(jsonPath("$.plans[0].capAmount").value(10.00))
                .andExpect(jsonPath("$.plans[0].reasonCodes[0]").value("LOGISTICS_DELAY"));
    }

    @Test
    void unassignedSupportCannotReadCompensationOptions() throws Exception {
        when(service.listOptions("support-demo", TICKET_ID))
                .thenThrow(new SupportTicketNotFoundException());

        mvc.perform(
                        get(
                                        "/api/support/workbench/tickets/{ticketId}/compensation-options",
                                        TICKET_ID)
                                .principal(support()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("SUPPORT_TICKET_NOT_FOUND"));
    }

    @Test
    void submittingASelectedPlanCreatesAnImmutableProposalRevision() throws Exception {
        when(service.submitProposal(
                        "support-demo", TICKET_ID, "COUPON", "LOGISTICS_DELAY", "issue-164-1"))
                .thenReturn(
                        new SupportCompensationProposalResult(
                                "support-workbench-v2",
                                TICKET_ID,
                                "issue-164-1",
                                REVISION_ID,
                                1,
                                "COUPON",
                                new BigDecimal("10.00"),
                                "CNY",
                                "PENDING_APPROVAL",
                                "ACCEPTED",
                                false));

        mvc.perform(
                        post(
                                        "/api/support/workbench/tickets/{ticketId}/compensation-proposals",
                                        TICKET_ID)
                                .principal(support())
                                .header("Idempotency-Key", "issue-164-1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"support-workbench-v2",
                                          "planCode":"COUPON",
                                          "reasonCode":"LOGISTICS_DELAY"
                                        }
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.proposalRevisionId").value(REVISION_ID.toString()))
                .andExpect(jsonPath("$.status").value("PENDING_APPROVAL"))
                .andExpect(jsonPath("$.replayed").value(false));
        verify(service)
                .submitProposal(
                        "support-demo", TICKET_ID, "COUPON", "LOGISTICS_DELAY", "issue-164-1");
    }

    @Test
    void clientAmountOrMethodOverridesAreRejectedBeforeSpringComputesThePlan() throws Exception {
        mvc.perform(
                        post(
                                        "/api/support/workbench/tickets/{ticketId}/compensation-proposals",
                                        TICKET_ID)
                                .principal(support())
                                .header("Idempotency-Key", "issue-164-override")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"support-workbench-v2",
                                          "planCode":"COUPON",
                                          "reasonCode":"LOGISTICS_DELAY",
                                          "amount":"999.00"
                                        }
                                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("AMOUNT_OVERRIDE_FORBIDDEN"));
    }

    @Test
    void exceptionalRequestsUseASeparateInterface() throws Exception {
        UUID exceptionalId = UUID.fromString("16400000-0000-0000-0000-000000000201");
        when(service.submitException(
                        "support-demo",
                        TICKET_ID,
                        "STANDARD_PLAN_INSUFFICIENT",
                        "标准优惠券无法覆盖客户损失",
                        "issue-164-ex"))
                .thenReturn(
                        new SupportExceptionalCompensationResult(
                                "support-workbench-v2",
                                TICKET_ID,
                                "issue-164-ex",
                                exceptionalId,
                                "STANDARD_PLAN_INSUFFICIENT",
                                "SUBMITTED",
                                "ACCEPTED",
                                false));

        mvc.perform(
                        post(
                                        "/api/support/workbench/tickets/{ticketId}/exceptional-compensation-requests",
                                        TICKET_ID)
                                .principal(support())
                                .header("Idempotency-Key", "issue-164-ex")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"support-workbench-v2",
                                          "reasonCode":"STANDARD_PLAN_INSUFFICIENT",
                                          "justification":"标准优惠券无法覆盖客户损失"
                                        }
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.exceptionalRequestId").value(exceptionalId.toString()))
                .andExpect(jsonPath("$.status").value("SUBMITTED"));
        verify(service)
                .submitException(
                        "support-demo",
                        TICKET_ID,
                        "STANDARD_PLAN_INSUFFICIENT",
                        "标准优惠券无法覆盖客户损失",
                        "issue-164-ex");
        org.mockito.Mockito.verify(service, org.mockito.Mockito.never())
                .submitProposal(
                        org.mockito.ArgumentMatchers.any(),
                        org.mockito.ArgumentMatchers.any(),
                        org.mockito.ArgumentMatchers.any(),
                        org.mockito.ArgumentMatchers.any(),
                        org.mockito.ArgumentMatchers.any());
    }

    @Test
    void unknownSubmitResultsCanBeQueriedByStableRequestIdentity() throws Exception {
        when(service.queryProposal("support-demo", TICKET_ID, "issue-164-1"))
                .thenReturn(
                        new SupportCompensationProposalResult(
                                "support-workbench-v2",
                                TICKET_ID,
                                "issue-164-1",
                                REVISION_ID,
                                1,
                                "COUPON",
                                new BigDecimal("10.00"),
                                "CNY",
                                "PENDING_APPROVAL",
                                "ACCEPTED",
                                true));

        mvc.perform(
                        get(
                                        "/api/support/workbench/tickets/{ticketId}/compensation-proposals/{requestId}",
                                        TICKET_ID,
                                        "issue-164-1")
                                .principal(support()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.replayed").value(true))
                .andExpect(jsonPath("$.status").value("PENDING_APPROVAL"));
    }
}
