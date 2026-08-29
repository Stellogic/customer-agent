package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.Resource;

class KnowledgeMarkdownParserTest {
    private final KnowledgeMarkdownParser parser = new KnowledgeMarkdownParser();

    @Test
    void parsesRequiredMetadataAndStableChunksFromShippedCurrentArticle() throws Exception {
        KnowledgeArticleDocument article =
                parser.parse(new ClassPathResource("knowledge/logistics-delay-v2.md"));

        assertThat(article.articleId()).isEqualTo("logistics-delay");
        assertThat(article.title()).isEqualTo("物流延迟处理说明");
        assertThat(article.version()).isEqualTo("v2");
        assertThat(article.updatedAt()).isEqualTo(Instant.parse("2026-08-28T00:00:00Z"));
        assertThat(article.applicability()).containsExactly("INTERNAL", "SUPPORT");
        assertThat(article.publicationStatus()).isEqualTo(KnowledgePublicationStatus.PUBLISHED);
        assertThat(article.current()).isTrue();
        assertThat(article.sourceFile()).isEqualTo("knowledge/logistics-delay-v2.md");
        assertThat(article.body()).contains("物流节点超过承诺时间没有更新");
        assertThat(article.chunks()).isNotEmpty();
        KnowledgeChunkDocument first = article.chunks().getFirst();
        assertThat(first.chunkId()).startsWith("chunk-");
        assertThat(first.articleId()).isEqualTo("logistics-delay");
        assertThat(first.version()).isEqualTo("v2");
        assertThat(first.sourceFile()).isEqualTo("knowledge/logistics-delay-v2.md");
        assertThat(first.startLine()).isGreaterThan(0);
        assertThat(first.endLine()).isGreaterThanOrEqualTo(first.startLine());
    }

    @Test
    void retiredVersionRemainsParsableForAuditAndIsNotCurrent() throws Exception {
        KnowledgeArticleDocument article =
                parser.parse(new ClassPathResource("knowledge/logistics-delay-v1.md"));

        assertThat(article.articleId()).isEqualTo("logistics-delay");
        assertThat(article.version()).isEqualTo("v1");
        assertThat(article.publicationStatus()).isEqualTo(KnowledgePublicationStatus.RETIRED);
        assertThat(article.current()).isFalse();
        assertThat(article.body()).contains("旧版本规则只用于审计历史回复");
    }

    @Test
    void sameMarkdownProducesIdenticalChunkIds() throws Exception {
        Resource source = markdown("stable-chunk.md", validArticle());
        List<String> first =
                parser.parse(source).chunks().stream().map(KnowledgeChunkDocument::chunkId).toList();
        List<String> second =
                parser.parse(source).chunks().stream().map(KnowledgeChunkDocument::chunkId).toList();

        assertThat(first).isNotEmpty().isEqualTo(second);
    }

    @Test
    void rejectsMissingDuplicateAndInvalidMetadata() {
        assertThatThrownBy(
                        () ->
                                parser.parse(
                                        markdown(
                                                "missing-id.md",
                                                """
                                                ---
                                                title: 缺少标识
                                                version: v1
                                                updated_at: 2026-08-28T00:00:00Z
                                                applicability: [INTERNAL]
                                                status: PUBLISHED
                                                current: true
                                                ---
                                                正文
                                                """)))
                .isInstanceOf(KnowledgeCatalogValidationException.class)
                .hasMessageContaining("缺少必需元数据")
                .hasMessageContaining("id");

        assertThatThrownBy(
                        () ->
                                parser.parse(
                                        markdown(
                                                "duplicate-title.md",
                                                """
                                                ---
                                                id: duplicate-title
                                                title: 第一标题
                                                title: 第二标题
                                                version: v1
                                                updated_at: 2026-08-28T00:00:00Z
                                                applicability: [INTERNAL]
                                                status: PUBLISHED
                                                current: true
                                                ---
                                                正文
                                                """)))
                .isInstanceOf(KnowledgeCatalogValidationException.class)
                .hasMessageContaining("重复元数据字段: title");

        assertThatThrownBy(
                        () ->
                                parser.parse(
                                        markdown(
                                                "current-draft.md",
                                                """
                                                ---
                                                id: current-draft
                                                title: 草稿不能作为当前版本
                                                version: v1
                                                updated_at: 2026-08-28T00:00:00Z
                                                applicability: [INTERNAL]
                                                status: DRAFT
                                                current: true
                                                ---
                                                正文
                                                """)))
                .isInstanceOf(KnowledgeCatalogValidationException.class)
                .hasMessageContaining("current 条目必须是 PUBLISHED");
    }

    @Test
    void rejectsUnsupportedApplicabilityAndEmptyBody() {
        assertThatThrownBy(
                        () ->
                                parser.parse(
                                        markdown(
                                                "bad-scope.md",
                                                """
                                                ---
                                                id: bad-scope
                                                title: 错误范围
                                                version: v1
                                                updated_at: 2026-08-28T00:00:00Z
                                                applicability: [EVERYONE]
                                                status: PUBLISHED
                                                current: true
                                                ---
                                                正文
                                                """)))
                .isInstanceOf(KnowledgeCatalogValidationException.class)
                .hasMessageContaining("不支持的适用范围: EVERYONE");

        assertThatThrownBy(
                        () ->
                                parser.parse(
                                        markdown(
                                                "empty-body.md",
                                                """
                                                ---
                                                id: empty-body
                                                title: 空正文
                                                version: v1
                                                updated_at: 2026-08-28T00:00:00Z
                                                applicability: [INTERNAL]
                                                status: PUBLISHED
                                                current: true
                                                ---

                                                """)))
                .isInstanceOf(KnowledgeCatalogValidationException.class)
                .hasMessageContaining("正文不能为空");
    }

    private static String validArticle() {
        return """
                ---
                id: stable-chunk
                title: 稳定分段样例
                version: v1
                updated_at: 2026-08-28T00:00:00Z
                applicability: [INTERNAL, SUPPORT]
                status: PUBLISHED
                current: true
                ---
                第一段说明物流延迟处理原则。
                """;
    }

    private static Resource markdown(String filename, String content) {
        return new ByteArrayResource(content.getBytes(StandardCharsets.UTF_8)) {
            @Override
            public String getFilename() {
                return filename;
            }
        };
    }
}
