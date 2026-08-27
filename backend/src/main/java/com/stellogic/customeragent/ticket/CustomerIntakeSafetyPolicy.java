package com.stellogic.customeragent.ticket;

import java.util.List;

final class CustomerIntakeSafetyPolicy {
    private static final List<String> EXPLICIT_CONFIRMATIONS =
            List.of("可以", "确认", "是的", "对", "没错", "就按这个处理", "可以就按这个处理", "确认提交");

    private CustomerIntakeSafetyPolicy() {}

    static boolean isExplicitConfirmation(String message) {
        String normalized = message.toLowerCase().replaceAll("[\\s。！!，,]", "");
        return EXPLICIT_CONFIRMATIONS.contains(normalized);
    }

    static String assistantMessage(IntakeUnderstanding understanding) {
        String orderReference = understanding.candidateOrderReference();
        if ("READY_TO_CONFIRM".equals(understanding.status())) {
            return "我理解为订单 " + orderReference + " 的物流延迟问题。请确认是否正确，或直接告诉我需要修改的地方。";
        }
        if (orderReference != null) {
            return "你说的是不是订单 " + orderReference + " 的物流延迟问题？也可以直接纠正我的理解。";
        }
        return "你说的是不是某一笔订单的物流问题？请补充订单线索。";
    }
}
