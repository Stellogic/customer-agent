package com.stellogic.customeragent.clarification;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CustomerClarificationControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("16000000-0000-0000-0000-000000000001");
    private static final UUID REQUEST_ID = UUID.fromString("16000000-0000-0000-0000-000000000002");
    private static final UUID RESUME_ID = UUID.fromString("16000000-0000-0000-0000-000000000003");
    private final ClarificationService service =
            org.mockito.Mockito.mock(ClarificationService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new CustomerClarificationController(service)).build();

    @Test
    void currentReplyUsesStableMessageAndResumeIdentities() throws Exception {
        when(service.reply(any()))
                .thenReturn(
                        new ClarificationReplyResult(RESUME_ID, AgentResumeStatus.PENDING, false));

        mvc.perform(
                        post(
                                        "/api/customer/tickets/{ticketId}/clarifications/{requestId}/replies",
                                        TICKET_ID,
                                        REQUEST_ID)
                                .principal(customer())
                                .header("X-Synthetic-Customer-Id", "customer-other-demo")
                                .header("Idempotency-Key", "message-16")
                                .header("X-Resume-Request-Id", RESUME_ID)
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"answer\":\"A\"}"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.resumeRequestId").value(RESUME_ID.toString()))
                .andExpect(jsonPath("$.status").value("PENDING"))
                .andExpect(jsonPath("$.replayed").value(false));

        verify(service).reply(argThat(command -> command.customerId().equals("customer-demo")));
    }

    @Test
    void browserCanQueryAnUnknownResumeResponseByStableIdentity() throws Exception {
        when(service.status("customer-demo", TICKET_ID, RESUME_ID))
                .thenReturn(
                        new ClarificationReplyResult(RESUME_ID, AgentResumeStatus.SUBMITTED, true));

        mvc.perform(
                        get(
                                        "/api/customer/tickets/{ticketId}/clarification-resumes/{resumeId}",
                                        TICKET_ID,
                                        RESUME_ID)
                                .principal(customer())
                                .header("X-Synthetic-Customer-Id", "customer-other-demo"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SUBMITTED"));
    }

    private UsernamePasswordAuthenticationToken customer() {
        return UsernamePasswordAuthenticationToken.authenticated("customer-demo", "n/a", List.of());
    }
}
