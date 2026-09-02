package com.stellogic.customeragent.investigation;

import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class CustomerReplySafetyPolicy {
    static boolean unsafeKnowledgeBody(String body) {
        return MONEY_PATTERN.matcher(body).find()
                || RESPONSE_TIME_PROMISE_PATTERN.matcher(body).find()
                || ORDER_REFERENCE_PATTERN.matcher(body).find()
                || SENSITIVE_LEAK_PATTERN.matcher(body).find()
                || PERSON_NAME_CLAIM_PATTERN.matcher(body).find()
                || PREMATURE_RESOLUTION_PATTERN.matcher(body).find()
                || DIRECT_COMPENSATION_PROMISE_PATTERN.matcher(body).find()
                || DIRECT_PAYMENT_PROMISE_PATTERN.matcher(body).find()
                || CUSTOMER_FACT_ASSERTION_PATTERN.matcher(body).find()
                || Pattern.compile("(?i)(https?://|[a-z]:\\\\|sourceFile|chunkId|vectorScore)")
                        .matcher(body)
                        .find();
    }

    private static final String NUMBER = "(?:\\d+(?:\\.\\d+)?|[零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬]+)";
    private static final Pattern MONEY_PATTERN =
            Pattern.compile(
                    "(?i)(?:[¥￥$]|USD|CNY|RMB)\\s*"
                            + NUMBER
                            + "|"
                            + NUMBER
                            + "\\s*(?:元|块钱|美元|人民币|USD|CNY|RMB)");
    private static final Pattern RESPONSE_TIME_PROMISE_PATTERN =
            Pattern.compile(NUMBER + "\\s*(?:秒|分钟|小时|天|工作日)(?:之内|以内|内).{0,8}(?:回复|联系|处理|解决)");
    private static final Pattern ORDER_REFERENCE_PATTERN =
            Pattern.compile("ORDER-[A-Z0-9-]+", Pattern.CASE_INSENSITIVE);
    private static final Pattern SENSITIVE_LEAK_PATTERN =
            Pattern.compile(
                    "(?i)(系统提示词|prompt|reasoning|checkpoint|thread_id|api[_\\s-]?key|bearer\\s+[a-z0-9._-]+)");
    private static final Pattern PERSON_NAME_CLAIM_PATTERN =
            Pattern.compile("(?:由|被)\\s*[\\u4e00-\\u9fff]{2,4}\\s*签收");
    private static final Pattern PREMATURE_RESOLUTION_PATTERN =
            Pattern.compile(
                    "工单.{0,5}已.{0,3}(解决|关闭)|关闭等待期|(?:ticket|case).{0,12}(?:resolved|closed)",
                    Pattern.CASE_INSENSITIVE);
    private static final Pattern DIRECT_COMPENSATION_PROMISE_PATTERN =
            Pattern.compile(
                    "(?<!不)(?:已|已经|将|会|承诺|同意|可以|可).{0,10}(?:补偿|退款)"
                            + "|(?:补偿|退款).{0,10}(?:已完成|将执行|已发放)");
    private static final Pattern DIRECT_PAYMENT_PROMISE_PATTERN =
            Pattern.compile("(?:已|已经|将).{0,10}(?:支付|到账)");
    private static final Pattern CUSTOMER_FACT_ASSERTION_PATTERN =
            Pattern.compile(
                    "(?:您的|本单|这笔|该笔|当前订单|当前包裹|该订单|该包裹|订单|包裹).{0,12}(?:已|已经|目前|当前|处于|存在|为).{0,8}(?:签收|丢失|延迟|停滞|配送|支付|退款|补偿|取消|到账)");

    private static final Map<InvestigationRiskScenario, Set<String>> SCENARIO_CLAIM_TOKENS =
            Map.of(
                    InvestigationRiskScenario.LOGISTICS_DELAY,
                    Set.of("物流", "延迟", "调查", "核验", "核对", "记录", "小时", "不足", "未达到", "存在", "出现"),
                    InvestigationRiskScenario.LOGISTICS_STALLED,
                    Set.of("物流", "停滞", "长时间", "无更新", "调查", "核验", "核对"),
                    InvestigationRiskScenario.PACKAGE_SIGNED_NOT_RECEIVED,
                    Set.of("物流", "签收", "未收到", "调查", "核验", "核对", "状态"),
                    InvestigationRiskScenario.PACKAGE_SUSPECTED_LOST,
                    Set.of("物流", "疑似", "丢件", "丢失", "调查", "核验", "核对"),
                    InvestigationRiskScenario.DUPLICATE_CHARGE,
                    Set.of("支付", "重复", "扣款", "调查", "核验", "核对", "记录"),
                    InvestigationRiskScenario.REFUND_STATUS,
                    Set.of("退款", "支付", "状态", "调查", "核验", "核对"),
                    InvestigationRiskScenario.ORDER_ADDRESS_OR_CANCEL_RULE,
                    Set.of("订单", "地址", "取消", "规则", "说明", "调查", "核验", "核对"),
                    InvestigationRiskScenario.OTHER_GENERAL,
                    Set.of("问题", "说明", "调查", "核验", "核对", "记录"));

    private static final Map<String, Set<InvestigationRiskScenario>> CLAIM_REQUIRING_SCENARIO =
            Map.of(
                    "签收", Set.of(InvestigationRiskScenario.PACKAGE_SIGNED_NOT_RECEIVED),
                    "未收到", Set.of(InvestigationRiskScenario.PACKAGE_SIGNED_NOT_RECEIVED),
                    "丢件", Set.of(InvestigationRiskScenario.PACKAGE_SUSPECTED_LOST),
                    "丢失", Set.of(InvestigationRiskScenario.PACKAGE_SUSPECTED_LOST),
                    "停滞", Set.of(InvestigationRiskScenario.LOGISTICS_STALLED),
                    "重复扣款", Set.of(InvestigationRiskScenario.DUPLICATE_CHARGE),
                    "退款",
                            Set.of(
                                    InvestigationRiskScenario.REFUND_STATUS,
                                    InvestigationRiskScenario.DUPLICATE_CHARGE,
                                    InvestigationRiskScenario.LOGISTICS_DELAY,
                                    InvestigationRiskScenario.PACKAGE_SIGNED_NOT_RECEIVED,
                                    InvestigationRiskScenario.PACKAGE_SUSPECTED_LOST,
                                    InvestigationRiskScenario.LOGISTICS_STALLED));

    private CustomerReplySafetyPolicy() {}

    public static boolean isAuthorizedBodyPrefix(
            String body, String scopedOrderReference, boolean complete) {
        if (body == null || body.isEmpty() || scopedOrderReference == null) return false;
        if (body.length() > 1000) return false;
        if (MONEY_PATTERN.matcher(body).find()) return false;
        if (RESPONSE_TIME_PROMISE_PATTERN.matcher(body).find()) return false;
        if (SENSITIVE_LEAK_PATTERN.matcher(body).find()) return false;
        if (PERSON_NAME_CLAIM_PATTERN.matcher(body).find()) return false;
        if (PREMATURE_RESOLUTION_PATTERN.matcher(body).find()) return false;
        Matcher referencedOrders = ORDER_REFERENCE_PATTERN.matcher(body);
        while (referencedOrders.find()) {
            if (!scopedOrderReference.equalsIgnoreCase(referencedOrders.group())) {
                return false;
            }
        }
        if (complete) {
            if (!hasOnlyAllowedCompensationLanguage(
                    body, inferIntentFromCompensationLanguage(body))) {
                return false;
            }
        }
        return true;
    }

    static String rejectionReason(
            InvestigationConclusion conclusion,
            String scopedOrderReference,
            List<String> scopedEvidence) {
        CustomerReplyEnvelope reply = conclusion.customerReply();
        CustomerReplyIntent expectedIntent =
                conclusion.compensationRequired()
                        ? CustomerReplyIntent.COMPENSATION_REVIEW_PENDING
                        : CustomerReplyIntent.NO_COMPENSATION_RESOLUTION;
        boolean basicShapeValid =
                reply != null
                        && (("customer-reply-v1".equals(reply.schemaVersion())
                                        && reply.knowledge() == null)
                                || ("customer-reply-v2".equals(reply.schemaVersion())
                                        && reply.knowledge() != null))
                        && reply.body() != null
                        && !reply.body().isBlank()
                        && reply.body().length() <= 1000
                        && reply.intent() == expectedIntent
                        && !reply.escalationRequired()
                        && scopedOrderReference.equals(reply.referencedOrder())
                        && scopedEvidence.equals(reply.evidenceRefs());
        if (!basicShapeValid) return "UNSAFE_CUSTOMER_REPLY";
        if (PREMATURE_RESOLUTION_PATTERN.matcher(reply.body()).find()) {
            return "CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE";
        }
        if (MONEY_PATTERN.matcher(reply.body()).find()) {
            return "CUSTOMER_REPLY_CONTAINS_AMOUNT";
        }
        if (RESPONSE_TIME_PROMISE_PATTERN.matcher(reply.body()).find()) {
            return "CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE";
        }
        if (SENSITIVE_LEAK_PATTERN.matcher(reply.body()).find()) {
            return "CUSTOMER_REPLY_CONTAINS_SENSITIVE_CONTENT";
        }
        Matcher referencedOrders = ORDER_REFERENCE_PATTERN.matcher(reply.body());
        while (referencedOrders.find()) {
            if (!scopedOrderReference.equalsIgnoreCase(referencedOrders.group())) {
                return "CUSTOMER_REPLY_ORDER_OUTSIDE_SCOPE";
            }
        }
        if (!hasOnlyAllowedCompensationLanguage(reply.body(), reply.intent())) {
            return "CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE";
        }
        if (!hasGroundedNarrative(reply.body(), conclusion)) {
            return "CUSTOMER_REPLY_CONTAINS_UNSUPPORTED_FACT";
        }
        return null;
    }

    private static boolean hasGroundedNarrative(String body, InvestigationConclusion conclusion) {
        if (PERSON_NAME_CLAIM_PATTERN.matcher(body).find()) return false;
        EvidenceSufficiencyClaim sufficiency = conclusion.sufficiency();
        if (sufficiency == null || sufficiency.riskScenario() == null) return false;
        InvestigationRiskScenario scenario = sufficiency.riskScenario();
        for (Map.Entry<String, Set<InvestigationRiskScenario>> claim :
                CLAIM_REQUIRING_SCENARIO.entrySet()) {
            if (body.contains(claim.getKey()) && !claim.getValue().contains(scenario)) {
                // Compensation-pending replies may mention 退款 only inside the approved no-execution
                // disclaimer; strip that before judging logistics-delay narratives.
                if ("退款".equals(claim.getKey())
                        && body.contains("审批完成前不会执行补偿或退款")
                        && countOccurrences(body, "退款") == 1) {
                    continue;
                }
                return false;
            }
        }
        Set<String> authorized =
                new HashSet<>(SCENARIO_CLAIM_TOKENS.getOrDefault(scenario, Set.of()));
        authorized.add(conclusion.orderReference());
        if (conclusion.delayHours() > 0) {
            authorized.add(Integer.toString(conclusion.delayHours()));
        }
        if (conclusion.delaySeconds() > 0) {
            authorized.add(Long.toString(conclusion.delaySeconds()));
        }
        // Natural language is allowed; reject only when a concrete numeric delay claim disagrees
        // with Spring authority.
        Matcher numericDelay = Pattern.compile("(\\d+)\\s*小时").matcher(body);
        while (numericDelay.find()) {
            int claimedHours = Integer.parseInt(numericDelay.group(1));
            boolean matchesAuthority = claimedHours == conclusion.delayHours();
            boolean mentionsThreshold = conclusion.delayHours() < 24 && claimedHours == 24;
            if (!matchesAuthority && !mentionsThreshold) {
                return false;
            }
        }
        // Natural language wrappers are allowed; person-linked delivery claims and
        // scenario-mismatched tokens are rejected above.
        return !authorized.isEmpty();
    }

    private static int countOccurrences(String body, String token) {
        int count = 0;
        int from = 0;
        while (true) {
            int at = body.indexOf(token, from);
            if (at < 0) return count;
            count++;
            from = at + token.length();
        }
    }

    private static CustomerReplyIntent inferIntentFromCompensationLanguage(String body) {
        if (body.contains("补偿建议正在等待人工审批")) {
            return CustomerReplyIntent.COMPENSATION_REVIEW_PENDING;
        }
        return CustomerReplyIntent.NO_COMPENSATION_RESOLUTION;
    }

    private static boolean hasOnlyAllowedCompensationLanguage(
            String body, CustomerReplyIntent intent) {
        String remaining = body;
        if (intent == CustomerReplyIntent.COMPENSATION_REVIEW_PENDING) {
            String pending = "补偿建议正在等待人工审批";
            String noExecution = "审批完成前不会执行补偿或退款";
            if (!remaining.contains(pending) || !remaining.contains(noExecution)) return false;
            remaining = remaining.replace(pending, "").replace(noExecution, "");
            return !remaining.contains("补偿") && !remaining.contains("退款");
        }
        if (intent == CustomerReplyIntent.NO_COMPENSATION_RESOLUTION) {
            // Intent and Spring facts carry the decision. Keep natural denial wording while
            // rejecting concrete compensation/refund actions and positive promises.
            return !DIRECT_COMPENSATION_PROMISE_PATTERN.matcher(remaining).find();
        }
        return false;
    }
}
