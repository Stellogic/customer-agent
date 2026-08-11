package com.stellogic.customeragent.queue;

import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
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

class SupportWorkbenchControllerTest {
    private static final UUID HANDOFF_TICKET = UUID.fromString("26000000-0000-0000-0000-000000000001");
    private static final UUID BREACHED_TICKET = UUID.fromString("26000000-0000-0000-0000-000000000002");
    private final SupportWorkbenchProjectionService service =
            org.mockito.Mockito.mock(SupportWorkbenchProjectionService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new SupportWorkbenchController(service))
            .setControllerAdvice(new SupportWorkbenchExceptionHandler())
            .build();

    @Test
    void supportReadsAViewScopedAuthoritativeSnapshotWithOnlyMinimumQueueSummaries() throws Exception {
        var handoff = new SupportQueueItem(
                HANDOFF_TICKET, "WAITING_FOR_CUSTOMER", "HUMAN", Instant.parse("2026-08-11T01:00:00Z"));
        var breach = new SupportQueueItem(
                BREACHED_TICKET, "INVESTIGATING", "AGENT", Instant.parse("2026-08-11T01:05:00Z"));
        when(service.snapshot("support-demo")).thenReturn(new SupportWorkbenchSnapshot(
                "support-workbench-v1", 7, List.of(handoff, breach), List.of(breach)));

        mvc.perform(get("/api/support/workbench/snapshot")
                        .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.view").value("SUPPORT_WORKBENCH"))
                .andExpect(jsonPath("$.schema").value("support-workbench-v1"))
                .andExpect(jsonPath("$.cursor").value("support-workbench-v1:7"))
                .andExpect(jsonPath("$.sharedQueue.length()").value(2))
                .andExpect(jsonPath("$.escalationQueue.length()").value(1))
                .andExpect(jsonPath("$.sharedQueue[0].ticketId").value(HANDOFF_TICKET.toString()))
                .andExpect(jsonPath("$.sharedQueue[0].lifecycleState").value("WAITING_FOR_CUSTOMER"))
                .andExpect(jsonPath("$.sharedQueue[0].handlingMode").value("HUMAN"))
                .andExpect(jsonPath("$.sharedQueue[0].reasonCode").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].reasonCodes").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].customerId").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].investigationSummary").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].messages").doesNotExist());
    }

    @Test
    void customerAndApproverCannotReadSupportWorkbenchRoutes() throws Exception {
        mvc.perform(get("/api/support/workbench/snapshot")
                        .header("X-Synthetic-Customer-Id", "customer-demo"))
                .andExpect(status().isForbidden());

        mvc.perform(get("/api/support/workbench/snapshot")
                        .header("X-Synthetic-Approver-Id", "approver-demo"))
                .andExpect(status().isForbidden());
    }

    @Test
    void replaySwitchesToLivePollingWithoutMissingTheConcurrentQueueChange() throws Exception {
        when(service.events("support-demo", "support-workbench-v1:0"))
                .thenReturn(List.of(new SupportWorkbenchEvent(
                        "support-workbench-v1", 1, "QUEUE_TICKET_UPSERTED",
                        "{\"ticketId\":\"" + HANDOFF_TICKET + "\",\"lifecycleState\":\"INVESTIGATING\","
                                + "\"handlingMode\":\"HUMAN\",\"sharedEnteredAt\":\"2026-08-11T01:00:00Z\","
                                + "\"escalationEnteredAt\":null}")));
        when(service.events("support-demo", "support-workbench-v1:1"))
                .thenReturn(List.of(new SupportWorkbenchEvent(
                        "support-workbench-v1", 2, "QUEUE_TICKET_REMOVED",
                        "{\"ticketId\":\"" + HANDOFF_TICKET + "\"}")));
        when(service.events("support-demo", "support-workbench-v1:2")).thenReturn(List.of());

        mvc.perform(get("/api/support/workbench/events")
                        .header("X-Synthetic-Support-Id", "support-demo")
                        .header("Last-Event-ID", "support-workbench-v1:0"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted());

        verify(service, timeout(2_000)).events("support-demo", "support-workbench-v1:1");
        verify(service, timeout(2_000)).events("support-demo", "support-workbench-v1:2");
    }

    @Test
    void incompatibleOrTrimmedCursorRequiresANewSnapshot() throws Exception {
        when(service.events("support-demo", "support-workbench-v0:9"))
                .thenThrow(new SupportWorkbenchCursorException());

        mvc.perform(get("/api/support/workbench/events")
                        .header("X-Synthetic-Support-Id", "support-demo")
                        .header("Last-Event-ID", "support-workbench-v0:9"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SNAPSHOT_REQUIRED"));
    }

    @Test
    void queueVisibilityDoesNotGrantGuessedOrCachedTicketDetailAccess() throws Exception {
        when(service.details("support-demo", HANDOFF_TICKET)).thenThrow(new SupportTicketNotFoundException());

        mvc.perform(get("/api/support/workbench/tickets/{ticketId}", HANDOFF_TICKET)
                        .header("X-Synthetic-Support-Id", "support-demo"))
                .andExpect(status().isNotFound())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.code").value("SUPPORT_TICKET_NOT_FOUND"));
    }

    @Test
    void supportEventUsesItsOwnWhitelistedEnvelope() {
        var event = new SupportWorkbenchEvent(
                "support-workbench-v1", 3, "QUEUE_TICKET_REMOVED", "{\"ticketId\":\"" + HANDOFF_TICKET + "\"}");

        org.assertj.core.api.Assertions.assertThat(event.publicData()).isEqualTo(
                "{\"view\":\"SUPPORT_WORKBENCH\",\"schema\":\"support-workbench-v1\",\"payload\":"
                        + "{\"ticketId\":\"" + HANDOFF_TICKET + "\"}}");
    }
}
