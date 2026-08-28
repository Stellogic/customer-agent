package com.stellogic.customeragent.investigation;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
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
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class AgentInvestigationCapabilityControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("23000000-0000-0000-0000-000000000001");
    private static final UUID GENERATION_ID =
            UUID.fromString("23000000-0000-0000-0000-000000000002");
    private final AgentInvestigationService service =
            org.mockito.Mockito.mock(AgentInvestigationService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(
                            new AgentInvestigationController(service, "agent-token"))
                    .build();

    @Test
    void exposesOnlyTheDeclaredTypedCatalogToTheCurrentAgentScope() throws Exception {
        when(service.capabilities(TICKET_ID, GENERATION_ID))
                .thenReturn(
                        new InvestigationCapabilityCatalog(
                                "investigation-capability-catalog-v1",
                                List.of(
                                        new InvestigationCapabilityDefinition(
                                                InvestigationCapability.CONFIRM_ORDER,
                                                List.of(),
                                                List.of(
                                                        new InvestigationCapabilityField(
                                                                "matchStatus",
                                                                InvestigationCapabilityValueType
                                                                        .STRING,
                                                                true))))));

        mvc.perform(
                        get(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/capabilities",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(scopedHeaders()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.schemaVersion").value("investigation-capability-catalog-v1"))
                .andExpect(jsonPath("$.capabilities[0].name").value("CONFIRM_ORDER"))
                .andExpect(jsonPath("$.capabilities[0].path").doesNotExist())
                .andExpect(jsonPath("$.database").doesNotExist());
    }

    @Test
    void exposesOnlyCurrentSyntheticPublicCommunicationContext() throws Exception {
        when(service.customerCommunicationContext(TICKET_ID, GENERATION_ID))
                .thenReturn(
                        new CustomerCommunicationContext(
                                "customer-communication-input-v1",
                                "包裹还没到，请尽快帮我看看",
                                List.of(
                                        new CustomerCommunicationMessage(
                                                "CUSTOMER", "包裹还没到，请尽快帮我看看"),
                                        new CustomerCommunicationMessage("SUPPORT", "我们正在调查"))));

        org.springframework.http.HttpHeaders headers = scopedHeaders();
        headers.set("X-Agent-Operation", "READ_CUSTOMER_COMMUNICATION_CONTEXT");
        mvc.perform(
                        get(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/customer-communication-context",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(headers))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.schemaVersion").value("customer-communication-input-v1"))
                .andExpect(jsonPath("$.syntheticCustomerText").value("包裹还没到，请尽快帮我看看"))
                .andExpect(jsonPath("$.publicConversation[0].author").value("CUSTOMER"))
                .andExpect(jsonPath("$.publicConversation[0].body").value("包裹还没到，请尽快帮我看看"))
                .andExpect(jsonPath("$.orderReference").doesNotExist())
                .andExpect(jsonPath("$.internalNotes").doesNotExist());
    }

    @Test
    void exposesOnlyMinimumSiblingTicketSummaryForTheCurrentGeneration() throws Exception {
        when(service.siblingTicketSummary(TICKET_ID, GENERATION_ID))
                .thenReturn(
                        new SiblingTicketSummary(
                                "sibling-ticket-summary-v1",
                                List.of(
                                        new SiblingTicketSummaryItem(
                                                "DUPLICATE_CHARGE",
                                                "INVESTIGATING",
                                                "NONE",
                                                true))));

        org.springframework.http.HttpHeaders headers = scopedHeaders();
        headers.set("X-Agent-Operation", "READ_SIBLING_TICKET_SUMMARY");
        mvc.perform(
                        get(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/sibling-summary",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(headers))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.schemaVersion").value("sibling-ticket-summary-v1"))
                .andExpect(jsonPath("$.tickets[0].issueKind").value("DUPLICATE_CHARGE"))
                .andExpect(jsonPath("$.tickets[0].pendingAction").value("NONE"))
                .andExpect(jsonPath("$.tickets[0].compensationFlowExists").value(true))
                .andExpect(jsonPath("$.tickets[0].conversation").doesNotExist())
                .andExpect(jsonPath("$.tickets[0].workingSummary").doesNotExist())
                .andExpect(jsonPath("$.tickets[0].internalNotes").doesNotExist())
                .andExpect(jsonPath("$.tickets[0].ticketId").doesNotExist())
                .andExpect(jsonPath("$.tickets[0].writeUrl").doesNotExist());
    }

    @Test
    void invokesOnlyADeclaredCapabilityWithItsExactParameters() throws Exception {
        when(service.invoke(
                        eq(TICKET_ID),
                        eq(GENERATION_ID),
                        eq("generation-capability-request"),
                        eq(InvestigationCapability.READ_LOGISTICS),
                        any()))
                .thenReturn(
                        new LogisticsFactsResult(
                                InvestigationCapability.READ_LOGISTICS,
                                80,
                                288000,
                                List.of("logistics:ORDER-1")));

        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/capabilities/READ_LOGISTICS",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(scopedHeaders())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"orderReference\":\"ORDER-1\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.capability").value("READ_LOGISTICS"))
                .andExpect(jsonPath("$.delaySeconds").value(288000))
                .andExpect(jsonPath("$.rawHttp").doesNotExist())
                .andExpect(jsonPath("$.token").doesNotExist());
    }

    @Test
    void rejectsUnknownCapabilitiesAndAdditionalParameters() throws Exception {
        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/capabilities/READ_DATABASE",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(scopedHeaders())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{}"))
                .andExpect(status().isBadRequest());
        verify(service).auditRejected(TICKET_ID, "UNKNOWN_INVESTIGATION_CAPABILITY");

        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/capabilities/READ_LOGISTICS",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(scopedHeaders())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"orderReference\":\"ORDER-1\",\"internalToken\":\"no\"}"))
                .andExpect(status().isBadRequest());
        verify(service).auditRejected(TICKET_ID, "INVALID_CAPABILITY_PARAMETERS");
    }

    @Test
    void rejectsWrongMachineGenerationAndOperationScope() throws Exception {
        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/capabilities/CONFIRM_ORDER",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .header("Authorization", "Bearer wrong-token")
                                .header("X-Agent-Generation-Id", UUID.randomUUID())
                                .header("X-Agent-Operation", "READ_DATABASE")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{}"))
                .andExpect(status().isForbidden());
        verify(service).auditRejected(TICKET_ID, "CAPABILITY_SCOPE_REJECTED");
    }

    @Test
    void rejectsCapabilityInvocationWithoutStableRequestIdentity() throws Exception {
        org.springframework.http.HttpHeaders headers = scopedHeaders();
        headers.remove("Idempotency-Key");

        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/capabilities/CONFIRM_ORDER",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(headers)
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{}"))
                .andExpect(status().isBadRequest());
        verify(service).auditRejected(TICKET_ID, "MISSING_IDEMPOTENCY_IDENTITY");
    }

    @Test
    void acceptsOnlyTheExactVersionedCustomerReplyEnvelope() throws Exception {
        when(service.submit(eq(TICKET_ID), eq(GENERATION_ID), eq("reply-request"), any()))
                .thenReturn(
                        new ConclusionAcceptance(
                                true, TicketLifecycleState.INVESTIGATING, null, null, null));

        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/conclusions",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(conclusionHeaders())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(validConclusion("")))
                .andExpect(status().isOk());

        verify(service)
                .submit(
                        eq(TICKET_ID),
                        eq(GENERATION_ID),
                        eq("reply-request"),
                        org.mockito.ArgumentMatchers.argThat(
                                conclusion ->
                                        conclusion
                                                        .customerReply()
                                                        .schemaVersion()
                                                        .equals("customer-reply-v1")
                                                && conclusion
                                                        .customerReply()
                                                        .evidenceRefs()
                                                        .equals(
                                                                List.of(
                                                                        "order:ORDER-122",
                                                                        "logistics:ORDER-122"))));
    }

    @Test
    void rejectsAdditionalPublicFieldsBeforeTheyReachTheService() throws Exception {
        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/conclusions",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .headers(conclusionHeaders())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(validConclusion(",\"rawModel\":\"forbidden\"")))
                .andExpect(status().isUnprocessableEntity());

        verify(service).auditRejected(TICKET_ID, "MALFORMED_CONCLUSION");
        org.mockito.Mockito.verifyNoMoreInteractions(service);
    }

    private static String validConclusion(String additionalReplyField) {
        return """
                {
                  "compensationRequired": true,
                  "reasonCode": "LOGISTICS_DELAY",
                  "delayHours": 80,
                  "delaySeconds": 288000,
                  "orderReference": "ORDER-122",
                  "evidenceRefs": ["order:ORDER-122", "logistics:ORDER-122"],
                  "customerReply": {
                    "schemaVersion": "customer-reply-v1",
                    "body": "订单 ORDER-122 的调查已完成，正在等待人工审批。",
                    "intent": "COMPENSATION_REVIEW_PENDING",
                    "evidenceRefs": ["order:ORDER-122", "logistics:ORDER-122"],
                    "escalationRequired": false,
                    "referencedOrder": "ORDER-122"%s
                  }
                }
                """
                .formatted(additionalReplyField);
    }

    private static org.springframework.http.HttpHeaders conclusionHeaders() {
        org.springframework.http.HttpHeaders headers = scopedHeaders();
        headers.set("X-Agent-Operation", "SUBMIT_INVESTIGATION_CONCLUSION");
        headers.set("Idempotency-Key", "reply-request");
        return headers;
    }

    private static org.springframework.http.HttpHeaders scopedHeaders() {
        org.springframework.http.HttpHeaders headers = new org.springframework.http.HttpHeaders();
        headers.setBearerAuth("agent-token");
        headers.set("X-Agent-Generation-Id", GENERATION_ID.toString());
        headers.set("X-Agent-Operation", "USE_INVESTIGATION_CAPABILITY");
        headers.set("Idempotency-Key", "generation-capability-request");
        return headers;
    }
}
