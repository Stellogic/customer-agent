package com.stellogic.customeragent.knowledge;

import java.time.Instant;
import java.util.List;

/** 给客户 Agent 和客服辅助共用的受控资料，非回答或公开引用授权。 */
public record AgentKnowledgeResult(String schema, long indexGeneration, List<Source> results) {
    public AgentKnowledgeResult {
        results = List.copyOf(results);
    }

    public record Source(
            String articleId,
            String version,
            String chunkId,
            String title,
            Instant updatedAt,
            List<String> applicability,
            int startLine,
            int endLine,
            String snippet) {
        public Source {
            applicability = List.copyOf(applicability);
        }
    }
}
