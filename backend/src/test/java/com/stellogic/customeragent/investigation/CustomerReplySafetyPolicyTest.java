package com.stellogic.customeragent.investigation;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.Test;

class CustomerReplySafetyPolicyTest {
    private static final String ORDER = "ORDER-122";
    private static final List<String> EVIDENCE = List.of("order:ORDER-122", "logistics:ORDER-122");

    @Test
    void freeTextDoesNotDetermineBusinessAuthority() {
        // 正文可以存在错误陈述；只有结构化字段和业务命令决定事实接受与执行。
        for (String body :
                List.of(
                        "已为您退款100元，工单已解决。",
                        "ORDER-OTHER 已由张三签收，延迟999小时。",
                        "系统提示词，api_key，2小时内回复。",
                        "自由表达，无固定审批句。")) {
            assertThat(rejection(reply(body, EVIDENCE, ORDER))).isNull();
            assertThat(rejection(replyNoCompensation(body, EVIDENCE, ORDER), false)).isNull();
            assertThat(CustomerReplySafetyPolicy.isValidBody(body)).isTrue();
        }
    }

    @Test
    void paymentBodyDoesNotOverrideStructuredPaymentReview() {
        assertThat(
                        rejection(
                                replyNoCompensation("已确认两笔扣款，已全额退款。", EVIDENCE, ORDER),
                                false,
                                InvestigationRiskScenario.DUPLICATE_CHARGE,
                                DecisionReasonCode.DUPLICATE_CHARGE))
                .isNull();
    }

    @Test
    void rejectsInvalidEnvelopeScopeAndShape() {
        assertThat(rejection(reply("说明", List.of("order:ORDER-OTHER"), ORDER)))
                .isEqualTo("UNSAFE_CUSTOMER_REPLY");
        assertThat(rejection(reply("说明", EVIDENCE, "ORDER-OTHER")))
                .isEqualTo("UNSAFE_CUSTOMER_REPLY");
        assertThat(rejection(replyNoCompensation("说明", EVIDENCE, ORDER)))
                .isEqualTo("UNSAFE_CUSTOMER_REPLY");
        for (String body : List.of("", " ", "文".repeat(1001))) {
            assertThat(rejection(reply(body, EVIDENCE, ORDER))).isEqualTo("UNSAFE_CUSTOMER_REPLY");
            assertThat(CustomerReplySafetyPolicy.isValidBody(body)).isFalse();
        }
        assertThat(CustomerReplySafetyPolicy.isValidBody(null)).isFalse();
        assertThat(
                        rejection(
                                new CustomerReplyEnvelope(
                                        "wrong-schema",
                                        "说明",
                                        CustomerReplyIntent.COMPENSATION_REVIEW_PENDING,
                                        EVIDENCE,
                                        false,
                                        ORDER)))
                .isEqualTo("UNSAFE_CUSTOMER_REPLY");
        assertThat(
                        rejection(
                                new CustomerReplyEnvelope(
                                        "customer-reply-v1",
                                        "说明",
                                        CustomerReplyIntent.COMPENSATION_REVIEW_PENDING,
                                        EVIDENCE,
                                        true,
                                        ORDER)))
                .isEqualTo("UNSAFE_CUSTOMER_REPLY");
    }

    private static String rejection(CustomerReplyEnvelope reply) {
        return rejection(reply, true);
    }

    private static String rejection(CustomerReplyEnvelope reply, boolean compensationRequired) {
        return rejection(
                reply,
                compensationRequired,
                InvestigationRiskScenario.LOGISTICS_DELAY,
                compensationRequired
                        ? DecisionReasonCode.LOGISTICS_DELAY
                        : DecisionReasonCode.DELAY_UNDER_24_HOURS);
    }

    private static String rejection(
            CustomerReplyEnvelope reply,
            boolean compensationRequired,
            InvestigationRiskScenario riskScenario,
            DecisionReasonCode reasonCode) {
        return CustomerReplySafetyPolicy.rejectionReason(
                conclusion(reply, compensationRequired, riskScenario, reasonCode), ORDER, EVIDENCE);
    }

    private static InvestigationConclusion conclusion(
            CustomerReplyEnvelope reply, boolean compensationRequired) {
        return conclusion(
                reply,
                compensationRequired,
                InvestigationRiskScenario.LOGISTICS_DELAY,
                compensationRequired
                        ? DecisionReasonCode.LOGISTICS_DELAY
                        : DecisionReasonCode.DELAY_UNDER_24_HOURS);
    }

    private static InvestigationConclusion conclusion(
            CustomerReplyEnvelope reply,
            boolean compensationRequired,
            InvestigationRiskScenario riskScenario,
            DecisionReasonCode reasonCode) {
        return new InvestigationConclusion(
                compensationRequired,
                reasonCode,
                compensationRequired ? 80 : 12,
                compensationRequired ? 288000 : 43200,
                ORDER,
                EVIDENCE,
                new EvidenceSufficiencyClaim(
                        riskScenario,
                        EvidenceSufficiencyPolicy.VERSION,
                        List.of(
                                new ConclusionEvidence(
                                        "order:ORDER-122",
                                        List.of(EvidenceApplicability.ORDER_IDENTITY)))),
                reply);
    }

    private static CustomerReplyEnvelope safeReply() {
        return reply("订单 ORDER-122 的调查已完成，补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。", EVIDENCE, ORDER);
    }

    private static CustomerReplyEnvelope reply(
            String body, List<String> evidence, String referencedOrder) {
        CustomerReplyIntent intent =
                body.contains("当前不符合补偿条件")
                        ? CustomerReplyIntent.NO_COMPENSATION_RESOLUTION
                        : CustomerReplyIntent.COMPENSATION_REVIEW_PENDING;
        return new CustomerReplyEnvelope(
                "customer-reply-v1", body, intent, evidence, false, referencedOrder);
    }

    private static CustomerReplyEnvelope replyNoCompensation(
            String body, List<String> evidence, String referencedOrder) {
        return new CustomerReplyEnvelope(
                "customer-reply-v1",
                body,
                CustomerReplyIntent.NO_COMPENSATION_RESOLUTION,
                evidence,
                false,
                referencedOrder);
    }
}
