package com.stellogic.customeragent.knowledge;

import java.io.IOException;
import java.time.Clock;
import java.time.Instant;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.sql.DataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Component
final class KnowledgeCatalogIndexer {
    private static final Logger LOG = LoggerFactory.getLogger(KnowledgeCatalogIndexer.class);
    private static final long ADVISORY_LOCK_KEY = 16620260829L;

    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final Clock clock;
    private final ResourcePatternResolver resources;
    private final KnowledgeMarkdownParser parser;
    private final String resourcePattern;
    private final boolean migrateOnly;

    KnowledgeCatalogIndexer(
            DataSource dataSource,
            PlatformTransactionManager transactionManager,
            Clock clock,
            @Value("${baseline.knowledge.resource-pattern:classpath*:/knowledge/*.md}")
                    String resourcePattern,
            @Value("${baseline.migrate-only:false}") boolean migrateOnly) {
        this.jdbc = new JdbcTemplate(dataSource);
        this.transactions = new TransactionTemplate(transactionManager);
        this.clock = clock;
        this.resources = new PathMatchingResourcePatternResolver();
        this.parser = new KnowledgeMarkdownParser();
        this.resourcePattern = resourcePattern;
        this.migrateOnly = migrateOnly;
    }

    @EventListener(ApplicationReadyEvent.class)
    void rebuildOnStartup() {
        if (!migrateOnly) rebuild();
    }

    synchronized KnowledgeIndexState rebuild() {
        List<KnowledgeArticleDocument> articles;
        try {
            articles = loadAndValidate();
        } catch (IOException | KnowledgeCatalogValidationException exception) {
            return markFailure(failureCode(exception), exception.getMessage());
        }

        try {
            return replaceIndex(articles);
        } catch (RuntimeException exception) {
            LOG.warn("knowledge index rebuild failed code=INDEX_REBUILD_FAILED");
            return markFailure("INDEX_REBUILD_FAILED", "知识索引重建失败，请检查数据库与索引状态");
        }
    }

    private List<KnowledgeArticleDocument> loadAndValidate()
            throws IOException, KnowledgeCatalogValidationException {
        Resource[] resolved = resources.getResources(resourcePattern);
        if (resolved.length == 0) {
            throw new KnowledgeCatalogValidationException(
                    "EMPTY_KNOWLEDGE_CATALOG", "知识目录没有找到 Markdown 条目");
        }
        Arrays.sort(resolved, Comparator.comparing(this::stableSourceFile));
        List<KnowledgeArticleDocument> articles =
                Arrays.stream(resolved).map(this::parse).toList();

        Set<String> sourceFiles = new HashSet<>();
        Set<String> articleVersions = new HashSet<>();
        Map<String, Integer> currentByArticle = new HashMap<>();
        Set<String> chunkIds = new HashSet<>();
        for (KnowledgeArticleDocument article : articles) {
            if (!sourceFiles.add(article.sourceFile())) {
                throw new KnowledgeCatalogValidationException(
                        "DUPLICATE_KNOWLEDGE_SOURCE", "重复知识源: " + article.sourceFile());
            }
            String articleVersion = article.articleId() + "\u0000" + article.version();
            if (!articleVersions.add(articleVersion)) {
                throw new KnowledgeCatalogValidationException(
                        "DUPLICATE_KNOWLEDGE_VERSION",
                        "重复知识条目版本: " + article.articleId() + "@" + article.version());
            }
            if (article.current()) {
                int count = currentByArticle.merge(article.articleId(), 1, Integer::sum);
                if (count > 1) {
                    throw new KnowledgeCatalogValidationException(
                            "DUPLICATE_CURRENT_KNOWLEDGE",
                            "同一知识条目只能有一个 current 版本: " + article.articleId());
                }
            }
            for (KnowledgeChunkDocument chunk : article.chunks()) {
                if (!chunkIds.add(chunk.chunkId())) {
                    throw new KnowledgeCatalogValidationException(
                            "DUPLICATE_KNOWLEDGE_CHUNK", "重复知识分段: " + chunk.chunkId());
                }
            }
        }
        for (KnowledgeArticleDocument article : articles) {
            if (!article.current() && !currentByArticle.containsKey(article.articleId())) {
                throw new KnowledgeCatalogValidationException(
                        "MISSING_CURRENT_KNOWLEDGE",
                        "知识条目没有 current 版本: " + article.articleId());
            }
        }
        return articles;
    }

    private KnowledgeArticleDocument parse(Resource resource) {
        try {
            return parser.parse(resource);
        } catch (IOException exception) {
            throw new KnowledgeCatalogValidationException(
                    "KNOWLEDGE_SOURCE_UNREADABLE", stableSourceFile(resource) + " 无法读取");
        }
    }

    private KnowledgeIndexState replaceIndex(List<KnowledgeArticleDocument> articles) {
        return transactions.execute(
                status -> {
                    acquireAdvisoryLock();
                    Long previousGeneration =
                            jdbc.queryForObject(
                                    "select generation from knowledge_index_state where id = 1",
                                    Long.class);
                    long generation = previousGeneration == null ? 1 : previousGeneration + 1;
                    Instant indexedAt = clock.instant();
                    String sourceDigest = sourceDigest(articles);
                    jdbc.update("delete from knowledge_chunk");
                    jdbc.update("delete from knowledge_article");
                    for (KnowledgeArticleDocument article : articles) insertArticle(article, indexedAt);
                    for (KnowledgeArticleDocument article : articles) {
                        for (KnowledgeChunkDocument chunk : article.chunks()) {
                            insertChunk(chunk, indexedAt);
                        }
                    }
                    jdbc.update(
                            "update knowledge_index_state set status = 'READY', generation = ?, "
                                    + "source_digest = ?, indexed_at = ?, updated_at = ?, "
                                    + "article_count = ?, chunk_count = ?, failure_code = null, "
                                    + "failure_message = null where id = 1",
                            generation,
                            sourceDigest,
                            indexedAt,
                            indexedAt,
                            articles.size(),
                            articles.stream().mapToInt(article -> article.chunks().size()).sum());
                    return new KnowledgeIndexState(
                            "READY",
                            generation,
                            sourceDigest,
                            indexedAt,
                            indexedAt,
                            articles.size(),
                            articles.stream().mapToInt(article -> article.chunks().size()).sum(),
                            null,
                            null);
                });
    }

    private void insertArticle(KnowledgeArticleDocument article, Instant indexedAt) {
        jdbc.update(
                "insert into knowledge_article (article_id, version, title, updated_at, "
                        + "applicability, publication_status, is_current, source_file, content_hash, body, indexed_at) "
                        + "values (?, ?, ?, ?, ?::text[], ?, ?, ?, ?, ?, ?)",
                article.articleId(),
                article.version(),
                article.title(),
                article.updatedAt(),
                article.applicability().toArray(String[]::new),
                article.publicationStatus().name(),
                article.current(),
                article.sourceFile(),
                article.contentHash(),
                article.body(),
                indexedAt);
    }

    private void insertChunk(KnowledgeChunkDocument chunk, Instant indexedAt) {
        jdbc.update(
                "insert into knowledge_chunk (chunk_id, article_id, version, ordinal, source_file, "
                        + "start_line, end_line, content, indexed_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                chunk.chunkId(),
                chunk.articleId(),
                chunk.version(),
                chunk.ordinal(),
                chunk.sourceFile(),
                chunk.startLine(),
                chunk.endLine(),
                chunk.content(),
                indexedAt);
    }

    private KnowledgeIndexState markFailure(String code, String message) {
        try {
            return transactions.execute(
                    status -> {
                        KnowledgeIndexState current = readState();
                        Instant updatedAt = clock.instant();
                        String safeMessage = message == null ? "知识目录校验失败" : message;
                        if (safeMessage.length() > 500) safeMessage = safeMessage.substring(0, 500);
                        jdbc.update(
                                "update knowledge_index_state set status = 'FAILED', failure_code = ?, "
                                        + "failure_message = ?, updated_at = ? where id = 1",
                                code,
                                safeMessage,
                                updatedAt);
                        return new KnowledgeIndexState(
                                "FAILED",
                                current.generation(),
                                current.sourceDigest(),
                                current.indexedAt(),
                                updatedAt,
                                current.articleCount(),
                                current.chunkCount(),
                                code,
                                safeMessage);
                    });
        } catch (RuntimeException persistenceFailure) {
            LOG.warn("knowledge index failure state unavailable code={}", code);
            return new KnowledgeIndexState(
                    "FAILED", 0, null, null, clock.instant(), 0, 0, code, "知识索引当前不可用");
        }
    }

    private KnowledgeIndexState readState() {
        return jdbc.queryForObject(
                "select status, generation, source_digest, indexed_at, updated_at, article_count, "
                        + "chunk_count, failure_code, failure_message from knowledge_index_state where id = 1",
                (rs, row) ->
                        new KnowledgeIndexState(
                                rs.getString(1),
                                rs.getLong(2),
                                rs.getString(3),
                                instant(rs.getTimestamp(4)),
                                instant(rs.getTimestamp(5)),
                                rs.getInt(6),
                                rs.getInt(7),
                                rs.getString(8),
                                rs.getString(9)));
    }

    private void acquireAdvisoryLock() {
        jdbc.query("select pg_advisory_xact_lock(" + ADVISORY_LOCK_KEY + ")", result -> null);
    }

    private String sourceDigest(List<KnowledgeArticleDocument> articles) {
        String value =
                articles.stream()
                        .sorted(Comparator.comparing(KnowledgeArticleDocument::articleId).thenComparing(KnowledgeArticleDocument::version))
                        .map(
                                article ->
                                        article.articleId()
                                                + "\u0000"
                                                + article.version()
                                                + "\u0000"
                                                + article.title()
                                                + "\u0000"
                                                + article.updatedAt()
                                                + "\u0000"
                                                + String.join(",", article.applicability())
                                                + "\u0000"
                                                + article.publicationStatus()
                                                + "\u0000"
                                                + article.current()
                                                + "\u0000"
                                                + article.sourceFile()
                                                + "\u0000"
                                                + article.contentHash())
                        .reduce("", (left, right) -> left + right + "\n");
        try {
            return java.util.HexFormat.of()
                    .formatHex(
                            java.security.MessageDigest.getInstance("SHA-256")
                                    .digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private String stableSourceFile(Resource resource) {
        String filename = resource.getFilename();
        return filename == null ? resource.getDescription() : "knowledge/" + filename;
    }

    private static String failureCode(Exception exception) {
        return exception instanceof KnowledgeCatalogValidationException validation
                ? validation.code()
                : "KNOWLEDGE_SOURCE_UNREADABLE";
    }

    private static Instant instant(java.sql.Timestamp timestamp) {
        return timestamp == null ? null : timestamp.toInstant();
    }
}
