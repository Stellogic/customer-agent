package com.stellogic.customeragent.knowledge;

public interface KnowledgeCatalogService {
    KnowledgeCatalogResponse search(String principalId, String query, int limit);

    KnowledgeArticleResponse article(String principalId, String articleId, String version);

    KnowledgeIndexState index(String principalId);
}
