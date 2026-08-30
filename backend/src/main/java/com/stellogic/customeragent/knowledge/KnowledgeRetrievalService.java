package com.stellogic.customeragent.knowledge;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
class KnowledgeRetrievalService {
    // 预先选择一次，不通过冻结评测反向调参。
    private static final double MIN_SIMILARITY = 0.80;
    private static final String ELIGIBLE =
            """
            with eligible as materialized (
              select c.*, a.title, e.embedding from knowledge_chunk c
              join knowledge_article a using(article_id,version)
              join knowledge_embedding e using(chunk_id)
              where a.publication_status='PUBLISHED' and a.is_current
                and a.applicability && ?::text[] and c.applicability && ?::text[]
                and e.generation=? and e.revision=? and e.content_hash=a.content_hash
            )
            """;
    private final JdbcTemplate jdbc;
    private final KnowledgeAccessPolicy access;
    private final KnowledgeEmbeddingGateway embedding;

    KnowledgeRetrievalService(
            JdbcTemplate jdbc, KnowledgeAccessPolicy access, KnowledgeEmbeddingGateway embedding) {
        this.jdbc = jdbc;
        this.access = access;
        this.embedding = embedding;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public KnowledgeRetrievalResponse search(String principal, String query, String scope) {
        List<String> allowed = access.requireScopes(principal);
        if (query == null || query.isBlank() || query.length() > 200) {
            throw new KnowledgeInvalidQueryException("检索问题长度必须在 1 到 200 之间");
        }
        List<String> scopes =
                scope == null ? allowed : allowed.stream().filter(scope::equals).toList();
        if (scope != null
                && !List.of("INTERNAL", "SUPPORT", "APPROVER", "CUSTOMER_PUBLIC").contains(scope)) {
            throw new KnowledgeInvalidQueryException("检索适用范围无效");
        }
        try {
            Long generation =
                    jdbc.queryForObject(
                            """
                            select s.generation from knowledge_index_state s join knowledge_vector_state v on s.id=v.id
                            where s.id=1 and s.status in ('READY','EMPTY') and s.failure_code is null
                              and s.generation=v.generation and v.revision=?
                              and not exists (
                                select 1 from knowledge_chunk c join knowledge_article a using(article_id,version)
                                left join knowledge_embedding e using(chunk_id)
                                where a.publication_status='PUBLISHED' and a.is_current
                                  and (e.chunk_id is null or e.generation<>s.generation or e.revision<>v.revision
                                       or e.content_hash<>a.content_hash))
                            """,
                            Long.class,
                            KnowledgeEmbeddingGateway.REVISION);
            if (generation == null) throw new KnowledgeRetrievalUnavailableException("INDEX_STALE");
            String vector = embedding.encode(List.of(query.trim()), true).getFirst();
            String[] scopeArray = scopes.toArray(String[]::new);
            List<KnowledgeRetrievalHit> lexical =
                    jdbc.query(
                            ELIGIBLE
                                    + """
                                    select *, ts_rank_cd(search_vector, plainto_tsquery('simple', ?)) as score
                                    from eligible where search_vector @@ plainto_tsquery('simple', ?)
                                    order by score desc, chunk_id limit 20
                                    """,
                            (rs, row) -> hit(rs, true),
                            scopeArray,
                            scopeArray,
                            generation,
                            KnowledgeEmbeddingGateway.REVISION,
                            query.trim(),
                            query.trim());
            List<KnowledgeRetrievalHit> dense =
                    jdbc.query(
                            ELIGIBLE
                                    + """
                                    select *, 1 - (embedding <=> ?::vector) as score
                                    from eligible order by embedding <=> ?::vector, chunk_id limit 20
                                    """,
                            (rs, row) -> hit(rs, false),
                            scopeArray,
                            scopeArray,
                            generation,
                            KnowledgeEmbeddingGateway.REVISION,
                            vector,
                            vector);
            List<KnowledgeRetrievalHit> results = fuse(lexical, dense);
            return new KnowledgeRetrievalResponse(
                    "knowledge-hybrid-v1",
                    query.trim(),
                    generation,
                    KnowledgeEmbeddingGateway.REVISION,
                    lexical,
                    dense,
                    results);
        } catch (KnowledgeRetrievalUnavailableException exception) {
            throw exception;
        } catch (org.springframework.dao.EmptyResultDataAccessException exception) {
            throw new KnowledgeRetrievalUnavailableException("INDEX_STALE");
        } catch (RuntimeException exception) {
            throw new KnowledgeRetrievalUnavailableException("RETRIEVAL_UNAVAILABLE");
        }
    }

    private static KnowledgeRetrievalHit hit(java.sql.ResultSet rs, boolean lexical)
            throws SQLException {
        double score = rs.getDouble("score");
        if (!Double.isFinite(score))
            throw new KnowledgeRetrievalUnavailableException("FUSION_UNAVAILABLE");
        return new KnowledgeRetrievalHit(
                rs.getString("chunk_id"),
                rs.getString("article_id"),
                rs.getString("version"),
                rs.getString("title"),
                List.of((String[]) rs.getArray("applicability").getArray()),
                rs.getString("source_file"),
                rs.getInt("start_line"),
                rs.getInt("end_line"),
                rs.getString("content"),
                score,
                lexical ? score : null,
                lexical ? null : score);
    }

    private static List<KnowledgeRetrievalHit> fuse(
            List<KnowledgeRetrievalHit> lexical, List<KnowledgeRetrievalHit> dense) {
        if (dense.isEmpty() || dense.getFirst().score() < MIN_SIMILARITY) return List.of();
        Map<String, KnowledgeRetrievalHit> hits = new HashMap<>();
        Map<String, Double> scores = new HashMap<>();
        Map<String, Double> lexicalScores = new HashMap<>();
        Map<String, Double> vectorScores = new HashMap<>();
        for (List<KnowledgeRetrievalHit> candidates : List.of(lexical, dense)) {
            for (int i = 0; i < candidates.size(); i++) {
                KnowledgeRetrievalHit hit = candidates.get(i);
                hits.put(hit.chunkId(), hit);
                scores.merge(hit.chunkId(), 1.0 / (60 + i + 1), Double::sum);
                if (hit.lexicalScore() != null)
                    lexicalScores.put(hit.chunkId(), hit.lexicalScore());
                if (hit.vectorScore() != null) vectorScores.put(hit.chunkId(), hit.vectorScore());
            }
        }
        List<KnowledgeRetrievalHit> results = new ArrayList<>();
        for (KnowledgeRetrievalHit hit : hits.values()) {
            results.add(
                    new KnowledgeRetrievalHit(
                            hit.chunkId(),
                            hit.articleId(),
                            hit.version(),
                            hit.title(),
                            hit.applicability(),
                            hit.sourceFile(),
                            hit.startLine(),
                            hit.endLine(),
                            hit.snippet(),
                            scores.get(hit.chunkId()),
                            lexicalScores.get(hit.chunkId()),
                            vectorScores.get(hit.chunkId())));
        }
        return results.stream()
                .sorted(
                        Comparator.comparingDouble(KnowledgeRetrievalHit::score)
                                .reversed()
                                .thenComparing(KnowledgeRetrievalHit::chunkId))
                .limit(5)
                .toList();
    }
}
