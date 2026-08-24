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

    private static org.springframework.http.HttpHeaders scopedHeaders() {
        org.springframework.http.HttpHeaders headers = new org.springframework.http.HttpHeaders();
        headers.setBearerAuth("agent-token");
        headers.set("X-Agent-Generation-Id", GENERATION_ID.toString());
        headers.set("X-Agent-Operation", "USE_INVESTIGATION_CAPABILITY");
        headers.set("Idempotency-Key", "generation-capability-request");
        return headers;
    }
}
