package com.stellogic.customeragent.knowledge;

import java.time.Instant;
import java.util.List;

/**
 * 纯引用校验与字段投影，尚未接线。article 必须由 Spring 从当前权威知识元数据加载，
 * allowedScopes 必须由服务端授权得出，不能来自模型或 HTTP 请求体。
 * 调用方仍负责工单授权、检索质量/代次、引用归属、内容安全和事实冲突校验。
 */
final class KnowledgeCitationProjection {
    private KnowledgeCitationProjection() {}

    record Reference(String articleId, String version, String chunkId) {}

    record CustomerSource(String title, Instant updatedAt) {}

    record SupportSource(
            String articleId,
            String version,
            String chunkId,
            String title,
            Instant updatedAt,
            List<String> applicability,
            int startLine,
            int endLine,
            String snippet) {
        SupportSource {
            applicability = List.copyOf(applicability);
        }
    }

    static CustomerSource customer(KnowledgeArticleDetail article, Reference reference) {
        requireChunk(article, reference, List.of("CUSTOMER_PUBLIC"));
        return new CustomerSource(article.title(), article.updatedAt());
    }

    static SupportSource support(
            KnowledgeArticleDetail article, Reference reference, List<String> allowedScopes) {
        KnowledgeChunkCitation chunk = requireChunk(article, reference, allowedScopes);
        return new SupportSource(
                article.articleId(),
                article.version(),
                chunk.chunkId(),
                article.title(),
                article.updatedAt(),
                matchingScopes(article, chunk, allowedScopes),
                chunk.startLine(),
                chunk.endLine(),
                chunk.content());
    }

    private static KnowledgeChunkCitation requireChunk(
            KnowledgeArticleDetail article, Reference reference, List<String> allowedScopes) {
        if (!article.articleId().equals(reference.articleId())
                || !article.version().equals(reference.version())
                || !article.current()
                || article.publicationStatus() != KnowledgePublicationStatus.PUBLISHED) {
            throw invalidCitation();
        }
        KnowledgeChunkCitation chunk =
                article.chunks().stream()
                        .filter(value -> value.chunkId().equals(reference.chunkId()))
                        .filter(value -> value.articleId().equals(article.articleId()))
                        .filter(value -> value.version().equals(article.version()))
                        .findFirst()
                        .orElseThrow(KnowledgeCitationProjection::invalidCitation);
        if (matchingScopes(article, chunk, allowedScopes).isEmpty()) {
            throw invalidCitation();
        }
        return chunk;
    }

    private static List<String> matchingScopes(
            KnowledgeArticleDetail article,
            KnowledgeChunkCitation chunk,
            List<String> allowedScopes) {
        return chunk.applicability().stream()
                .filter(article.applicability()::contains)
                .filter(allowedScopes::contains)
                .toList();
    }

    private static IllegalArgumentException invalidCitation() {
        return new IllegalArgumentException("知识引用与当前可用条目或授权范围不匹配");
    }
}
