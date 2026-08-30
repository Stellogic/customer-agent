package com.stellogic.customeragent.knowledge;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.List;

@Component
final class KnowledgeVectorIndexer {
    private static final Logger LOG = LoggerFactory.getLogger(KnowledgeVectorIndexer.class);
    private final JdbcTemplate jdbc;
    private final KnowledgeEmbeddingGateway embedding;
    private final TransactionTemplate transaction;
    private final boolean migrateOnly;

    KnowledgeVectorIndexer(
            JdbcTemplate jdbc,
            KnowledgeEmbeddingGateway embedding,
            PlatformTransactionManager manager,
            @Value("${baseline.migrate-only:false}") boolean migrateOnly) {
        this.jdbc = jdbc;
        this.embedding = embedding;
        transaction = new TransactionTemplate(manager);
        this.migrateOnly = migrateOnly;
    }

    @Order(1)
    @EventListener(ApplicationReadyEvent.class)
    void rebuildOnStartup() {
        if (migrateOnly) return;
        try {
            transaction.executeWithoutResult(
                    status -> {
                        // 与目录替换使用同一事务锁，不发布一半或旧代次的向量。
                        jdbc.query("select pg_advisory_xact_lock(16620260829)", rs -> null);
                        Long generation =
                                jdbc.queryForObject(
                                        "select generation from knowledge_index_state where id=1"
                                            + " and status in ('READY','EMPTY') and failure_code is"
                                            + " null",
                                        Long.class);
                        List<Chunk> chunks =
                                jdbc.query(
                                        "select c.chunk_id, c.content, a.content_hash from"
                                            + " knowledge_chunk c join knowledge_article a"
                                            + " using(article_id,version) where"
                                            + " a.publication_status='PUBLISHED' and a.is_current"
                                            + " order by c.chunk_id",
                                        (rs, row) ->
                                                new Chunk(
                                                        rs.getString(1),
                                                        rs.getString(2),
                                                        rs.getString(3)));
                        jdbc.update("delete from knowledge_embedding");
                        for (int start = 0; start < chunks.size(); start += 32) {
                            List<Chunk> batch =
                                    chunks.subList(start, Math.min(start + 32, chunks.size()));
                            List<String> vectors =
                                    embedding.encode(
                                            batch.stream().map(Chunk::content).toList(), false);
                            for (int i = 0; i < batch.size(); i++) {
                                Chunk chunk = batch.get(i);
                                jdbc.update(
                                        "insert into knowledge_embedding"
                                            + " (chunk_id,generation,content_hash,revision,embedding)"
                                            + " values(?,?,?,?,?::vector)",
                                        chunk.id(),
                                        generation,
                                        chunk.hash(),
                                        KnowledgeEmbeddingGateway.REVISION,
                                        vectors.get(i));
                            }
                        }
                        jdbc.update(
                                "insert into knowledge_vector_state(id,generation,revision)"
                                    + " values(1,?,?) on conflict(id) do update set"
                                    + " generation=excluded.generation, revision=excluded.revision",
                                generation,
                                KnowledgeEmbeddingGateway.REVISION);
                    });
        } catch (RuntimeException exception) {
            LOG.warn("knowledge vector index unavailable code=VECTOR_INDEX_UNAVAILABLE");
        }
    }

    private record Chunk(String id, String content, String hash) {}
}
