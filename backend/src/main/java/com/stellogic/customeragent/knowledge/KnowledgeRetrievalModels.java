package com.stellogic.customeragent.knowledge;

import java.util.List;

record KnowledgeRetrievalHit(
        String chunkId,
        String articleId,
        String version,
        String title,
        List<String> applicability,
        String sourceFile,
        int startLine,
        int endLine,
        String snippet,
        double score,
        Double lexicalScore,
        Double vectorScore) {}

record KnowledgeRetrievalPolicy(String id, String calibrationDatasetSha256, double threshold) {}

record KnowledgeRetrievalResponse(
        String schema,
        String query,
        long generation,
        String revision,
        KnowledgeRetrievalPolicy policy,
        List<KnowledgeRetrievalHit> lexicalCandidates,
        List<KnowledgeRetrievalHit> vectorCandidates,
        List<KnowledgeRetrievalHit> results) {}

record KnowledgeDevelopmentResponse(
        String schema,
        long generation,
        String revision,
        List<String> featureNames,
        List<Double> features,
        List<KnowledgeRetrievalHit> lexicalCandidates,
        List<KnowledgeRetrievalHit> vectorCandidates,
        List<KnowledgeRetrievalHit> fusedCandidates) {}

final class KnowledgeRetrievalUnavailableException extends RuntimeException {
    private final String code;

    KnowledgeRetrievalUnavailableException(String code) {
        super("知识混合检索不可用");
        this.code = code;
    }

    String code() {
        return code;
    }
}
