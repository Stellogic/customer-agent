package com.stellogic.customeragent.ticket;

import static org.mockito.ArgumentMatchers.any;
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
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.ObjectMapper;

@WebMvcTest(
        controllers = {
            CustomerTicketController.class,
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

    @Test
    void forgedCustomerHeaderCannotReplaceTheAuthenticatedCustomerPrincipal() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot());
        MockHttpSession customer = login("customer-demo");

        mvc.perform(
                        get("/api/customer/tickets/{ticketId}", TICKET_ID)
                                .session(customer)
                                .header("X-Synthetic-Customer-Id", "customer-other-demo"))
                .andExpect(status().isOk());

        verify(service).snapshot("customer-demo", TICKET_ID);
    }

    @Test
    void anonymousAndInternalSessionsCannotUseForgedCustomerHeaders() throws Exception {
        mvc.perform(
                        get("/api/customer/tickets/{ticketId}", TICKET_ID)
                                .header("X-Synthetic-Customer-Id", "customer-demo"))
                .andExpect(status().isUnauthorized());

        mvc.perform(
                        get("/api/customer/tickets/{ticketId}", TICKET_ID)
                                .session(login("support-demo"))
                                .header("X-Synthetic-Customer-Id", "customer-demo"))
                .andExpect(status().isForbidden());
    }

    @Test
    void customerWritesRequireTheCurrentSessionCsrfToken() throws Exception {
        when(service.create(any())).thenReturn(new TicketCreationResult(TICKET_ID, false));
        MockHttpSession customer = login("customer-demo");
        String body = "{\"orderReference\":\"ORDER-DELAY-001\",\"description\":\"物流延迟\"}";

        mvc.perform(
                        post("/api/customer/tickets")
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
                        post("/api/customer/tickets")
                                .session(customer)
                                .header("X-CSRF-TOKEN", token(csrf))
                                .header("X-Synthetic-Customer-Id", "customer-other-demo")
                                .header("Idempotency-Key", "issue-74-create")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body))
                .andExpect(status().isCreated());
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
                "customer-public-v1",
                1,
                1,
                List.of(),
                null);
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestServices {
        @Bean
        CustomerTicketService customerTicketService() {
            return mock(CustomerTicketService.class);
        }
    }
}
