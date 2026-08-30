package com.stellogic.customeragent.knowledge;

import java.time.Instant;
import java.util.List;

record KnowledgeArticleDocument(
        String articleId,
        String title,
        String version,
        Instant updatedAt,
        List<String> applicability,
        KnowledgePublicationStatus publicationStatus,
        boolean current,
        String sourceFile,
        String contentHash,
        String body,
        List<KnowledgeChunkDocument> chunks) {
    KnowledgeArticleDocument {
        applicability = List.copyOf(applicability);
        chunks = List.copyOf(chunks);
    }
}

record KnowledgeChunkDocument(
        String chunkId,
        String articleId,
        String version,
        int ordinal,
        String sourceFile,
        int startLine,
        int endLine,
        List<String> applicability,
        String content) {
    KnowledgeChunkDocument {
        applicability = List.copyOf(applicability);
    }
}

record KnowledgeIndexState(
        KnowledgeIndexStatus status,
        long generation,
        String sourceDigest,
        Instant indexedAt,
        Instant updatedAt,
        int articleCount,
        int chunkCount,
        String failureCode,
        String failureMessage) {}

record KnowledgeSearchResult(
        String chunkId,
        String articleId,
        String version,
        String title,
        Instant updatedAt,
        List<String> applicability,
        String sourceFile,
        int startLine,
        int endLine,
        String snippet,
        String matchType,
        double lexicalScore) {
    KnowledgeSearchResult {
        applicability = List.copyOf(applicability);
    }
}

record KnowledgeArticleVersion(
        String articleId,
        String title,
        String version,
        Instant updatedAt,
        List<String> applicability,
        KnowledgePublicationStatus publicationStatus,
        boolean current,
        String sourceFile) {
    KnowledgeArticleVersion {
        applicability = List.copyOf(applicability);
    }
}

record KnowledgeChunkCitation(
        String chunkId,
        String articleId,
        String version,
        String sourceFile,
        int startLine,
        int endLine,
        List<String> applicability,
        String content) {
    KnowledgeChunkCitation {
        applicability = List.copyOf(applicability);
    }
}

record KnowledgeArticleDetail(
        String articleId,
        String title,
        String version,
        Instant updatedAt,
        List<String> applicability,
        KnowledgePublicationStatus publicationStatus,
        boolean current,
        String sourceFile,
        String contentHash,
        String body,
        List<KnowledgeArticleVersion> versions,
        List<KnowledgeChunkCitation> chunks) {
    KnowledgeArticleDetail {
        applicability = List.copyOf(applicability);
        versions = List.copyOf(versions);
        chunks = List.copyOf(chunks);
    }
}

record KnowledgeCatalogResponse(
        String view,
        String schema,
        KnowledgeIndexState index,
        String query,
        List<KnowledgeSearchResult> results) {
    KnowledgeCatalogResponse {
        results = List.copyOf(results);
    }
}

record KnowledgeArticleResponse(
        String view, String schema, KnowledgeIndexState index, KnowledgeArticleDetail article) {}

enum KnowledgePublicationStatus {
    DRAFT,
    PUBLISHED,
    RETIRED
}

enum KnowledgeIndexStatus {
    EMPTY,
    READY,
    FAILED
}
