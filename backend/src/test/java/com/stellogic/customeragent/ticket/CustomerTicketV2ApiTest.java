package com.stellogic.customeragent.ticket;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CustomerTicketV2ApiTest {
    private static final UUID TICKET_ID = UUID.fromString("15100000-0000-0000-0000-000000000001");
    private final CustomerTicketService service =
            org.mockito.Mockito.mock(CustomerTicketService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new CustomerTicketV2Controller(service))
                    .setControllerAdvice(new CustomerTicketExceptionHandler())
                    .defaultRequest(get("/").session(session("customer-demo")))
                    .build();

    @Test
    void createsTheCurrentLogisticsConversationThroughTheExplicitV2Contract() throws Exception {
        when(service.create(any())).thenReturn(new TicketCreationResult(TICKET_ID, false));

        mvc.perform(
                        post("/api/customer/v2/tickets")
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-151-create")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"public-conversation-v2",
                                          "orderReference":"ORDER-DELAY-001",
                                          "description":"物流已经延迟多日"
                                        }
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.schema").value("public-conversation-v2"))
                .andExpect(jsonPath("$.ticketId").value(TICKET_ID.toString()))
                .andExpect(jsonPath("$.accepted").value(true))
                .andExpect(jsonPath("$.replayed").value(false));
    }

    @Test
    void acceptsAnAdditionalCustomerMessageWithStableIdentityWhileAgentIsProcessing()
            throws Exception {
        when(service.appendMessage(any()))
                .thenReturn(new CustomerMessageResult(TICKET_ID, "ACCEPTED", false));

        mvc.perform(
                        post("/api/customer/v2/tickets/{ticketId}/messages", TICKET_ID)
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "message-158-1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"public-conversation-v2",
                                          "message":"补充一下，今天仍然没有更新物流轨迹"
                                        }
                                        """))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.schema").value("public-conversation-v2"))
                .andExpect(jsonPath("$.ticketId").value(TICKET_ID.toString()))
                .andExpect(jsonPath("$.accepted").value(true))
                .andExpect(jsonPath("$.replayed").value(false))
                .andExpect(jsonPath("$.generationId").doesNotExist());

        verify(service)
                .appendMessage(
                        new AppendCustomerMessage(
                                "customer-demo", TICKET_ID, "message-158-1", "补充一下，今天仍然没有更新物流轨迹"));
    }

    @Test
    void rejectsUnknownFieldsAndIncompatibleRequestVersions() throws Exception {
        mvc.perform(
                        post("/api/customer/v2/tickets")
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-151-unknown")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"public-conversation-v2",
                                          "orderReference":"ORDER-DELAY-001",
                                          "description":"物流延迟",
                                          "checkpoint":"must-not-enter-product-contract"
                                        }
                                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));

        mvc.perform(
                        post("/api/customer/v2/tickets")
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-151-version")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"ticket-conversation-v3",
                                          "orderReference":"ORDER-DELAY-001",
                                          "description":"物流延迟"
                                        }
                                        """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INCOMPATIBLE_SCHEMA"));
    }

    @Test
    void returnsAnIndependentMinimalV2Snapshot() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot());

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}", TICKET_ID)
                                .principal(customer("customer-demo")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.view").value("PUBLIC_CONVERSATION"))
                .andExpect(jsonPath("$.schema").value("public-conversation-v2"))
                .andExpect(jsonPath("$.cursor").value("public-conversation-v2:2"))
                .andExpect(jsonPath("$.ticket.id").value(TICKET_ID.toString()))
                .andExpect(jsonPath("$.ticket.lifecycleState").value("INVESTIGATING"))
                .andExpect(jsonPath("$.ticket.handlingMode").value("AGENT"))
                .andExpect(jsonPath("$.ticket.agentGeneration").value(1))
                .andExpect(jsonPath("$.ticket.createdAt").doesNotExist())
                .andExpect(jsonPath("$.ticket.firstRespondedAt").doesNotExist())
                .andExpect(jsonPath("$.messages.length()").value(2))
                .andExpect(jsonPath("$.internalNotes").doesNotExist())
                .andExpect(jsonPath("$.orderReference").doesNotExist())
                .andExpect(jsonPath("$.threadId").doesNotExist());
    }

    @Test
    void replaysV2SseWithAnIndependentCursorAndEnvelope() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot());
        when(service.events("customer-demo", TICKET_ID, "customer-public-v1:0"))
                .thenReturn(
                        List.of(
                                new CustomerPublicEvent(
                                        "customer-public-v1",
                                        1,
                                        1,
                                        "TICKET_ACCEPTED",
                                        "{\"ticketId\":\"" + TICKET_ID + "\"}")));
        when(service.events("customer-demo", TICKET_ID, "customer-public-v1:1"))
                .thenReturn(
                        List.of(
                                new CustomerPublicEvent(
                                        "customer-public-v1",
                                        2,
                                        1,
                                        "PUBLIC_MESSAGE_APPENDED",
                                        "{\"author\":\"SUPPORT\",\"body\":\"已受理\",\"sentAt\":\"2026-08-28T00:00:00Z\"}")));
        when(service.events("customer-demo", TICKET_ID, "customer-public-v1:2"))
                .thenReturn(List.of());

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}/events", TICKET_ID)
                                .principal(customer("customer-demo"))
                                .header("Last-Event-ID", "public-conversation-v2:0"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted());

        verify(service, timeout(2_000)).events("customer-demo", TICKET_ID, "customer-public-v1:1");
        verify(service, timeout(2_000)).events("customer-demo", TICKET_ID, "customer-public-v1:2");
    }

    @Test
    void rejectsUnknownEventsAndV1OrFutureCursors() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot());
        when(service.events("customer-demo", TICKET_ID, "customer-public-v1:2"))
                .thenReturn(
                        List.of(
                                new CustomerPublicEvent(
                                        "customer-public-v1", 3, 1, "RAW_AGENT_EVENT", "{}")));

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}/events", TICKET_ID)
                                .principal(customer("customer-demo"))
                                .header("Last-Event-ID", "public-conversation-v2:2"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SNAPSHOT_REQUIRED"));

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}/events", TICKET_ID)
                                .principal(customer("customer-demo"))
                                .header("Last-Event-ID", "customer-public-v1:2"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SNAPSHOT_REQUIRED"));
    }

    private CustomerPublicSnapshot snapshot() {
        return new CustomerPublicSnapshot(
                TICKET_ID,
                "INVESTIGATING",
                "AGENT",
                Instant.parse("2026-08-28T00:00:00Z"),
                Instant.parse("2026-08-28T00:00:00Z"),
                "customer-public-v1",
                2,
                1,
                List.of(
                        new PublicMessage(
                                "CUSTOMER", "物流已经延迟多日", Instant.parse("2026-08-28T00:00:00Z")),
                        new PublicMessage("SUPPORT", "已受理", Instant.parse("2026-08-28T00:00:00Z"))),
                null,
                null);
    }

    private UsernamePasswordAuthenticationToken customer(String id) {
        return UsernamePasswordAuthenticationToken.authenticated(id, "n/a", List.of());
    }
}
