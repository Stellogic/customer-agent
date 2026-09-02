package com.stellogic.customeragent.ticket;

import java.time.Instant;
import java.util.List;

/** 公开投影只保存已接受回复的状态和友好来源元数据，不包含模型引用或检索回执。 */
public record CustomerKnowledgeProjection(String status, List<Source> sources) {
    public CustomerKnowledgeProjection {
        sources = List.copyOf(sources);
    }

    public record Source(String title, Instant updatedAt) {}
}
