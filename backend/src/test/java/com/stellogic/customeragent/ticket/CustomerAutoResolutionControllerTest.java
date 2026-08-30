package com.stellogic.customeragent.ticket;

import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.stellogic.customeragent.investigation.AutoResolutionService;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

class CustomerAutoResolutionControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("16200000-0000-0000-0000-000000000001");
    private static final Instant DUE_AT = Instant.parse("2026-08-30T04:00:00Z");
    private final AutoResolutionService service = mock(AutoResolutionService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new CustomerAutoResolutionController(service))
                    .setControllerAdvice(new CustomerTicketExceptionHandler())
                    .build();

    @Test
    void cancellationUsesAuthenticatedOwnerAndTheExactPresentedCandidate() throws Exception {
        mvc.perform(
                        post("/api/customer/tickets/{ticketId}/auto-resolution/cancel", TICKET_ID)
                                .principal(customer())
                                .header("X-Synthetic-Customer-Id", "customer-other-demo")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"candidateDueAt\":\"2026-08-30T04:00:00Z\"}"))
                .andExpect(status().isNoContent());

        verify(service).cancel("customer-demo", TICKET_ID, DUE_AT);
    }

    @Test
    void missingCandidateIdentityDoesNotReachTheService() throws Exception {
        mvc.perform(
                        post("/api/customer/tickets/{ticketId}/auto-resolution/cancel", TICKET_ID)
                                .principal(customer())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{}"))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(service);
    }

    @Test
    void staleCandidateRemainsAConflictInsteadOfReportingCancellation() throws Exception {
        doThrow(new ResponseStatusException(HttpStatus.CONFLICT))
                .when(service)
                .cancel("customer-demo", TICKET_ID, DUE_AT);

        mvc.perform(
                        post("/api/customer/tickets/{ticketId}/auto-resolution/cancel", TICKET_ID)
                                .principal(customer())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"candidateDueAt\":\"2026-08-30T04:00:00Z\"}"))
                .andExpect(status().isConflict());
    }

    private UsernamePasswordAuthenticationToken customer() {
        return UsernamePasswordAuthenticationToken.authenticated("customer-demo", "n/a", List.of());
    }
}
