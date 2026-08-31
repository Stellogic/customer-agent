package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.Test;

class KnowledgeAnswerabilityFeaturesTest {
    @Test
    void combinesDenseConfidenceLexicalCoverageAndIndependentRetrieverAgreement() {
        var first = hit("a", "alpha beta", 0.75);
        var second = hit("b", "gamma", 0.5);
        var lexicalOnly = hit("c", "alpha", 1.0);
        var actual =
                KnowledgeAnswerabilityFeatures.extract(
                        "alpha beta gamma",
                        List.of(first, lexicalOnly),
                        List.of(first, second),
                        List.of(first, second, lexicalOnly));
        assertThat(actual).containsExactly(0.75, 0.25, 2.0 / 3.0, 1.0 / 3.0);
    }

    @Test
    void emptyCandidatesNeverInventEvidenceOrDivideByZero() {
        assertThat(KnowledgeAnswerabilityFeatures.extract("!!!", List.of(), List.of(), List.of()))
                .containsExactly(0.0, 0.0, 0.0, 0.0);
    }

    private static KnowledgeRetrievalHit hit(String id, String text, double score) {
        return new KnowledgeRetrievalHit(
                id,
                "example",
                "development-v1",
                "示例",
                List.of("INTERNAL"),
                "knowledge/example.md",
                1,
                1,
                text,
                score,
                null,
                score);
    }
}
