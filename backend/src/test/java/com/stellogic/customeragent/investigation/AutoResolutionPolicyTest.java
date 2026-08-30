package com.stellogic.customeragent.investigation;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class AutoResolutionPolicyTest {
    @Test
    void springWhitelistAllowsOnlyThreeExplicitScenarioAndConclusionPairs() {
        assertThat(AutoResolutionPolicy.WAIT).isEqualTo(Duration.ofSeconds(300));
        assertThat(scenario(DecisionReasonCode.DELAY_UNDER_24_HOURS, InvestigationRiskScenario.LOGISTICS_DELAY,
                order(false, false, false, 0, "IN_TRANSIT", 23), "物流状态是什么"))
                .isEqualTo("AUTHORITATIVE_STATUS_EXPLANATION");
        assertThat(scenario(DecisionReasonCode.ORDER_RULE_EXPLAINED, InvestigationRiskScenario.ORDER_ADDRESS_OR_CANCEL_RULE,
                order(false, false, false, 0, "IN_TRANSIT"), "请说明订单规则"))
                .isEqualTo("RULE_EXPLANATION");
        assertThat(scenario(DecisionReasonCode.DELAY_UNDER_24_HOURS, InvestigationRiskScenario.LOGISTICS_DELAY,
                order(false, false, false, 0, "IN_TRANSIT"), "核对已完成的状态"))
                .isEqualTo("COMPLETED_NON_COMPENSATION_CHECK");
        assertThat(scenario(DecisionReasonCode.REFUND_STATUS_EXPLAINED, InvestigationRiskScenario.REFUND_STATUS,
                order(false, false, false, 0, "IN_TRANSIT"), "核对退款"))
                .isNull();
    }

    @Test
    void aRuleQuestionMustNotHideAnOrderOperationRequest() {
        var order = order(false, false, false, 0, "IN_TRANSIT");
        assertThat(scenario(DecisionReasonCode.ORDER_RULE_EXPLAINED,
                InvestigationRiskScenario.ORDER_ADDRESS_OR_CANCEL_RULE, order,
                "订单地址填错了，需要修改收货地址")).isNull();
        assertThat(scenario(DecisionReasonCode.ORDER_RULE_EXPLAINED,
                InvestigationRiskScenario.ORDER_ADDRESS_OR_CANCEL_RULE, order,
                "取消订单的规则是什么？")).isEqualTo("RULE_EXPLANATION");
        assertThat(scenario(DecisionReasonCode.ORDER_RULE_EXPLAINED,
                InvestigationRiskScenario.ORDER_ADDRESS_OR_CANCEL_RULE, order,
                "取消订单的规则是什么？\n请立即取消订单")).isNull();
    }

    @Test
    void issueKindOrAnAllowedReasonCannotOverrideTheRiskScenario() {
        for (InvestigationRiskScenario risk : List.of(InvestigationRiskScenario.PACKAGE_SIGNED_NOT_RECEIVED,
                InvestigationRiskScenario.PACKAGE_SUSPECTED_LOST, InvestigationRiskScenario.DUPLICATE_CHARGE,
                InvestigationRiskScenario.OTHER_GENERAL, InvestigationRiskScenario.LOGISTICS_STALLED)) {
            assertThat(scenario(DecisionReasonCode.DELAY_UNDER_24_HOURS, risk,
                    order(false, false, false, 0, "IN_TRANSIT"), "请核对"))
                    .as(risk.name()).isNull();
        }
        assertThat(AutoResolutionPolicy.scenario(conclusion(DecisionReasonCode.DELAY_UNDER_24_HOURS,
                        InvestigationRiskScenario.LOGISTICS_DELAY), order(false, false, false, 0, "SIGNED"),
                "PACKAGE_NOT_RECEIVED", "请核对物流" )).isNull();
    }

    @ParameterizedTest
    @ValueSource(strings = {"包裹签收但没有收到", "怀疑丢件", "发生重复扣款", "退款一直不到账",
            "请修改收货地址", "帮我取消订单", "申请补偿", "我不同意这个结论"})
    void knownDisputesOrRequestedActionsNeverGainEligibilityFromAModelReason(String message) {
        assertThat(scenario(DecisionReasonCode.DELAY_UNDER_24_HOURS, InvestigationRiskScenario.LOGISTICS_DELAY,
                order(false, false, false, 0, "IN_TRANSIT"), message)).isNull();
    }

    @Test
    void currentPendingActionsCompensationAndLogisticsRiskBlockAnOtherwiseAllowedConclusion() {
        for (var order : List.of(order(false, false, false, 1, "IN_TRANSIT"),
                order(false, true, false, 0, "IN_TRANSIT"), order(false, false, true, 0, "IN_TRANSIT"),
                order(false, false, false, 0, "SUSPECTED_LOST"), order(false, false, false, 0, "STALLED"))) {
            assertThat(scenario(DecisionReasonCode.DELAY_UNDER_24_HOURS, InvestigationRiskScenario.LOGISTICS_DELAY,
                    order, "请核对物流")).isNull();
        }
    }

    private static String scenario(DecisionReasonCode reason, InvestigationRiskScenario risk,
            JdbcAgentInvestigationService.ScopedOrder order, String message) {
        return AutoResolutionPolicy.scenario(conclusion(reason, risk), order, "OTHER", message);
    }

    private static InvestigationConclusion conclusion(DecisionReasonCode reason, InvestigationRiskScenario risk) {
        return new InvestigationConclusion(false, reason, 0, 0, "ORDER-162", List.of(),
                new EvidenceSufficiencyClaim(risk, "evidence-sufficiency-v1", List.of()),
                new CustomerReplyEnvelope("customer-reply-v1", "订单 ORDER-162 的核对结论已给出。",
                        CustomerReplyIntent.NO_COMPENSATION_RESOLUTION, List.of(), false, "ORDER-162"));
    }

    private static JdbcAgentInvestigationService.ScopedOrder order(boolean refunded, boolean compensated,
            boolean duplicate, int pending, String logistics) {
        return order(refunded, compensated, duplicate, pending, logistics, 0);
    }

    private static JdbcAgentInvestigationService.ScopedOrder order(boolean refunded, boolean compensated,
            boolean duplicate, int pending, String logistics, int delayHours) {
        return new JdbcAgentInvestigationService.ScopedOrder("ORDER-162", delayHours, delayHours * 3600L, true, false, refunded,
                compensated, "delay-policy-v1", BigDecimal.TEN, BigDecimal.TEN, pending, BigDecimal.ZERO,
                logistics, "ORDER_RULE_V1", duplicate);
    }
}
