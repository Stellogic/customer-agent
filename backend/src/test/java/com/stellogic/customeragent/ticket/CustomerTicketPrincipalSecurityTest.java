package com.stellogic.customeragent.ticket;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.atLeastOnce;
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
import com.stellogic.customeragent.investigation.AutoResolutionService;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.ObjectMapper;

@WebMvcTest(
        controllers = {
            CustomerTicketV2Controller.class,
            CustomerAutoResolutionController.class,
            CustomerIntakeV2Controller.class,
            AuthSessionController.class,
            DemoAccountController.class
        })
@Import({
    HumanSecurityConfiguration.class,
    LocalDemoHumanAccountsConfiguration.class,
    CustomerTicketExceptionHandler.class,
    CustomerTicketPrincipalSecurityTest.TestServices.class
})
@ActiveProfiles("local-demo")
class CustomerTicketPrincipalSecurityTest {
    private static final UUID TICKET_ID = UUID.fromString("74000000-0000-0000-0000-000000000001");

    @Autowired private MockMvc mvc;
    @Autowired private ObjectMapper json;
    @Autowired private CustomerTicketService service;
    @Autowired private AutoResolutionService autoResolutionService;

    @Test
    void autoResolutionCancellationRequiresCustomerSessionAndCurrentCsrfToken() throws Exception {
        String endpoint = "/api/customer/v2/tickets/{ticketId}/auto-resolution/cancel";
        String body = "{\"candidateDueAt\":\"2026-08-30T04:00:00Z\",\"candidateGeneration\":1}";
        MockHttpSession customer = login("customer-demo");

        mvc.perform(
                        post(endpoint, TICKET_ID)
                                .session(customer)
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body))
                .andExpect(status().isForbidden());

        MvcResult csrf =
                mvc.perform(get("/api/auth/csrf").session(customer))
                        .andExpect(status().isOk())
                        .andReturn();
        mvc.perform(
                        post(endpoint, TICKET_ID)
                                .session(customer)
                                .header("X-CSRF-TOKEN", token(csrf))
                                .header("X-Synthetic-Customer-Id", "customer-other-demo")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body))
                .andExpect(status().isNoContent());

        verify(autoResolutionService)
                .cancel("customer-demo", TICKET_ID, Instant.parse("2026-08-30T04:00:00Z"), 1);

        MockHttpSession support = login("support-demo");
        MvcResult supportCsrf =
                mvc.perform(get("/api/auth/csrf").session(support))
                        .andExpect(status().isOk())
                        .andReturn();
        mvc.perform(
                        post(endpoint, TICKET_ID)
                                .session(support)
                                .header("X-CSRF-TOKEN", token(supportCsrf))
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body))
                .andExpect(status().isForbidden());
    }

    @Test
    void forgedCustomerHeaderCannotReplaceTheAuthenticatedCustomerPrincipal() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot());
        MockHttpSession customer = login("customer-demo");

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}", TICKET_ID)
                                .session(customer)
                                .header("X-Synthetic-Customer-Id", "customer-other-demo"))
                .andExpect(status().isOk());

        verify(service, atLeastOnce()).snapshot("customer-demo", TICKET_ID);
    }

    @Test
    void publicConversationUsesTheAuthenticatedCustomerAndCsrfBoundary() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot());
        MockHttpSession customer = login("customer-demo");

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}", TICKET_ID)
                                .session(customer)
                                .header("X-Synthetic-Customer-Id", "customer-other-demo"))
                .andExpect(status().isOk());
        verify(service, atLeastOnce()).snapshot("customer-demo", TICKET_ID);
    }

    @Test
    void naturalLanguageIntakeUsesTheAuthenticatedCustomerAndCsrfBoundary() throws Exception {
        MockHttpSession customer = login("customer-demo");
        String body = "{\"schema\":\"customer-intake-v4\",\"message\":\"我的包裹好几天没动了\"}";

        mvc.perform(
                        post("/api/customer/v2/intakes")
                                .session(customer)
                                .header("Idempotency-Key", "issue-152-intake")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body))
                .andExpect(status().isForbidden());
    }

    @Test
    void anonymousAndInternalSessionsCannotUseForgedCustomerHeaders() throws Exception {
        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}", TICKET_ID)
                                .header("X-Synthetic-Customer-Id", "customer-demo"))
                .andExpect(status().isUnauthorized());

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}", TICKET_ID)
                                .session(login("support-demo"))
                                .header("X-Synthetic-Customer-Id", "customer-demo"))
                .andExpect(status().isForbidden());
    }

    @Test
    void customerWritesRequireTheCurrentSessionCsrfToken() throws Exception {
        when(service.appendMessage(any()))
                .thenReturn(new CustomerMessageResult(TICKET_ID, "ACCEPTED", false));
        MockHttpSession customer = login("customer-demo");
        String body = "{\"schema\":\"public-conversation-v2\",\"message\":\"补充物流信息\"}";

        mvc.perform(
                        post("/api/customer/v2/tickets/{ticketId}/messages", TICKET_ID)
                                .session(customer)
                                .header("Idempotency-Key", "issue-74-create")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body))
                .andExpect(status().isForbidden());

        MvcResult csrf =
                mvc.perform(get("/api/auth/csrf").session(customer))
                        .andExpect(status().isOk())
                        .andReturn();
        mvc.perform(
                        post("/api/customer/v2/tickets/{ticketId}/messages", TICKET_ID)
                                .session(customer)
                                .header("X-CSRF-TOKEN", token(csrf))
                                .header("X-Synthetic-Customer-Id", "customer-other-demo")
                                .header("Idempotency-Key", "issue-74-create")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body))
                .andExpect(status().isAccepted());
    }

    private MockHttpSession login(String username) throws Exception {
        MvcResult csrf = mvc.perform(get("/api/auth/csrf")).andExpect(status().isOk()).andReturn();
        MockHttpSession anonymous = (MockHttpSession) csrf.getRequest().getSession(false);
        MvcResult login =
                mvc.perform(
                                post("/api/auth/login")
                                        .session(anonymous)
                                        .header("X-CSRF-TOKEN", token(csrf))
                                        .param("username", username)
                                        .param("password", "local-demo-password"))
                        .andExpect(status().isNoContent())
                        .andReturn();
        return (MockHttpSession) login.getRequest().getSession(false);
    }

    private String token(MvcResult csrf) throws Exception {
        return json.readTree(csrf.getResponse().getContentAsString()).get("token").asText();
    }

    private CustomerPublicSnapshot snapshot() {
        return new CustomerPublicSnapshot(
                TICKET_ID,
                "INVESTIGATING",
                "AGENT",
                Instant.parse("2026-08-22T00:00:00Z"),
                Instant.parse("2026-08-22T00:00:01Z"),
                "public-conversation-v2",
                1,
                1,
                List.of(),
                null,
                null,
                null);
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestServices {
        @Bean
        AutoResolutionService autoResolutionService() {
            return mock(AutoResolutionService.class);
        }

        @Bean
        CustomerTicketService customerTicketService() {
            return mock(CustomerTicketService.class);
        }

        @Bean
        CustomerIntakeService customerIntakeService() {
            return mock(CustomerIntakeService.class);
        }
    }
}
