package com.stellogic.customeragent.execution;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CompensationExecutionControllerTest {
    private static final UUID EXECUTION_ID = UUID.fromString("30000000-0000-0000-0000-000000000001");
    private static final UUID ATTEMPT_ID = UUID.fromString("30000000-0000-0000-0000-000000000002");
    private static final String PARAMETER_DIGEST =
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    private final CompensationExecutionService service =
            org.mockito.Mockito.mock(CompensationExecutionService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(
                    new CompensationExecutionController(service, new ExecutorMachineIdentity("executor-secret")))
            .build();

    @Test
    void assignedExecutorReadsAndClaimsOnlyImmutableExecutionParameters() throws Exception {
        when(service.assignments("compensation-executor")).thenReturn(List.of(
                new CompensationExecutionModels.Assignment(
                        EXECUTION_ID, CompensationExecutionModels.CompensationMethod.COUPON,
                        new BigDecimal("10.00"), CompensationExecutionModels.ExecutionStatus.READY,
                        "compensation-execution:revision")));
        when(service.claim(any())).thenReturn(new CompensationExecutionModels.ClaimResult(
                EXECUTION_ID, ATTEMPT_ID, CompensationExecutionModels.ExecutionStatus.PROCESSING,
                "compensation-execution:revision", PARAMETER_DIGEST,
                CompensationExecutionModels.CompensationMethod.COUPON, new BigDecimal("10.00"), false));

        mvc.perform(get("/internal/compensation-executions")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].executionId").value(EXECUTION_ID.toString()))
                .andExpect(jsonPath("$[0].compensationMethod").value("COUPON"))
                .andExpect(jsonPath("$[0].amount").value(10.00))
                .andExpect(jsonPath("$[0].idempotencyKey").value("compensation-execution:revision"))
                .andExpect(jsonPath("$[0].proposalRevisionId").doesNotExist())
                .andExpect(jsonPath("$[0].decisionId").doesNotExist());

        mvc.perform(post("/internal/compensation-executions/{executionId}/claims", EXECUTION_ID)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret")
                        .header("Idempotency-Key", "worker-delivery-23"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("PROCESSING"))
                .andExpect(jsonPath("$.attemptId").value(ATTEMPT_ID.toString()))
                .andExpect(jsonPath("$.idempotencyKey").value("compensation-execution:revision"))
                .andExpect(jsonPath("$.parameterDigest").value(PARAMETER_DIGEST))
                .andExpect(jsonPath("$.replayed").value(false));
    }

    @Test
    void nonExecutorCannotReadOrAdvanceExecutions() throws Exception {
        mvc.perform(get("/internal/compensation-executions")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer wrong-secret"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/internal/compensation-executions/{executionId}/claims", EXECUTION_ID)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer wrong-secret")
                        .header("Idempotency-Key", "worker-delivery-23"))
                .andExpect(status().isForbidden());
    }

    @Test
    void executorConfirmsSuccessWithoutSupplyingBusinessParameters() throws Exception {
        when(service.succeed(any())).thenReturn(new CompensationExecutionModels.SuccessResult(
                EXECUTION_ID, ATTEMPT_ID, CompensationExecutionModels.ExecutionStatus.SUCCEEDED,
                CompensationExecutionModels.CompensationMethod.COUPON, new BigDecimal("10.00"),
                "已发放 10.00 CNY 优惠券。", false));

        mvc.perform(post("/internal/compensation-executions/{executionId}/success", EXECUTION_ID)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret")
                        .header("Idempotency-Key", "worker-result-23")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"attemptId":"%s","idempotencyKey":"compensation-execution:revision",
                                 "parameterDigest":"%s"}
                                """.formatted(ATTEMPT_ID, PARAMETER_DIGEST)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SUCCEEDED"))
                .andExpect(jsonPath("$.compensationMethod").value("COUPON"))
                .andExpect(jsonPath("$.amount").value(10.00))
                .andExpect(jsonPath("$.customerMessage").value("已发放 10.00 CNY 优惠券。"))
                .andExpect(jsonPath("$.orderReference").doesNotExist())
                .andExpect(jsonPath("$.idempotencyKey").doesNotExist())
                .andExpect(jsonPath("$.parameterDigest").doesNotExist());
    }

    @Test
    void executorMarksAmbiguousResultUnknownAndSubmitsAuthoritativeReconciliation() throws Exception {
        when(service.markUnknown(any())).thenReturn(new CompensationExecutionModels.TransitionResult(
                EXECUTION_ID, ATTEMPT_ID, CompensationExecutionModels.ExecutionStatus.UNKNOWN,
                "补偿结果正在自动确认中，请勿重复提交。", false));
        when(service.reconcile(any())).thenReturn(new CompensationExecutionModels.TransitionResult(
                EXECUTION_ID, ATTEMPT_ID, CompensationExecutionModels.ExecutionStatus.SUCCEEDED,
                "已完成 26.80 CNY 模拟部分退款，退回原支付方式（尾号 4242）。", false));

        mvc.perform(post("/internal/compensation-executions/{executionId}/unknown", EXECUTION_ID)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret")
                        .header("Idempotency-Key", "unknown:" + EXECUTION_ID)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"attemptId":"%s","idempotencyKey":"compensation-execution:revision",
                                 "parameterDigest":"%s"}
                                """.formatted(ATTEMPT_ID, PARAMETER_DIGEST)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UNKNOWN"))
                .andExpect(jsonPath("$.customerMessage")
                        .value("补偿结果正在自动确认中，请勿重复提交。"));

        mvc.perform(post("/internal/compensation-executions/{executionId}/reconciliations", EXECUTION_ID)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret")
                        .header("Idempotency-Key", "reconcile:" + EXECUTION_ID + ":provider-query-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"queryId":"provider-query-1","outcome":"FOUND",
                                 "resultReference":"simulated-refund:%s"}
                                """.formatted(EXECUTION_ID)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SUCCEEDED"))
                .andExpect(jsonPath("$.customerMessage")
                        .value("已完成 26.80 CNY 模拟部分退款，退回原支付方式（尾号 4242）。"));
    }

    @Test
    void executorReportsConfirmedPreEffectFailure() throws Exception {
        when(service.markFailed(any())).thenReturn(new CompensationExecutionModels.TransitionResult(
                EXECUTION_ID, ATTEMPT_ID, CompensationExecutionModels.ExecutionStatus.FAILED, null, false));

        mvc.perform(post("/internal/compensation-executions/{executionId}/failures", EXECUTION_ID)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer executor-secret")
                        .header("Idempotency-Key", "failure:" + EXECUTION_ID)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"attemptId":"%s","idempotencyKey":"compensation-execution:revision",
                                 "parameterDigest":"%s"}
                                """.formatted(ATTEMPT_ID, PARAMETER_DIGEST)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("FAILED"))
                .andExpect(jsonPath("$.customerMessage").doesNotExist());
    }
}
