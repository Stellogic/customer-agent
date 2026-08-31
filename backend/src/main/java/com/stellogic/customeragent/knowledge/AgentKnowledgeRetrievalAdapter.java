package com.stellogic.customeragent.knowledge;

import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 共用检索投影。外层须在调用前后各自校验当前工单 generation 或 HUMAN assignment。
 * 外层不持事务；通过 Spring 代理调用本类，保证检索与 canonical 补读使用同一快照。
 */
@Service
public class AgentKnowledgeRetrievalAdapter {
    private final KnowledgeRetrievalService retrieval;
    private final KnowledgeAccessPolicy access;
    private final JdbcTemplate jdbc;

    AgentKnowledgeRetrievalAdapter(
            KnowledgeRetrievalService retrieval, KnowledgeAccessPolicy access, JdbcTemplate jdbc) {
        this.retrieval = retrieval;
        this.access = access;
        this.jdbc = jdbc;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AgentKnowledgeResult searchCustomer(String query) {
        return search(query, List.of("CUSTOMER_PUBLIC"));
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AgentKnowledgeResult searchSupport(String principalId, String query) {
        return search(query, supportScopes(principalId));
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AgentKnowledgeResult revalidateCustomer(AgentKnowledgeResult receipt) {
        return revalidate(receipt, List.of("CUSTOMER_PUBLIC"));
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AgentKnowledgeResult revalidateSupport(String principalId, AgentKnowledgeResult receipt) {
        return revalidate(receipt, supportScopes(principalId));
    }

    private List<String> supportScopes(String principalId) {
        if (!access.requireScopes(principalId).contains("SUPPORT")) {
            throw new KnowledgeAccessDeniedException();
        }
        return List.of("INTERNAL", "SUPPORT");
    }

    private AgentKnowledgeResult revalidate(AgentKnowledgeResult receipt, List<String> scopes) {
        if (!"agent-knowledge-v1".equals(receipt.schema()) || receipt.results().size() > 5) {
            throw new InvalidKnowledgeCitationException();
        }
        Integer current = jdbc.queryForObject(
                """
                select count(*) from knowledge_index_state s join knowledge_vector_state v on s.id=v.id
                where s.id=1 and s.status in ('READY','EMPTY') and s.failure_code is null
                  and s.generation=? and s.generation=v.generation and v.revision=?
                """, Integer.class, receipt.indexGeneration(), KnowledgeEmbeddingGateway.REVISION);
        if (current == null || current != 1) {
            throw new KnowledgeRetrievalUnavailableException("INDEX_STALE");
        }
        for (AgentKnowledgeResult.Source source : receipt.results()) {
            AgentKnowledgeResult.Source canonical =
                    canonicalSource(source.articleId(), source.version(), source.chunkId(), scopes);
            if (!canonical.equals(source)) throw new InvalidKnowledgeCitationException();
        }
        return receipt;
    }

    private AgentKnowledgeResult search(String query, List<String> scopes) {
        KnowledgeRetrievalResponse response = retrieval.searchAuthorizedScopes(query, scopes);
        List<AgentKnowledgeResult.Source> results =
                response.results().stream()
                        .map(hit -> canonicalSource(hit.articleId(), hit.version(), hit.chunkId(), scopes))
                        .toList();
        return new AgentKnowledgeResult("agent-knowledge-v1", response.generation(), results);
    }

    private AgentKnowledgeResult.Source canonicalSource(
            String articleId, String version, String chunkId, List<String> scopes) {
        List<AgentKnowledgeResult.Source> rows =
                jdbc.query(
                        """
                        select a.title, a.updated_at, a.applicability as article_scopes,
                               c.applicability as chunk_scopes, c.start_line, c.end_line, c.content
                        from knowledge_article a join knowledge_chunk c using(article_id,version)
                        where a.article_id=? and a.version=? and c.chunk_id=?
                          and a.publication_status='PUBLISHED' and a.is_current
                        """,
                        (rs, row) -> {
                            List<String> articleScopes =
                                    List.of((String[]) rs.getArray("article_scopes").getArray());
                            List<String> chunkScopes =
                                    List.of((String[]) rs.getArray("chunk_scopes").getArray());
                            List<String> matching = scopes.stream()
                                    .filter(articleScopes::contains).filter(chunkScopes::contains).toList();
                            if (matching.isEmpty()) throw new KnowledgeAccessDeniedException();
                            return new AgentKnowledgeResult.Source(
                                    articleId, version, chunkId,
                                    rs.getString("title"), rs.getTimestamp("updated_at").toInstant(),
                                    matching, rs.getInt("start_line"), rs.getInt("end_line"),
                                    rs.getString("content"));
                        },
                        articleId, version, chunkId);
        if (rows.isEmpty()) throw new InvalidKnowledgeCitationException();
        return rows.getFirst();
    }
}
