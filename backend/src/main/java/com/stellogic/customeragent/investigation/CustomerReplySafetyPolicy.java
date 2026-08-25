package com.stellogic.customeragent.investigation;

import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class CustomerReplySafetyPolicy {
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

    private CustomerReplySafetyPolicy() {}

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
                        && "customer-reply-v1".equals(reply.schemaVersion())
                        && reply.body() != null
                        && !reply.body().isBlank()
                        && reply.body().length() <= 1000
                        && reply.intent() == expectedIntent
                        && !reply.escalationRequired()
                        && scopedOrderReference.equals(reply.referencedOrder())
                        && scopedEvidence.equals(reply.evidenceRefs())
                        && reply.body().contains(scopedOrderReference);
        if (!basicShapeValid) return "UNSAFE_CUSTOMER_REPLY";
        if (MONEY_PATTERN.matcher(reply.body()).find()) {
            return "CUSTOMER_REPLY_CONTAINS_AMOUNT";
        }
        if (RESPONSE_TIME_PROMISE_PATTERN.matcher(reply.body()).find()) {
            return "CUSTOMER_REPLY_CONTAINS_UNAPPROVED_PROMISE";
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
        if (!hasAuthorizedNarrative(reply.body(), scopedOrderReference, reply.intent())) {
            return "CUSTOMER_REPLY_CONTAINS_UNSUPPORTED_FACT";
        }
        return null;
    }

    private static boolean hasAuthorizedNarrative(
            String body, String orderReference, CustomerReplyIntent intent) {
        String quotedOrder = Pattern.quote(orderReference);
        String pattern;
        if (intent == CustomerReplyIntent.COMPENSATION_REVIEW_PENDING) {
            pattern =
                    "^(?:订单 "
                            + quotedOrder
                            + " 的调查已完成，|我们已核对订单 "
                            + quotedOrder
                            + " 的物流记录。)补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。$";
        } else {
            pattern =
                    "^经核验，订单 "
                            + quotedOrder
                            + " 的本次物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。$";
        }
        return Pattern.matches(pattern, body);
    }

    private static boolean hasOnlyAllowedCompensationLanguage(
            String body, CustomerReplyIntent intent) {
        String remaining = body;
        if (intent == CustomerReplyIntent.COMPENSATION_REVIEW_PENDING) {
            String pending = "补偿建议正在等待人工审批";
            String noExecution = "审批完成前不会执行补偿或退款";
            if (!remaining.contains(pending) || !remaining.contains(noExecution)) return false;
            remaining = remaining.replace(pending, "").replace(noExecution, "");
        } else {
            String ineligible = "当前不符合补偿条件";
            if (!remaining.contains(ineligible)) return false;
            remaining = remaining.replace(ineligible, "");
        }
        return !remaining.contains("补偿") && !remaining.contains("退款");
    }
}
