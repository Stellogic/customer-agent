package com.stellogic.customeragent.closure;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.stellogic.customeragent.ticket.CustomerTicketExceptionHandler;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CustomerReplyControllerTest {
    private static final UUID ORIGINAL = UUID.fromString("28000000-0000-0000-0000-000000000001");
    private static final UUID LINKED = UUID.fromString("28000000-0000-0000-0000-000000000002");
    private final ClosureService service = org.mockito.Mockito.mock(ClosureService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new CustomerReplyController(service))
                    .setControllerAdvice(new CustomerTicketExceptionHandler())
                    .build();

    @Test
    void customerUsesStableMessageIdentityToReopenTheOriginalTicket() throws Exception {
        when(service.reply(any())).thenReturn(new CustomerReplyResult(ORIGINAL, "REOPENED", false));

        mvc.perform(
                        post("/api/customer/tickets/{ticketId}/replies", ORIGINAL)
                                .principal(customer())
                                .header("Idempotency-Key", "reply-28-same")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                {"orderReference":"ORDER-DELAY-UNDER-24","issueKind":"LOGISTICS_DELAY","message":"问题仍未解决"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ticketId").value(ORIGINAL.toString()))
                .andExpect(jsonPath("$.outcome").value("REOPENED"))
                .andExpect(jsonPath("$.replayed").value(false));

        verify(service).reply(argThat(command -> command.customerId().equals("customer-demo")));
    }

    @Test
    void differentIssueKindOnTheSameOrderCreatesAnAcceptedLinkedTicket() throws Exception {
        when(service.reply(any()))
                .thenReturn(new CustomerReplyResult(LINKED, "LINKED_TICKET_CREATED", false));

        mvc.perform(
                        post("/api/customer/tickets/{ticketId}/replies", ORIGINAL)
                                .principal(customer())
                                .header("Idempotency-Key", "reply-28-different")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                {"orderReference":"ORDER-DELAY-UNDER-24","issueKind":"OTHER","message":"同一订单的另一个问题"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.ticketId").value(LINKED.toString()))
                .andExpect(jsonPath("$.outcome").value("LINKED_TICKET_CREATED"));
    }

    private UsernamePasswordAuthenticationToken customer() {
        return UsernamePasswordAuthenticationToken.authenticated("customer-demo", "n/a", List.of());
    }
}
