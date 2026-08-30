package com.stellogic.customeragent.investigation;

import java.time.Duration;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Spring-owned whitelist; neither issue kind nor a model risk score grants eligibility. */
final class AutoResolutionPolicy {
    static final String VERSION = "auto-resolution-v1";
    static final Duration WAIT = Duration.ofMinutes(5);
    private static final Map<DecisionReasonCode, String> SCENARIOS = Map.of(
            DecisionReasonCode.DELAY_UNDER_24_HOURS, "AUTHORITATIVE_STATUS_EXPLANATION",
            DecisionReasonCode.ORDER_RULE_EXPLAINED, "RULE_EXPLANATION",
            DecisionReasonCode.REFUND_STATUS_EXPLAINED, "COMPLETED_NON_COMPENSATION_CHECK");
    // Denial signals supplement authoritative facts, and never grant eligibility.
    private static final Pattern DISPUTE_OR_ACTION = Pattern.compile(
            "签收.{0,8}(没|未|不).{0,4}收到|丢件|丢失|重复.{0,4}(扣款|收费)|退款.{0,8}(异常|没到|未到|不到账)|"
                    + "(请|帮我|我要|要求|申请)(立即|现在|直接|尽快|马上)?(给我|帮我)?"
                    + "(改地址|修改(收货)?地址|更改地址|取消订单|退款|补偿)|"
                    + "(?m)^(修改地址|更改地址|取消订单)[。！!]?\\s*$|赔偿|补偿|不同意|有争议|"
                    + "signed.{0,15}not received|lost package|duplicate charge|change.{0,10}address|cancel.{0,10}order",
            Pattern.CASE_INSENSITIVE);

    private AutoResolutionPolicy() {}

    static String scenario(InvestigationConclusion conclusion,
            JdbcAgentInvestigationService.ScopedOrder order, String issueKind, String customerText) {
        String scenario = SCENARIOS.get(conclusion.reasonCode());
        if (scenario == null || conclusion.compensationRequired()
                || conclusion.customerReply().escalationRequired()
                || Set.of("PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE").contains(issueKind)
                || DISPUTE_OR_ACTION.matcher(customerText).find()
                || !order.paid() || order.cancelled() || order.existingCompensation()
                || order.duplicateChargeSuspected() || order.pendingActionCount() != 0
                || order.activeReservationAmount().signum() != 0
                || Set.of("STALLED", "SUSPECTED_LOST").contains(order.logisticsStatus())) return null;
        return switch (conclusion.reasonCode()) {
            case DELAY_UNDER_24_HOURS ->
                    conclusion.sufficiency().riskScenario() == InvestigationRiskScenario.LOGISTICS_DELAY
                            && order.delaySeconds() < Duration.ofHours(24).toSeconds()
                            && !order.fullyRefunded() ? scenario : null;
            case ORDER_RULE_EXPLAINED ->
                    conclusion.sufficiency().riskScenario() == InvestigationRiskScenario.ORDER_ADDRESS_OR_CANCEL_RULE
                            && !order.fullyRefunded() ? scenario : null;
            case REFUND_STATUS_EXPLAINED ->
                    conclusion.sufficiency().riskScenario() == InvestigationRiskScenario.REFUND_STATUS
                            && order.fullyRefunded() ? scenario : null;
            default -> null;
        };
    }
}
