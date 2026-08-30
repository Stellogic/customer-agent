-- vector 扩展必须由数据库管理员预先安装；应用和迁移角色不提升为超级用户。
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'knowledge retrieval requires preinstalled pgvector';
    END IF;
END $$;

CREATE TABLE knowledge_embedding (
    chunk_id text PRIMARY KEY REFERENCES knowledge_chunk(chunk_id) ON DELETE CASCADE,
    generation bigint NOT NULL,
    content_hash char(64) NOT NULL,
    revision char(40) NOT NULL,
    embedding vector(512) NOT NULL
);

CREATE TABLE knowledge_vector_state (
    id smallint PRIMARY KEY CHECK(id=1),
    generation bigint NOT NULL,
    revision char(40) NOT NULL
);

GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_embedding, knowledge_vector_state TO spring_app;
GRANT SELECT ON knowledge_article TO spring_fixture;
