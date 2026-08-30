package com.stellogic.customeragent.knowledge;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** 开发采集与在线判定共用的四特征，输入只能是已完成硬过滤的候选。 */
final class KnowledgeAnswerabilityFeatures {
    static final List<String> NAMES = List.of(
            "dense_max", "dense_margin", "query_term_coverage", "retriever_agreement");

    private KnowledgeAnswerabilityFeatures() {}

    static List<Double> extract(String query, List<KnowledgeRetrievalHit> lexical,
            List<KnowledgeRetrievalHit> dense, List<KnowledgeRetrievalHit> fused) {
        double maximum = dense.isEmpty() ? 0 : dense.getFirst().score();
        double margin = dense.size() < 2 ? 0 : maximum - dense.get(1).score();
        Set<String> queryTerms = new HashSet<>(KnowledgeLexicalAnalyzer.terms(query));
        double coverage = 0;
        if (!queryTerms.isEmpty()) {
            for (var hit : fused) {
                Set<String> common = new HashSet<>(KnowledgeLexicalAnalyzer.terms(hit.snippet()));
                common.retainAll(queryTerms);
                coverage = Math.max(coverage, (double) common.size() / queryTerms.size());
            }
        }
        Set<String> left = new HashSet<>(lexical.stream().limit(5)
                .map(KnowledgeRetrievalHit::chunkId).toList());
        Set<String> right = new HashSet<>(dense.stream().limit(5)
                .map(KnowledgeRetrievalHit::chunkId).toList());
        Set<String> union = new HashSet<>(left);
        union.addAll(right);
        left.retainAll(right);
        double agreement = union.isEmpty() ? 0 : (double) left.size() / union.size();
        return List.of(maximum, margin, coverage, agreement);
    }
}
