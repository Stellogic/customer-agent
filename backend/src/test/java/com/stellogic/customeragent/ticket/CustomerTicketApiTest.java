package com.stellogic.customeragent.ticket;

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
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CustomerTicketApiTest {
    private static final UUID TICKET_ID = UUID.fromString("10000000-0000-0000-0000-000000000013");
    private final CustomerTicketService service = org.mockito.Mockito.mock(CustomerTicketService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new CustomerTicketController(service))
            .setControllerAdvice(new CustomerTicketExceptionHandler())
            .build();

    @Test
    void customerCreatesTicketThroughThePublicProductApi() throws Exception {
        when(service.create(any())).thenReturn(new TicketCreationResult(TICKET_ID, false));

        mvc.perform(post("/api/customer/tickets")
                        .header("X-Synthetic-Customer-Id", "customer-demo")
                        .header("Idempotency-Key", "request-13")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"orderReference":"ORDER-DELAY-001","description":"物流已经延迟多日"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.ticketId").value(TICKET_ID.toString()))
                .andExpect(jsonPath("$.accepted").value(true))
                .andExpect(jsonPath("$.replayed").value(false));
    }

    @Test
    void reusedRequestIdentityWithDifferentParametersIsAnExplicitConflict() throws Exception {
        when(service.create(any())).thenThrow(new RequestIdentityConflictException());

        mvc.perform(post("/api/customer/tickets")
                        .header("X-Synthetic-Customer-Id", "customer-demo")
                        .header("Idempotency-Key", "request-13")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"orderReference":"ORDER-DELAY-002","description":"另一个问题"}
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("REQUEST_ID_CONFLICT"));
    }

    @Test
    void customerSnapshotIsCompleteAndOtherCustomersReceiveNonEnumerableDenial() throws Exception {
        var snapshot = new CustomerPublicSnapshot(
                TICKET_ID,
                "INVESTIGATING",
                "AGENT",
                Instant.parse("2026-08-09T00:00:00Z"),
                Instant.parse("2026-08-09T00:00:00Z"),
                "customer-public-v1",
                2,
                List.of(
                        new PublicMessage("CUSTOMER", "物流已经延迟多日", Instant.parse("2026-08-09T00:00:00Z")),
                        new PublicMessage("SUPPORT", "已受理", Instant.parse("2026-08-09T00:00:00Z"))),
                null);
        when(service.snapshot("customer-demo", TICKET_ID)).thenReturn(snapshot);
        when(service.snapshot("customer-other-demo", TICKET_ID)).thenThrow(new TicketNotFoundException());

        mvc.perform(get("/api/customer/tickets/{ticketId}", TICKET_ID)
                        .header("X-Synthetic-Customer-Id", "customer-demo"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.view").value("CUSTOMER_PUBLIC"))
                .andExpect(jsonPath("$.schema").value("customer-public-v1"))
                .andExpect(jsonPath("$.cursor").value("customer-public-v1:2"))
                .andExpect(jsonPath("$.ticket.lifecycleState").value("INVESTIGATING"))
                .andExpect(jsonPath("$.ticket.handlingMode").value("AGENT"))
                .andExpect(jsonPath("$.ticket.firstRespondedAt").exists())
                .andExpect(jsonPath("$.messages.length()").value(2))
                .andExpect(jsonPath("$.internalNotes").doesNotExist())
                .andExpect(jsonPath("$.threadId").doesNotExist());

        mvc.perform(get("/api/customer/tickets/{ticketId}", TICKET_ID)
                        .header("X-Synthetic-Customer-Id", "customer-other-demo"))
                .andExpect(status().isNotFound());
    }

    @Test
    void customerCanReplayViewScopedSseAfterASequence() throws Exception {
        when(service.events("customer-demo", TICKET_ID, "customer-public-v1:0"))
                .thenReturn(List.of(new CustomerPublicEvent(
                        "customer-public-v1", 1, "TICKET_ACCEPTED", "{\"ticketId\":\"" + TICKET_ID + "\"}")));
        when(service.events("customer-demo", TICKET_ID, "customer-public-v1:1"))
                .thenReturn(List.of(new CustomerPublicEvent(
                        "customer-public-v1", 2, "PUBLIC_MESSAGE_APPENDED", "{\"author\":\"SUPPORT\"}")));
        when(service.events("customer-demo", TICKET_ID, "customer-public-v1:2")).thenReturn(List.of());

        mvc.perform(get("/api/customer/tickets/{ticketId}/events", TICKET_ID)
                        .header("X-Synthetic-Customer-Id", "customer-demo")
                        .header("Last-Event-ID", "customer-public-v1:0"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted());

        verify(service, timeout(2_000)).events("customer-demo", TICKET_ID, "customer-public-v1:1");
    }

    @Test
    void publicEventUsesViewScopedSchemaEnvelope() {
        var event = new CustomerPublicEvent(
                "customer-public-v1", 3, "PUBLIC_MESSAGE_APPENDED",
                "{\"author\":\"SUPPORT\",\"body\":\"正在处理\",\"sentAt\":\"2026-08-09T00:01:00Z\"}");

        org.assertj.core.api.Assertions.assertThat(event.publicData()).isEqualTo(
                "{\"view\":\"CUSTOMER_PUBLIC\",\"schema\":\"customer-public-v1\",\"payload\":"
                        + "{\"author\":\"SUPPORT\",\"body\":\"正在处理\",\"sentAt\":\"2026-08-09T00:01:00Z\"}}");
    }

    @Test
    void incompatibleOrTrimmedCursorRequiresANewAuthoritativeSnapshot() throws Exception {
        when(service.events("customer-demo", TICKET_ID, "customer-public-v0:9"))
                .thenThrow(new ProjectionCursorException());

        mvc.perform(get("/api/customer/tickets/{ticketId}/events", TICKET_ID)
                        .header("X-Synthetic-Customer-Id", "customer-demo")
                        .header("Last-Event-ID", "customer-public-v0:9"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SNAPSHOT_REQUIRED"));
    }

    @Test
    void eventReplayRechecksTicketOwnership() throws Exception {
        when(service.events("customer-other-demo", TICKET_ID, "customer-public-v1:2"))
                .thenThrow(new TicketNotFoundException());

        mvc.perform(get("/api/customer/tickets/{ticketId}/events", TICKET_ID)
                        .header("X-Synthetic-Customer-Id", "customer-other-demo")
                        .header("Last-Event-ID", "customer-public-v1:2"))
                .andExpect(status().isNotFound());
    }
}
