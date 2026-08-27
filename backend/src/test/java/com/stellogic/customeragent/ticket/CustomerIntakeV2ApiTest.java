package com.stellogic.customeragent.ticket;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CustomerIntakeV2ApiTest {
    private static final UUID INTAKE_ID = UUID.fromString("15200000-0000-0000-0000-000000000001");
    private static final UUID TICKET_ID = UUID.fromString("15200000-0000-0000-0000-000000000002");
    private final CustomerIntakeService service =
            org.mockito.Mockito.mock(CustomerIntakeService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new CustomerIntakeV2Controller(service))
                    .setControllerAdvice(new CustomerTicketExceptionHandler())
                    .defaultRequest(post("/").session(session("customer-demo")))
                    .build();

    @Test
    void startsWithNaturalLanguageAndReturnsOnlyAConfirmableCandidate() throws Exception {
        when(service.start(any()))
                .thenReturn(
                        new CustomerIntakeSnapshot(
                                INTAKE_ID,
                                "READY_TO_CONFIRM",
                                "ORDER-DELAY-001",
                                "配送中的合成订单",
                                "LOGISTICS_DELAY",
                                "物流已经延迟多日",
                                "我理解为 ORDER-DELAY-001 的物流延迟问题，请确认是否正确。",
                                null,
                                false));

        mvc.perform(
                        post("/api/customer/v2/intakes")
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-152-start")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"customer-intake-v1",
                                          "message":"我的包裹好几天没动了，帮我看看"
                                        }
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.schema").value("customer-intake-v1"))
                .andExpect(jsonPath("$.intakeId").value(INTAKE_ID.toString()))
                .andExpect(jsonPath("$.status").value("READY_TO_CONFIRM"))
                .andExpect(jsonPath("$.candidateOrder.reference").value("ORDER-DELAY-001"))
                .andExpect(jsonPath("$.candidateOrder.summary").value("配送中的合成订单"))
                .andExpect(jsonPath("$.issue.kind").value("LOGISTICS_DELAY"))
                .andExpect(jsonPath("$.ticketId").doesNotExist())
                .andExpect(jsonPath("$.confirmed").value(false));
    }

    @Test
    void naturalLanguageAndQuickConfirmationUseTheSameMessageCommand() throws Exception {
        when(service.reply(any()))
                .thenReturn(
                        new CustomerIntakeSnapshot(
                                INTAKE_ID,
                                "CONFIRMED",
                                "ORDER-DELAY-001",
                                "配送中的合成订单",
                                "LOGISTICS_DELAY",
                                "物流已经延迟多日",
                                "已确认，客服工单正在独立处理。",
                                TICKET_ID,
                                false));

        mvc.perform(
                        post("/api/customer/v2/intakes/{intakeId}/messages", INTAKE_ID)
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-152-confirm")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"customer-intake-v1","message":"可以，就按这个处理"}
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("CONFIRMED"))
                .andExpect(jsonPath("$.ticketId").value(TICKET_ID.toString()))
                .andExpect(jsonPath("$.confirmed").value(true));
    }

    private static UsernamePasswordAuthenticationToken customer(String customerId) {
        return new UsernamePasswordAuthenticationToken(customerId, "n/a");
    }
}
