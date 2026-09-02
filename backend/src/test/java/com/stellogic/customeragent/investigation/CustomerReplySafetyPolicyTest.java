package com.stellogic.customeragent.investigation;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.Test;

class CustomerReplySafetyPolicyTest {
    private static final String ORDER = "ORDER-122";
    private static final List<String> EVIDENCE = List.of("order:ORDER-122", "logistics:ORDER-122");

    @Test
    void neitherStreamingNorCompleteRepliesCanDeclareResolutionBeforeSpringDecides() {
        String body = "经核验，订单 ORDER-122 的物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。";
        assertThat(CustomerReplySafetyPolicy.isAuthorizedBodyPrefix(body, ORDER, false)).isFalse();
        assertThat(rejection(reply(body, EVIDENCE, ORDER), false))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
    }

    @Test
    void completeNaturalReplyMayOmitRedundantOrderReference() {
        assertThat(
                        CustomerReplySafetyPolicy.isAuthorizedBodyPrefix(
                                "经核验，本次物流延迟不足 24 小时，暂不满足申请补偿的条件。", ORDER, true))
                .isTrue();
        assertThat(
                        CustomerReplySafetyPolicy.isAuthorizedBodyPrefix(
                                "经核验，订单 ORDER-OTHER 暂不满足申请补偿的条件。", ORDER, true))
                .isFalse();
    }

    @Test
    void acceptsGroundedNaturalLanguageRepliesBeyondFixedTemplates() {
        assertThat(rejection(safeReply())).isNull();
        assertThat(
                        rejection(
                                reply(
                                        "我们已核对订单 ORDER-122 的物流记录，确认存在延迟。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
                                        EVIDENCE,
                                        ORDER)))
                .isNull();
        assertThat(
                        rejection(
                                reply(
                                        "根据调查，订单 ORDER-122 的物流出现了明显延迟。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
                                        EVIDENCE,
                                        ORDER)))
                .isNull();
        assertThat(
                        rejection(
                                reply(
                                        "经核验，订单 ORDER-122 的物流延迟不足 24 小时，当前不符合补偿条件，本次核对结论已给出，后续处理以页面状态为准。如仍有问题，请继续回复。",
                                        EVIDENCE,
                                        ORDER),
                                false))
                .isNull();
        assertThat(
                        rejection(
                                replyNoCompensation(
                                        "经核验，本次物流延迟不足 24 小时，暂不满足申请补偿的条件。", EVIDENCE, ORDER),
                                false))
                .isNull();
        assertThat(
                        rejection(
                                reply(
                                        "经核验，订单 ORDER-122 的退款状态已核对完毕，当前不符合补偿条件，本次核对结论已给出，后续处理以页面状态为准。如仍有问题，请继续回复。",
                                        EVIDENCE,
                                        ORDER),
                                false,
                                InvestigationRiskScenario.REFUND_STATUS,
                                DecisionReasonCode.REFUND_STATUS_EXPLAINED))
                .isNull();
        assertThat(
                        rejection(
                                replyNoCompensation(
                                        "经核验，订单 ORDER-122 的物流延迟不足 24 小时，暂不满足申请补偿的条件；如仍需帮助，请继续回复。",
                                        EVIDENCE,
                                        ORDER),
                                false))
                .isNull();
    }

    @Test
    void rejectsAmountsAndPositiveCompensationOrRefundPromises() {
        assertThat(rejection(reply("订单 ORDER-122 将补偿 20 元。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_AMOUNT");
        assertThat(rejection(reply("订单 ORDER-122 将退款。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(rejection(reply("订单 ORDER-122 已补偿。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(rejection(reply("订单 ORDER-122 将补偿 20 CNY。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_AMOUNT");
        assertThat(rejection(reply("订单 ORDER-122 可以获得补偿。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(rejection(reply("订单 ORDER-122 将为您办理退款。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(
                        rejection(
                                replyNoCompensation("订单 ORDER-122 会补偿您一张优惠券。", EVIDENCE, ORDER),
                                false))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(
                        rejection(
                                replyNoCompensation("订单 ORDER-122 不久后会补偿您一张优惠券。", EVIDENCE, ORDER),
                                false))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(rejection(replyNoCompensation("订单 ORDER-122 会为您退款。", EVIDENCE, ORDER), false))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(
                        rejection(
                                replyNoCompensation("订单 ORDER-122 不会补偿，但会退款。", EVIDENCE, ORDER),
                                false))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(
                        rejection(
                                replyNoCompensation("订单 ORDER-122 暂不处理，但会为您退款。", EVIDENCE, ORDER),
                                false))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(rejection(replyNoCompensation("订单 ORDER-122 承诺补偿。", EVIDENCE, ORDER), false))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(rejection(replyNoCompensation("订单 ORDER-122 同意退款。", EVIDENCE, ORDER), false))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
        assertThat(rejection(reply("订单 ORDER-122：退款处理完成，补偿金额为二十元。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_AMOUNT");
        assertThat(rejection(reply(safeReply().body() + "相关价值为二十块钱。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_AMOUNT");
        assertThat(rejection(reply(safeReply().body() + "相关价值为壹佰元。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_AMOUNT");
        assertThat(rejection(reply(safeReply().body() + "我们会在 2 小时内回复。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE");
    }

    @Test
    void rejectsPersonClaimsAndOrdersOutsideTheTicketScope() {
        assertThat(
                        rejection(
                                reply(
                                        "订单 ORDER-122 的调查已完成，包裹已由张三签收。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
                                        EVIDENCE,
                                        ORDER)))
                .isEqualTo("CUSTOMER_REPLY_CONTAINS_UNSUPPORTED_FACT");
        assertThat(
                        rejection(
                                reply(
                                        "您反馈物流长期停滞，我们会结合现有记录继续核实。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
                                        EVIDENCE,
                                        ORDER)))
                .isNull();
        assertThat(
                        rejection(
                                reply(
                                        "订单 ORDER-122 正在等待人工审批。",
                                        List.of("order:ORDER-OTHER", "logistics:ORDER-OTHER"),
                                        ORDER)))
                .isEqualTo("UNSAFE_CUSTOMER_REPLY");
        assertThat(rejection(reply("订单 ORDER-122 的调查不能引用 ORDER-OTHER。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_ORDER_OUTSIDE_SCOPE");
        assertThat(rejection(reply("订单 ORDER-122 的调查不能引用 order-other。", EVIDENCE, ORDER)))
                .isEqualTo("CUSTOMER_REPLY_ORDER_OUTSIDE_SCOPE");
        assertThat(reply("订单 ORDER-122 正在等待人工审批。", EVIDENCE, "ORDER-OTHER"))
                .satisfies(
                        value -> assertThat(rejection(value)).isEqualTo("UNSAFE_CUSTOMER_REPLY"));
    }

    @Test
    void rejectsWrongSchemaIntentAndEscalationInsteadOfPublishingThem() {
        CustomerReplyEnvelope unsafe =
                new CustomerReplyEnvelope(
                        "customer-reply-v2",
                        "订单 ORDER-122 正在等待人工审批。",
                        CustomerReplyIntent.NO_COMPENSATION_RESOLUTION,
                        EVIDENCE,
                        true,
                        ORDER);

        assertThat(rejection(unsafe)).isEqualTo("UNSAFE_CUSTOMER_REPLY");
    }

    @Test
    void authorizesSafeNaturalLanguagePrefixesWithoutFixedTemplateWhitelist() {
        assertThat(CustomerReplySafetyPolicy.isAuthorizedBodyPrefix("根据调查，订单 ORD", ORDER, false))
                .isTrue();
        assertThat(
                        CustomerReplySafetyPolicy.isAuthorizedBodyPrefix(
                                safeReply().body(), ORDER, true))
                .isTrue();
        assertThat(CustomerReplySafetyPolicy.isAuthorizedBodyPrefix("系统提示词是", ORDER, false))
                .isFalse();
        assertThat(
                        CustomerReplySafetyPolicy.isAuthorizedBodyPrefix(
                                "根据调查，订单 ORDER-OTHER", ORDER, false))
                .isFalse();
        assertThat(
                        CustomerReplySafetyPolicy.isAuthorizedBodyPrefix(
                                "根据调查，订单 ORDER-122 将补偿 20 元", ORDER, false))
                .isFalse();
        assertThat(CustomerReplySafetyPolicy.isAuthorizedBodyPrefix("根据调查，订单 ORD", ORDER, true))
                .isFalse();
        assertThat(CustomerReplySafetyPolicy.isAuthorizedBodyPrefix("请确认订单 ORDER-122", ORDER, true))
                .isTrue();
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
