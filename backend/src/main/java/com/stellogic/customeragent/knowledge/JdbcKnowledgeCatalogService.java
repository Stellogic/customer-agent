package com.stellogic.customeragent.knowledge;

import java.sql.Array;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
final class JdbcKnowledgeCatalogService implements KnowledgeCatalogService {
    private static final String VIEW = "KNOWLEDGE_CATALOG";
    private static final String SCHEMA = "knowledge-catalog-v1";

    private final JdbcTemplate jdbc;
    private final KnowledgeAccessPolicy access;
    private final KnowledgeCatalogIndexer indexer;

    JdbcKnowledgeCatalogService(
            JdbcTemplate jdbc, KnowledgeAccessPolicy access, KnowledgeCatalogIndexer indexer) {
        this.jdbc = jdbc;
        this.access = access;
        this.indexer = indexer;
    }

    @Override
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public KnowledgeCatalogResponse search(String principalId, String query, int limit) {
        List<String> scopes = access.requireScopes(principalId);
        String normalizedQuery = normalizeQuery(query);
        if (limit < 1 || limit > 50) {
            throw new KnowledgeInvalidQueryException("limit 必须在 1 到 50 之间");
        }
        KnowledgeIndexState state = requireReady();
        String compactQuery = normalizedQuery.replaceAll("\\s+", "");
        String[] scopeArray = scopes.toArray(String[]::new);
        List<KnowledgeSearchResult> results =
                jdbc.query(
                        "with parsed as (select plainto_tsquery('simple', ?) as query) "
                                + "select c.chunk_id, a.article_id, a.version, a.title, a.updated_at, "
                                + "a.applicability, c.source_file, c.start_line, c.end_line, c.content, "
                                + "ts_rank_cd(c.search_vector, parsed.query) as rank, "
                                + "case when ? <> '' and position(lower(?) in lower(c.content)) > 0 "
                                + "then 1 else 0 end as exact_match "
                                + "from knowledge_chunk c "
                                + "join knowledge_article a on a.article_id = c.article_id and a.version = c.version "
                                + "cross join parsed "
                                + "where a.publication_status = 'PUBLISHED' and a.is_current "
                                + "and a.applicability && ?::text[] "
                                + "and (? = '' or c.search_vector @@ parsed.query "
                                + "or position(lower(?) in lower(c.content)) > 0 "
                                + "or position(lower(?) in regexp_replace(lower(c.content), '\\s+', '', 'g')) > 0) "
                                + "and (? <> '' or c.ordinal = 1) "
                                + "order by exact_match desc, rank desc, a.updated_at desc, c.ordinal, c.chunk_id "
                                + "limit ?",
                        (rs, row) ->
                                new KnowledgeSearchResult(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getString(4),
                                        timestamp(rs.getTimestamp(5)),
                                        strings(rs.getArray(6)),
                                        rs.getString(7),
                                        rs.getInt(8),
                                        rs.getInt(9),
                                        snippet(rs.getString(10), normalizedQuery),
                                        rs.getInt(12) == 1 ? "KEYWORD" : "FULL_TEXT",
                                        rs.getDouble(11)),
                        normalizedQuery,
                        normalizedQuery,
                        normalizedQuery,
                        scopeArray,
                        normalizedQuery,
                        normalizedQuery,
                        compactQuery,
                        normalizedQuery,
                        limit);
        return new KnowledgeCatalogResponse(VIEW, SCHEMA, state, normalizedQuery, results);
    }

    @Override
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public KnowledgeArticleResponse article(String principalId, String articleId, String version) {
        List<String> scopes = access.requireScopes(principalId);
        requireArticleId(articleId);
        if (version != null && (version.isBlank() || version.length() > 64)) {
            throw new KnowledgeInvalidQueryException("version 无效");
        }
        KnowledgeIndexState state = requireReady();
        String[] scopeArray = scopes.toArray(String[]::new);
        String whereVersion =
                version == null
                        ? "a.article_id = ? and a.is_current and a.applicability && ?::text[]"
                        : "a.article_id = ? and a.version = ? and a.applicability && ?::text[]";
        Object[] parameters =
                version == null
                        ? new Object[] {articleId, scopeArray}
                        : new Object[] {articleId, version, scopeArray};
        KnowledgeArticleDetail detail =
                jdbc.query(
                                "select a.article_id, a.title, a.version, a.updated_at, a.applicability, "
                                        + "a.publication_status, a.is_current, a.source_file, a.content_hash, a.body "
                                        + "from knowledge_article a where "
                                        + whereVersion,
                                (rs, row) ->
                                        new KnowledgeArticleDetail(
                                                rs.getString(1),
                                                rs.getString(2),
                                                rs.getString(3),
                                                timestamp(rs.getTimestamp(4)),
                                                strings(rs.getArray(5)),
                                                rs.getString(6),
                                                rs.getBoolean(7),
                                                rs.getString(8),
                                                rs.getString(9),
                                                rs.getString(10),
                                                List.of(),
                                                List.of()),
                                parameters)
                        .stream()
                        .findFirst()
                        .orElseThrow(KnowledgeArticleNotFoundException::new);

        List<KnowledgeArticleVersion> versions =
                jdbc.query(
                        "select a.article_id, a.title, a.version, a.updated_at, a.applicability, "
                                + "a.publication_status, a.is_current, a.source_file from knowledge_article a "
                                + "where a.article_id = ? and a.applicability && ?::text[] "
                                + "order by a.is_current desc, a.updated_at desc, a.version desc",
                        (rs, row) ->
                                new KnowledgeArticleVersion(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getString(3),
                                        timestamp(rs.getTimestamp(4)),
                                        strings(rs.getArray(5)),
                                        rs.getString(6),
                                        rs.getBoolean(7),
                                        rs.getString(8)),
                        articleId,
                        scopeArray);
        List<KnowledgeChunkCitation> chunks =
                jdbc.query(
                        "select chunk_id, article_id, version, source_file, start_line, end_line, content "
                                + "from knowledge_chunk where article_id = ? and version = ? order by ordinal",
                        (rs, row) ->
                                new KnowledgeChunkCitation(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getString(4),
                                        rs.getInt(5),
                                        rs.getInt(6),
                                        rs.getString(7)),
                        detail.articleId(),
                        detail.version());
        KnowledgeArticleDetail withRelated =
                new KnowledgeArticleDetail(
                        detail.articleId(),
                        detail.title(),
                        detail.version(),
                        detail.updatedAt(),
                        detail.applicability(),
                        detail.publicationStatus(),
                        detail.current(),
                        detail.sourceFile(),
                        detail.contentHash(),
                        detail.body(),
                        versions,
                        chunks);
        return new KnowledgeArticleResponse(VIEW, SCHEMA, state, withRelated);
    }

    @Override
    @Transactional(readOnly = true)
    public KnowledgeIndexState index(String principalId) {
        access.requireScopes(principalId);
        return readState();
    }

    @Override
    public KnowledgeIndexState rebuild(String principalId) {
        access.requireScopes(principalId);
        return indexer.rebuild();
    }

    private KnowledgeIndexState requireReady() {
        KnowledgeIndexState state = readState();
        if (!"READY".equals(state.status())) throw new KnowledgeIndexUnavailableException(state);
        return state;
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
                                timestamp(rs.getTimestamp(4)),
                                timestamp(rs.getTimestamp(5)),
                                rs.getInt(6),
                                rs.getInt(7),
                                rs.getString(8),
                                rs.getString(9)));
    }

    private static String normalizeQuery(String query) {
        String normalized = query == null ? "" : query.trim();
        if (normalized.length() > 200) {
            throw new KnowledgeInvalidQueryException("关键词不能超过 200 个字符");
        }
        return normalized;
    }

    private static void requireArticleId(String articleId) {
        if (articleId == null || !articleId.matches("[a-z0-9][a-z0-9-]{2,63}")) {
            throw new KnowledgeInvalidQueryException("articleId 无效");
        }
    }

    private static String snippet(String content, String query) {
        int max = 360;
        if (content.length() <= max) return content;
        String normalized = query.toLowerCase();
        int match = normalized.isBlank() ? -1 : content.toLowerCase().indexOf(normalized);
        int start = match > 80 ? match - 80 : 0;
        int end = Math.min(content.length(), start + max);
        String prefix = start > 0 ? "…" : "";
        String suffix = end < content.length() ? "…" : "";
        return prefix + content.substring(start, end) + suffix;
    }

    private static List<String> strings(Array array) {
        try {
            return List.of((String[]) array.getArray());
        } catch (java.sql.SQLException exception) {
            throw new IllegalStateException("knowledge applicability cannot be read", exception);
        }
    }

    private static Instant timestamp(Timestamp timestamp) {
        return timestamp == null ? null : timestamp.toInstant();
    }
}
