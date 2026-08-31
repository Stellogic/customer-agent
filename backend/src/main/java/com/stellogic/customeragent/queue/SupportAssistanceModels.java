package com.stellogic.customeragent.queue;

import java.util.List;
import java.util.UUID;

enum SupportAssistanceKind { summary, knowledge, policy, draft }

record SupportAssistanceRequest(UUID assignmentId, UUID requestId, SupportAssistanceKind kind, String query) {}

record SupportAssistanceReceipt(UUID ticketId, UUID assignmentId, UUID requestId,
        SupportAssistanceKind kind, String status, String resultJson, boolean execute,
        SupportAssistanceContext.Snapshot input) {}

/** 工作者只返回引用选择，不让模型生成 title/version/权限等 metadata。 */
record SupportAssistanceAnswer(String decision, String text, String followUp,
        List<Quote> citations) {
    record Quote(String chunkId, String quote) {}
}

final class SupportAssistanceConflictException extends RuntimeException {}
