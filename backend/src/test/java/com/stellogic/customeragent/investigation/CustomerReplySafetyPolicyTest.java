package com.stellogic.customeragent.investigation;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.Test;

class CustomerReplySafetyPolicyTest {
    private static final String ORDER = "ORDER-122";
    private static final List<String> EVIDENCE = List.of("order:ORDER-122", "logistics:ORDER-122");

    @Test
    void acceptsOnlyTheSafeDeterministicReplyEnvelope() {
        assertThat(rejection(safeReply())).isNull();
        assertThat(
                        rejection(
                                reply(
                                        "我们已核对订单 ORDER-122 的物流记录。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
                                        EVIDENCE,
                                        ORDER)))
                .isNull();
        assertThat(
                        rejection(
                                reply(
                                        "调查结果显示，订单 ORDER-122 的物流出现延迟。补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
                                        EVIDENCE,
                                        ORDER)))
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
    void rejectsFabricatedEvidenceAndOrdersOutsideTheTicketScope() {
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

    private static String rejection(CustomerReplyEnvelope reply) {
        return CustomerReplySafetyPolicy.rejectionReason(conclusion(reply), ORDER, EVIDENCE);
    }

    private static InvestigationConclusion conclusion(CustomerReplyEnvelope reply) {
        return new InvestigationConclusion(
                true, DecisionReasonCode.LOGISTICS_DELAY, 80, 288000, ORDER, EVIDENCE, reply);
    }

    private static CustomerReplyEnvelope safeReply() {
        return reply("订单 ORDER-122 的调查已完成，补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。", EVIDENCE, ORDER);
    }

    private static CustomerReplyEnvelope reply(
            String body, List<String> evidence, String referencedOrder) {
        return new CustomerReplyEnvelope(
                "customer-reply-v1",
                body,
                CustomerReplyIntent.COMPENSATION_REVIEW_PENDING,
                evidence,
                false,
                referencedOrder);
    }
}
