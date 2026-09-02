package com.stellogic.customeragent.ticket;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static org.assertj.core.api.Assertions.assertThat;
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
                .andExpect(
                        jsonPath("$.pendingCompensation").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.internalNotes").doesNotExist())
                .andExpect(jsonPath("$.orderReference").doesNotExist())
                .andExpect(jsonPath("$.threadId").doesNotExist());
    }

    @Test
    void exposesOnlyPublicAutoResolutionStateAndAcceptsItsEvent() throws Exception {
        Instant dueAt = Instant.parse("2026-08-28T01:00:00Z");
        when(service.snapshot("customer-demo", TICKET_ID))
                .thenReturn(snapshot(new CurrentAutoResolution("PENDING", dueAt)));

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}", TICKET_ID)
                                .principal(customer("customer-demo")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.autoResolution.status").value("PENDING"))
                .andExpect(jsonPath("$.autoResolution.dueAt").value("2026-08-28T01:00:00Z"))
                .andExpect(jsonPath("$.autoResolution.generationId").doesNotExist())
                .andExpect(jsonPath("$.autoResolution.evidence").doesNotExist());

        var event =
                CustomerTicketV2Controller.V2Event.from(
                        new CustomerPublicEvent(
                                "public-conversation-v2",
                                3,
                                1,
                                "AUTO_RESOLUTION_CHANGED",
                                "{\"autoResolution\":{\"status\":\"CANCELLED\",\"dueAt\":null}}"));
        assertThat(event.cursor()).isEqualTo("public-conversation-v2:3");
        assertThat(event.publicData())
                .contains("\"schema\":\"public-conversation-v2\"", "\"status\":\"CANCELLED\"");
    }

    @Test
    void pendingCompensationProjectionOnlyExposesSafeTypeAmountAndReviewStatus() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID))
                .thenReturn(
                        new CustomerPublicSnapshot(
                                TICKET_ID,
                                "INVESTIGATING",
                                "HUMAN",
                                Instant.parse("2026-08-28T00:00:00Z"),
                                Instant.parse("2026-08-28T00:00:00Z"),
                                "public-conversation-v2",
                                3,
                                1,
                                List.of(),
                                null,
                                null,
                                null,
                                new PendingCompensationProjection(
                                        "COUPON", "10.00", "CNY", "PENDING_REVIEW")));

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}", TICKET_ID)
                                .principal(customer("customer-demo")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.pendingCompensation.compensationMethod").value("COUPON"))
                .andExpect(jsonPath("$.pendingCompensation.amount").value("10.00"))
                .andExpect(jsonPath("$.pendingCompensation.currency").value("CNY"))
                .andExpect(jsonPath("$.pendingCompensation.status").value("PENDING_REVIEW"))
                .andExpect(jsonPath("$.pendingCompensation.approved").doesNotExist())
                .andExpect(jsonPath("$.pendingCompensation.executed").doesNotExist());
    }

    @Test
    void replaysV2SseWithAnIndependentCursorAndEnvelope() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot());
        when(service.events("customer-demo", TICKET_ID, "public-conversation-v2:0"))
                .thenReturn(
                        List.of(
                                new CustomerPublicEvent(
                                        "public-conversation-v2",
                                        1,
                                        1,
                                        "TICKET_ACCEPTED",
                                        "{\"ticketId\":\"" + TICKET_ID + "\"}")));
        when(service.events("customer-demo", TICKET_ID, "public-conversation-v2:1"))
                .thenReturn(
                        List.of(
                                new CustomerPublicEvent(
                                        "public-conversation-v2",
                                        2,
                                        1,
                                        "PUBLIC_MESSAGE_APPENDED",
                                        "{\"author\":\"SUPPORT\",\"body\":\"已受理\",\"sentAt\":\"2026-08-28T00:00:00Z\"}")));
        when(service.events("customer-demo", TICKET_ID, "public-conversation-v2:2"))
                .thenReturn(List.of());

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}/events", TICKET_ID)
                                .principal(customer("customer-demo"))
                                .header("Last-Event-ID", "public-conversation-v2:0"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted());

        verify(service, timeout(2_000))
                .events("customer-demo", TICKET_ID, "public-conversation-v2:1");
        verify(service, timeout(2_000))
                .events("customer-demo", TICKET_ID, "public-conversation-v2:2");
    }

    @Test
    void rejectsUnknownEventsAndV1OrFutureCursors() throws Exception {
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot());
        when(service.events("customer-demo", TICKET_ID, "public-conversation-v2:2"))
                .thenReturn(
                        List.of(
                                new CustomerPublicEvent(
                                        "public-conversation-v2", 3, 1, "RAW_AGENT_EVENT", "{}")));

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}/events", TICKET_ID)
                                .principal(customer("customer-demo"))
                                .header("Last-Event-ID", "customer-public-v1:2"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SNAPSHOT_REQUIRED"));

        mvc.perform(
                        get("/api/customer/v2/tickets/{ticketId}/events", TICKET_ID)
                                .principal(customer("customer-demo"))
                                .header("Last-Event-ID", "public-conversation-v2:2"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SNAPSHOT_REQUIRED"));
    }

    private CustomerPublicSnapshot snapshot() {
        return snapshot(null);
    }

    private CustomerPublicSnapshot snapshot(CurrentAutoResolution autoResolution) {
        return new CustomerPublicSnapshot(
                TICKET_ID,
                "INVESTIGATING",
                "AGENT",
                Instant.parse("2026-08-28T00:00:00Z"),
                Instant.parse("2026-08-28T00:00:00Z"),
                "public-conversation-v2",
                2,
                1,
                List.of(
                        new PublicMessage(
                                "CUSTOMER", "物流已经延迟多日", Instant.parse("2026-08-28T00:00:00Z")),
                        new PublicMessage("SUPPORT", "已受理", Instant.parse("2026-08-28T00:00:00Z"))),
                null,
                null,
                autoResolution);
    }

    private UsernamePasswordAuthenticationToken customer(String id) {
        return UsernamePasswordAuthenticationToken.authenticated(id, "n/a", List.of());
    }
}
