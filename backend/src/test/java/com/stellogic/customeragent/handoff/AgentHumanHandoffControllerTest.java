package com.stellogic.customeragent.handoff;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class AgentHumanHandoffControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("19000000-0000-0000-0000-000000000001");
    private static final UUID GENERATION_ID = UUID.fromString("19000000-0000-0000-0000-000000000002");
    private final HumanHandoffService service = org.mockito.Mockito.mock(HumanHandoffService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(
            new AgentHumanHandoffController(service, "agent-token")).build();

    @Test
    void agentRequestsTheSharedAtomicHandoffWithAControlledSummary() throws Exception {
        when(service.requestAgentHumanHandoff(any())).thenReturn(
                new AgentHumanHandoffResult("handoff-19", "HUMAN", "FACT_CONFLICT", false));

        mvc.perform(post("/internal/agent/tickets/{ticketId}/generations/{generationId}/human-handoff",
                        TICKET_ID, GENERATION_ID)
                        .header("Authorization", "Bearer agent-token")
                        .header("X-Agent-Generation-Id", GENERATION_ID)
                        .header("X-Agent-Operation", "REQUEST_SAFE_HANDOFF")
                        .header("Idempotency-Key", "handoff-19")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"reasonCode":"FACT_CONFLICT","summary":{
                                  "conclusionCode":"INVESTIGATION_COULD_NOT_CONTINUE",
                                  "facts":[{"type":"ORDER","value":"ORDER-1","evidenceReference":"order:ORDER-1"}]
                                }}
                                """))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.handlingMode").value("HUMAN"))
                .andExpect(jsonPath("$.reasonCode").value("FACT_CONFLICT"))
                .andExpect(jsonPath("$.summary").doesNotExist());
    }

    @Test
    void rejectsUncontrolledReasonCodesAtTheHttpBoundary() throws Exception {
        mvc.perform(post("/internal/agent/tickets/{ticketId}/generations/{generationId}/human-handoff",
                        TICKET_ID, GENERATION_ID)
                        .header("Authorization", "Bearer agent-token")
                        .header("X-Agent-Generation-Id", GENERATION_ID)
                        .header("X-Agent-Operation", "REQUEST_SAFE_HANDOFF")
                        .header("Idempotency-Key", "handoff-19")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"reasonCode\":\"MODEL_SAID_SO\",\"summary\":{\"conclusionCode\":\"X\",\"facts\":[]}}"))
                .andExpect(status().isBadRequest());
    }
}
