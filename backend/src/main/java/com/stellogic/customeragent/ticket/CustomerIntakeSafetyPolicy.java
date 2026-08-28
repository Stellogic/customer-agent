package com.stellogic.customeragent.ticket;

import java.util.List;
import java.util.regex.Pattern;

final class CustomerIntakeSafetyPolicy {
    private static final List<String> EXPLICIT_CONFIRMATIONS =
            List.of("可以", "确认", "是的", "对", "没错", "就按这个处理", "可以就按这个处理", "确认提交");
    private static final List<String> HUMAN_ASSISTANCE_PHRASES =
            List.of("协助受理", "人工受理", "转人工", "找人工", "人工处理", "人工帮助", "人工帮我受理");
    private static final Pattern NEGATED_HUMAN_ASSISTANCE =
            Pattern.compile(
                    "(?:不要|不用|不想|别|无需|不需要|禁止|拒绝)(?:再|让)?"
                            + "(?:(?:客服)?(?:人工帮我受理|协助受理|人工受理|转人工|找人工|人工处理|人工帮助))+");
    private static final List<String> NO_EXISTING_TICKET =
            List.of("没工单", "没有工单", "还没工单", "尚无工单", "未建工单", "未创建工单", "没有创建工单");

    private CustomerIntakeSafetyPolicy() {}

    static boolean isExplicitConfirmation(String message) {
        String normalized = message.toLowerCase().replaceAll("[\\s。！!，,]", "");
        return EXPLICIT_CONFIRMATIONS.contains(normalized);
    }

    static boolean isHumanAssistanceRequest(String message) {
        String normalized = message.toLowerCase().replaceAll("[\\s。！!，,]", "");
        if (normalized.contains("工单")
                && NO_EXISTING_TICKET.stream().noneMatch(normalized::contains)) return false;
        String affirmativeOnly = NEGATED_HUMAN_ASSISTANCE.matcher(normalized).replaceAll("");
        return HUMAN_ASSISTANCE_PHRASES.stream().anyMatch(affirmativeOnly::contains);
    }

    static String assistantMessage(IntakeUnderstanding understanding) {
        String orderReference = understanding.candidateOrderReference();
        if ("READY_TO_CONFIRM".equals(understanding.status())) {
            int count = understanding.issues().size();
            return "我理解为订单 "
                    + orderReference
                    + " 有 "
                    + count
                    + " 个独立问题。请确认；确认后将创建 "
                    + count
                    + " 张工单，也可以直接告诉我需要修改的地方。";
        }
        if (!understanding.pendingIssueKinds().isEmpty()) {
            return clarificationMessage(understanding.pendingIssueKinds().getFirst());
        }
        if (orderReference != null) {
            return "你说的是不是订单 " + orderReference + " 的物流延迟问题？也可以直接纠正我的理解。";
        }
        return "你说的是不是某一笔订单的物流问题？请补充订单线索。";
    }

    private static String clarificationMessage(String kind) {
        return switch (kind) {
            case "DUPLICATE_CHARGE" -> "你提到疑似重复扣款，请确认是否确实发生了两次扣款。";
            case "PACKAGE_NOT_RECEIVED" -> "请确认包裹是否至今仍未收到。";
            case "LOGISTICS_DELAY" -> "请确认物流是否已经超过预期时间仍无进展。";
            default -> throw new IntakeAgentUnavailableException();
        };
    }
}
