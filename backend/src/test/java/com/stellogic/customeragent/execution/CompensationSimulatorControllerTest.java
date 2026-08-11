package com.stellogic.customeragent.execution;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CompensationSimulatorControllerTest {
    private static final UUID EXECUTION_ID = UUID.fromString("30000000-0000-0000-0000-000000000007");
    private final CompensationSimulatorService service = org.mockito.Mockito.mock(CompensationSimulatorService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(
                    new CompensationSimulatorController(service, "executor-secret"))
            .build();

    @Test
    void simulatorCanLoseTheFirstResponseAfterPersistingTheSideEffect() throws Exception {
        when(service.execute(any())).thenReturn(new CompensationSimulatorModels.ExecuteResult(
                CompensationSimulatorModels.ProviderOutcome.SUCCEEDED,
                "simulated-refund:" + EXECUTION_ID, true));

        mvc.perform(post("/internal/compensation-simulator/{executionId}/executions", EXECUTION_ID)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret")
                        .header("Idempotency-Key", "compensation-execution:revision")
                        .header("X-Simulation-Scenario", "AFTER_EFFECT_RESPONSE_LOST")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"parameterDigest":"%s","amount":26.80}
                                """.formatted("a".repeat(64))))
                .andExpect(status().isGatewayTimeout());
    }

    @Test
    void simulatorReconcilesByTheOriginalExecutionIdentity() throws Exception {
        when(service.reconcile(EXECUTION_ID)).thenReturn(new CompensationSimulatorModels.ReconciliationResult(
                "provider-query:" + EXECUTION_ID,
                CompensationExecutionModels.ReconciliationOutcome.FOUND,
                "simulated-refund:" + EXECUTION_ID));

        mvc.perform(get("/internal/compensation-simulator/{executionId}/reconciliation", EXECUTION_ID)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.outcome").value("FOUND"))
                .andExpect(jsonPath("$.resultReference").value("simulated-refund:" + EXECUTION_ID));
    }
}
