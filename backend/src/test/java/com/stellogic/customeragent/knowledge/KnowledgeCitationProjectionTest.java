package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;

/** 合成元数据 fixture；不调用检索、数据库或模型，不代表通过真实质量门。 */
class KnowledgeCitationProjectionTest {
    private static final Instant UPDATED_AT = Instant.parse("2026-08-01T00:00:00Z");
    private static final KnowledgeCitationProjection.Reference REFERENCE =
            new KnowledgeCitationProjection.Reference("delivery-rules", "v1", "chunk-test");

    @Test
    void customerProjectionContainsOnlyCanonicalTitleAndUpdateTime() {
        KnowledgeArticleDetail article = article(List.of("CUSTOMER_PUBLIC"));

        assertThat(KnowledgeCitationProjection.customer(article, REFERENCE))
                .isEqualTo(new KnowledgeCitationProjection.CustomerSource("配送规则（测试）", UPDATED_AT));
        // 字段白名单本身是本测试的行为边界，防止未来意外扩展公开投影。
        assertThat(
                        Arrays.stream(
                                        KnowledgeCitationProjection.CustomerSource.class
                                                .getRecordComponents())
                                .map(java.lang.reflect.RecordComponent::getName))
                .containsExactly("title", "updatedAt");
    }

    @Test
    void supportProjectionUsesCanonicalChunkAndOnlyMatchingScopes() {
        KnowledgeArticleDetail article = article(List.of("SUPPORT", "APPROVER"));

        var source =
                KnowledgeCitationProjection.support(
                        article, REFERENCE, List.of("INTERNAL", "SUPPORT"));

        assertThat(source)
                .isEqualTo(
                        new KnowledgeCitationProjection.SupportSource(
                                "delivery-rules",
                                "v1",
                                "chunk-test",
                                "配送规则（测试）",
                                UPDATED_AT,
                                List.of("SUPPORT"),
                                12,
                                16,
                                "片段正文（测试）"));
        assertThat(
                        Arrays.stream(source.getClass().getRecordComponents())
                                .map(java.lang.reflect.RecordComponent::getName))
                .doesNotContain(
                        "sourceFile", "body", "score", "lexicalCandidates", "vectorCandidates");
    }

    @Test
    void mismatchedArticleVersionAndUnknownChunkAreRejected() {
        KnowledgeArticleDetail article = article(List.of("CUSTOMER_PUBLIC"));
        List<KnowledgeCitationProjection.Reference> wrongReferences =
                List.of(
                        new KnowledgeCitationProjection.Reference(
                                "other-article", "v1", "chunk-test"),
                        new KnowledgeCitationProjection.Reference(
                                "delivery-rules", "old", "chunk-test"),
                        new KnowledgeCitationProjection.Reference(
                                "delivery-rules", "v1", "unknown"));

        for (var reference : wrongReferences) {
            assertThatThrownBy(() -> KnowledgeCitationProjection.customer(article, reference))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    void retiredAndHistoricalVersionsCannotBeUsedForNewReplies() {
        KnowledgeArticleDetail original = article(List.of("CUSTOMER_PUBLIC"));
        for (KnowledgePublicationStatus status : KnowledgePublicationStatus.values()) {
            KnowledgeArticleDetail historical = withVersionState(original, status, false);
            assertThatThrownBy(() -> KnowledgeCitationProjection.customer(historical, REFERENCE))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    void internalKnowledgeCannotBeProjectedToCustomerAndRevokedScopesCannotReadSnippet() {
        KnowledgeArticleDetail internal = article(List.of("INTERNAL"));

        assertThatThrownBy(() -> KnowledgeCitationProjection.customer(internal, REFERENCE))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(
                        () -> KnowledgeCitationProjection.support(internal, REFERENCE, List.of()))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void articleAndChunkMustShareAnAuthorizedScope() {
        KnowledgeArticleDetail original = article(List.of("CUSTOMER_PUBLIC", "SUPPORT"));
        KnowledgeArticleDetail mixed =
                new KnowledgeArticleDetail(
                        original.articleId(),
                        original.title(),
                        original.version(),
                        original.updatedAt(),
                        List.of("CUSTOMER_PUBLIC"),
                        original.publicationStatus(),
                        original.current(),
                        original.sourceFile(),
                        original.contentHash(),
                        original.body(),
                        List.of(),
                        List.of(
                                new KnowledgeChunkCitation(
                                        "chunk-test",
                                        "delivery-rules",
                                        "v1",
                                        "private/test.md",
                                        12,
                                        16,
                                        List.of("SUPPORT"),
                                        "不可见片段（测试）")));

        assertThatThrownBy(() -> KnowledgeCitationProjection.customer(mixed, REFERENCE))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(
                        () ->
                                KnowledgeCitationProjection.support(
                                        mixed, REFERENCE, List.of("SUPPORT")))
                .isInstanceOf(IllegalArgumentException.class);
    }

    private static KnowledgeArticleDetail article(List<String> scopes) {
        return new KnowledgeArticleDetail(
                "delivery-rules",
                "配送规则（测试）",
                "v1",
                UPDATED_AT,
                scopes,
                KnowledgePublicationStatus.PUBLISHED,
                true,
                "private/test.md",
                "a".repeat(64),
                "完整正文（测试）",
                List.of(),
                List.of(
                        new KnowledgeChunkCitation(
                                "chunk-test",
                                "delivery-rules",
                                "v1",
                                "private/test.md",
                                12,
                                16,
                                scopes,
                                "片段正文（测试）")));
    }

    private static KnowledgeArticleDetail withVersionState(
            KnowledgeArticleDetail original, KnowledgePublicationStatus status, boolean current) {
        return new KnowledgeArticleDetail(
                original.articleId(),
                original.title(),
                original.version(),
                original.updatedAt(),
                original.applicability(),
                status,
                current,
                original.sourceFile(),
                original.contentHash(),
                original.body(),
                original.versions(),
                original.chunks());
    }
}
