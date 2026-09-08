package com.stellogic.customeragent.investigation;

import java.util.List;

/** 只核对公开回复结构；正文不授予业务执行权限，也不接受语义审查。 */
public final class CustomerReplySafetyPolicy {
    private CustomerReplySafetyPolicy() {}

    public static boolean isValidBody(String body) {
        return body != null && !body.isBlank() && body.length() <= 1000;
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
                        && isValidBody(reply.body())
                        && reply.intent() == expectedIntent
                        && !reply.escalationRequired()
                        && scopedOrderReference.equals(reply.referencedOrder())
                        && scopedEvidence.equals(reply.evidenceRefs());
        return basicShapeValid ? null : "UNSAFE_CUSTOMER_REPLY";
    }
}
