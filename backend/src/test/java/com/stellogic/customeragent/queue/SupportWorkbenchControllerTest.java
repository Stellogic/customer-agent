package com.stellogic.customeragent.queue;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static com.stellogic.customeragent.identity.HumanTestPrincipals.support;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
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
    private static final UUID HANDOFF_TICKET =
            UUID.fromString("26000000-0000-0000-0000-000000000001");
    private static final UUID BREACHED_TICKET =
            UUID.fromString("26000000-0000-0000-0000-000000000002");
    private final SupportWorkbenchProjectionService service =
            org.mockito.Mockito.mock(SupportWorkbenchProjectionService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new SupportWorkbenchController(service))
                    .setControllerAdvice(new SupportWorkbenchExceptionHandler())
                    .defaultRequest(get("/").session(session("support-demo")))
                    .build();

    @Test
    void supportReadsAViewScopedAuthoritativeSnapshotWithOnlyMinimumQueueSummaries()
            throws Exception {
        var handoff =
                new SupportQueueItem(
                        HANDOFF_TICKET,
                        "ORDER-157",
                        "PACKAGE_NOT_RECEIVED",
                        SupportTicketLifecycleState.WAITING_FOR_CUSTOMER,
                        SupportHandlingMode.HUMAN,
                        Instant.parse("2026-08-11T01:00:00Z"));
        var breach =
                new SupportQueueItem(
                        BREACHED_TICKET,
                        "ORDER-157",
                        "LOGISTICS_DELAY",
                        SupportTicketLifecycleState.INVESTIGATING,
                        SupportHandlingMode.AGENT,
                        Instant.parse("2026-08-11T01:05:00Z"));
        when(service.snapshot("support-demo", "support-workbench-v2"))
                .thenReturn(
                        new SupportWorkbenchSnapshot(
                                "support-workbench-v2",
                                7,
                                List.of(handoff, breach),
                                List.of(breach)));

        mvc.perform(
                        get("/api/support/workbench/snapshot")
                                .queryParam("schema", "support-workbench-v2")
                                .principal(support()))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.view").value("SUPPORT_WORKBENCH"))
                .andExpect(jsonPath("$.schema").value("support-workbench-v2"))
                .andExpect(jsonPath("$.cursor").value("support-workbench-v2:7"))
                .andExpect(jsonPath("$.sharedQueue.length()").value(2))
                .andExpect(jsonPath("$.escalationQueue.length()").value(1))
                .andExpect(jsonPath("$.sharedQueue[0].ticketId").value(HANDOFF_TICKET.toString()))
                .andExpect(jsonPath("$.sharedQueue[0].orderReference").value("ORDER-157"))
                .andExpect(jsonPath("$.sharedQueue[0].issueKind").value("PACKAGE_NOT_RECEIVED"))
                .andExpect(
                        jsonPath("$.sharedQueue[0].lifecycleState").value("WAITING_FOR_CUSTOMER"))
                .andExpect(jsonPath("$.sharedQueue[0].handlingMode").value("HUMAN"))
                .andExpect(jsonPath("$.sharedQueue[0].reasonCode").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].reasonCodes").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].customerId").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].investigationSummary").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].messages").doesNotExist());
    }

    @Test
    void currentAssignmentIsRecoverableFromTheAuthoritativeSnapshot() throws Exception {
        when(service.snapshot("support-demo", "support-workbench-v2"))
                .thenReturn(
                        new SupportWorkbenchSnapshot(
                                "support-workbench-v2",
                                8,
                                List.of(),
                                List.of(),
                                List.of(HANDOFF_TICKET, BREACHED_TICKET)));

        mvc.perform(
                        get("/api/support/workbench/snapshot")
                                .queryParam("schema", "support-workbench-v2")
                                .principal(support()))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.assignedTicketIds.length()").value(2))
                .andExpect(jsonPath("$.assignedTicketIds[0]").value(HANDOFF_TICKET.toString()))
                .andExpect(jsonPath("$.assignedTicketIds[1]").value(BREACHED_TICKET.toString()))
                .andExpect(jsonPath("$.assignedTicketId").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue.length()").value(0));
    }

    @Test
    void agentModeTicketsCannotBeClaimed() throws Exception {
        when(service.claim("support-demo", BREACHED_TICKET))
                .thenThrow(new SupportTicketNotFoundException());

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/claims", BREACHED_TICKET)
                                .principal(support()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("SUPPORT_TICKET_NOT_FOUND"));
    }

    @Test
    void currentAssigneeCanReleaseTheAssignmentBackToTheQueue() throws Exception {
        when(service.release("support-demo", HANDOFF_TICKET))
                .thenReturn(new SupportAssignmentRelease(HANDOFF_TICKET, "support-demo", false));

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/release", HANDOFF_TICKET)
                                .principal(support()))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.ticketId").value(HANDOFF_TICKET.toString()))
                .andExpect(jsonPath("$.supportId").value("support-demo"))
                .andExpect(jsonPath("$.replayed").value(false));
    }

    @Test
    void reassignmentTerminatesThePreviousAssignee() throws Exception {
        when(service.reassign("support-demo", HANDOFF_TICKET, "internal-demo"))
                .thenReturn(
                        new SupportAssignmentReassignment(
                                HANDOFF_TICKET, "internal-demo", "support-demo", false));

        mvc.perform(
                        post(
                                        "/api/support/workbench/tickets/{ticketId}/reassignments",
                                        HANDOFF_TICKET)
                                .principal(support())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"support-workbench-v2","targetSupportId":"internal-demo"}
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.ticketId").value(HANDOFF_TICKET.toString()))
                .andExpect(jsonPath("$.supportId").value("internal-demo"))
                .andExpect(jsonPath("$.previousSupportId").value("support-demo"))
                .andExpect(jsonPath("$.replayed").value(false));
    }

    @Test
    void claimingAnUnassignedTicketCreatesTheCurrentAssignment() throws Exception {
        when(service.claim("support-demo", HANDOFF_TICKET))
                .thenReturn(new SupportAssignmentClaim(HANDOFF_TICKET, "support-demo", false));

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/claims", HANDOFF_TICKET)
                                .principal(support()))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.ticketId").value(HANDOFF_TICKET.toString()))
                .andExpect(jsonPath("$.supportId").value("support-demo"))
                .andExpect(jsonPath("$.replayed").value(false));
    }

    @Test
    void claimingTheCurrentAssignmentIsAReplay() throws Exception {
        when(service.claim("support-demo", HANDOFF_TICKET))
                .thenReturn(new SupportAssignmentClaim(HANDOFF_TICKET, "support-demo", true));

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/claims", HANDOFF_TICKET)
                                .principal(support()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.replayed").value(true));
    }

    @Test
    void anotherSupportCannotSeeOrClaimAnAlreadyAssignedTicket() throws Exception {
        when(service.claim("support-demo", HANDOFF_TICKET))
                .thenThrow(new SupportTicketNotFoundException());
        when(service.details("support-demo", HANDOFF_TICKET))
                .thenThrow(new SupportTicketNotFoundException());

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/claims", HANDOFF_TICKET)
                                .principal(support()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("SUPPORT_TICKET_NOT_FOUND"));
        mvc.perform(
                        get("/api/support/workbench/tickets/{ticketId}", HANDOFF_TICKET)
                                .principal(support()))
                .andExpect(status().isNotFound())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.code").value("SUPPORT_TICKET_NOT_FOUND"));
    }

    @Test
    void humanModePublicReplyUsesStableMessageIdentity() throws Exception {
        UUID publicMessageId = UUID.fromString("26000000-0000-0000-0000-000000000101");
        when(service.publicReply("support-demo", HANDOFF_TICKET, "reply-163-1", "包裹已在派送中"))
                .thenReturn(
                        new SupportPublicReplyResult(
                                HANDOFF_TICKET,
                                "reply-163-1",
                                publicMessageId,
                                "ACCEPTED",
                                false));

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/messages", HANDOFF_TICKET)
                                .principal(support())
                                .header("Idempotency-Key", "reply-163-1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"support-workbench-v2","message":"包裹已在派送中"}
                                        """))
                .andExpect(status().isCreated())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.schema").value("support-workbench-v2"))
                .andExpect(jsonPath("$.ticketId").value(HANDOFF_TICKET.toString()))
                .andExpect(jsonPath("$.messageId").value("reply-163-1"))
                .andExpect(jsonPath("$.publicMessageId").value(publicMessageId.toString()))
                .andExpect(jsonPath("$.outcome").value("ACCEPTED"))
                .andExpect(jsonPath("$.accepted").value(true))
                .andExpect(jsonPath("$.replayed").value(false));
    }

    @Test
    void replayingTheSamePublicReplyReturnsTheAuthoritativeResult() throws Exception {
        UUID publicMessageId = UUID.fromString("26000000-0000-0000-0000-000000000101");
        when(service.publicReply("support-demo", HANDOFF_TICKET, "reply-163-1", "包裹已在派送中"))
                .thenReturn(
                        new SupportPublicReplyResult(
                                HANDOFF_TICKET,
                                "reply-163-1",
                                publicMessageId,
                                "ACCEPTED",
                                true));

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/messages", HANDOFF_TICKET)
                                .principal(support())
                                .header("Idempotency-Key", "reply-163-1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"support-workbench-v2","message":"包裹已在派送中"}
                                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.publicMessageId").value(publicMessageId.toString()))
                .andExpect(jsonPath("$.replayed").value(true));
    }

    @Test
    void uncertainClientsCanQueryTheAuthoritativePublicReply() throws Exception {
        UUID publicMessageId = UUID.fromString("26000000-0000-0000-0000-000000000101");
        when(service.queryPublicReply("support-demo", HANDOFF_TICKET, "reply-163-1"))
                .thenReturn(
                        new SupportPublicReplyResult(
                                HANDOFF_TICKET,
                                "reply-163-1",
                                publicMessageId,
                                "ACCEPTED",
                                true));

        mvc.perform(
                        get(
                                        "/api/support/workbench/tickets/{ticketId}/messages/{messageId}",
                                        HANDOFF_TICKET,
                                        "reply-163-1")
                                .principal(support()))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.messageId").value("reply-163-1"))
                .andExpect(jsonPath("$.publicMessageId").value(publicMessageId.toString()))
                .andExpect(jsonPath("$.accepted").value(true))
                .andExpect(jsonPath("$.replayed").value(true));
    }

    @Test
    void onlyTheCurrentHumanAssigneeCanSendAPublicReply() throws Exception {
        when(service.publicReply("support-demo", HANDOFF_TICKET, "reply-163-2", "不能发送"))
                .thenThrow(new SupportPublicReplyNotAllowedException());

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/messages", HANDOFF_TICKET)
                                .principal(support())
                                .header("Idempotency-Key", "reply-163-2")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"support-workbench-v2","message":"不能发送"}
                                        """))
                .andExpect(status().isConflict())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.code").value("SUPPORT_REPLY_NOT_ALLOWED"));
    }

    @Test
    void conflictingIdempotencyBindingsAreRejected() throws Exception {
        when(service.publicReply("support-demo", HANDOFF_TICKET, "reply-163-3", "另一段内容"))
                .thenThrow(new SupportReplyIdentityConflictException());

        mvc.perform(
                        post("/api/support/workbench/tickets/{ticketId}/messages", HANDOFF_TICKET)
                                .principal(support())
                                .header("Idempotency-Key", "reply-163-3")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"support-workbench-v2","message":"另一段内容"}
                                        """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SUPPORT_REPLY_IDENTITY_CONFLICT"));
    }

    @Test
    void legacySnapshotRemainsStrictlyCompatibleDuringTheEpochCutover() throws Exception {
        var item =
                new SupportQueueItem(
                        HANDOFF_TICKET,
                        "ORDER-157",
                        "PACKAGE_NOT_RECEIVED",
                        SupportTicketLifecycleState.WAITING_FOR_CUSTOMER,
                        SupportHandlingMode.HUMAN,
                        Instant.parse("2026-08-11T01:00:00Z"));
        when(service.snapshot("support-demo", "support-workbench-v1"))
                .thenReturn(
                        new SupportWorkbenchSnapshot(
                                "support-workbench-v1", 9, List.of(item), List.of()));

        mvc.perform(get("/api/support/workbench/snapshot").principal(support()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.schema").value("support-workbench-v1"))
                .andExpect(jsonPath("$.cursor").value("support-workbench-v1:9"))
                .andExpect(jsonPath("$.sharedQueue[0].ticketId").value(HANDOFF_TICKET.toString()))
                .andExpect(
                        jsonPath("$.sharedQueue[0].lifecycleState").value("WAITING_FOR_CUSTOMER"))
                .andExpect(jsonPath("$.sharedQueue[0].handlingMode").value("HUMAN"))
                .andExpect(jsonPath("$.sharedQueue[0].enteredAt").exists())
                .andExpect(jsonPath("$.sharedQueue[0].orderReference").doesNotExist())
                .andExpect(jsonPath("$.sharedQueue[0].issueKind").doesNotExist());
    }

    @Test
    void replaySwitchesToLivePollingWithoutMissingTheConcurrentQueueChange() throws Exception {
        when(service.events("support-demo", "support-workbench-v2:0"))
                .thenReturn(
                        List.of(
                                new SupportWorkbenchEvent(
                                        "support-workbench-v2",
                                        1,
                                        "QUEUE_TICKET_UPSERTED",
                                        "{\"ticketId\":\""
                                                + HANDOFF_TICKET
                                                + "\",\"orderReference\":\"ORDER-157\","
                                                + "\"issueKind\":\"PACKAGE_NOT_RECEIVED\","
                                                + "\"lifecycleState\":\"INVESTIGATING\","
                                                + "\"handlingMode\":\"HUMAN\",\"sharedEnteredAt\":\"2026-08-11T01:00:00Z\","
                                                + "\"escalationEnteredAt\":null}")));
        when(service.events("support-demo", "support-workbench-v2:1"))
                .thenReturn(
                        List.of(
                                new SupportWorkbenchEvent(
                                        "support-workbench-v2",
                                        2,
                                        "QUEUE_TICKET_REMOVED",
                                        "{\"ticketId\":\"" + HANDOFF_TICKET + "\"}")));
        when(service.events("support-demo", "support-workbench-v2:2")).thenReturn(List.of());

        mvc.perform(
                        get("/api/support/workbench/events")
                                .principal(support())
                                .header("Last-Event-ID", "support-workbench-v2:0"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted());

        verify(service, timeout(2_000)).events("support-demo", "support-workbench-v2:1");
        verify(service, timeout(2_000)).events("support-demo", "support-workbench-v2:2");
    }

    @Test
    void incompatibleOrTrimmedCursorRequiresANewSnapshot() throws Exception {
        when(service.events("support-demo", "support-workbench-v0:9"))
                .thenThrow(new SupportWorkbenchCursorException());

        mvc.perform(
                        get("/api/support/workbench/events")
                                .principal(support())
                                .accept(MediaType.TEXT_EVENT_STREAM)
                                .header("Last-Event-ID", "support-workbench-v0:9"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SNAPSHOT_REQUIRED"));
    }

    @Test
    void queueVisibilityDoesNotGrantGuessedOrCachedTicketDetailAccess() throws Exception {
        when(service.details("support-demo", HANDOFF_TICKET))
                .thenThrow(new SupportTicketNotFoundException());

        mvc.perform(
                        get("/api/support/workbench/tickets/{ticketId}", HANDOFF_TICKET)
                                .principal(support()))
                .andExpect(status().isNotFound())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.code").value("SUPPORT_TICKET_NOT_FOUND"));
    }

    @Test
    void assignedTicketAuthorityStreamRevalidatesTheCurrentAssignment() throws Exception {
        when(service.details("support-demo", HANDOFF_TICKET))
                .thenReturn(org.mockito.Mockito.mock(SupportTicketDetails.class));

        mvc.perform(
                        get("/api/support/workbench/tickets/{ticketId}/events", HANDOFF_TICKET)
                                .principal(support()))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted());

        verify(service, timeout(2_000).atLeast(2)).details("support-demo", HANDOFF_TICKET);
    }

    @Test
    void supportEventUsesItsOwnWhitelistedEnvelope() {
        var event =
                new SupportWorkbenchEvent(
                        "support-workbench-v2",
                        3,
                        "QUEUE_TICKET_REMOVED",
                        "{\"ticketId\":\"" + HANDOFF_TICKET + "\"}");

        org.assertj.core.api.Assertions.assertThat(event.publicData())
                .isEqualTo(
                        "{\"view\":\"SUPPORT_WORKBENCH\",\"schema\":\"support-workbench-v2\",\"payload\":"
                                + "{\"ticketId\":\""
                                + HANDOFF_TICKET
                                + "\"}}");
    }
}
