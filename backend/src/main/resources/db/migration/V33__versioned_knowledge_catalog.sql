CREATE TABLE knowledge_article (
    article_id text NOT NULL CHECK (article_id ~ '^[a-z0-9][a-z0-9-]{2,63}$'),
    version text NOT NULL CHECK (length(btrim(version)) BETWEEN 1 AND 64),
    title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    updated_at timestamptz NOT NULL,
    applicability text[] NOT NULL CHECK (cardinality(applicability) > 0),
    publication_status text NOT NULL CHECK (publication_status IN ('DRAFT', 'PUBLISHED', 'RETIRED')),
    is_current boolean NOT NULL,
    source_file text NOT NULL CHECK (length(btrim(source_file)) > 0),
    content_hash char(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    body text NOT NULL CHECK (length(btrim(body)) > 0),
    indexed_at timestamptz NOT NULL,
    PRIMARY KEY (article_id, version),
    UNIQUE (source_file),
    CHECK (NOT is_current OR publication_status = 'PUBLISHED')
);

CREATE UNIQUE INDEX knowledge_article_one_current
    ON knowledge_article (article_id)
    WHERE is_current;

CREATE INDEX knowledge_article_applicability
    ON knowledge_article USING GIN (applicability);

CREATE TABLE knowledge_chunk (
    chunk_id text PRIMARY KEY CHECK (chunk_id ~ '^chunk-[0-9a-f]{64}$'),
    article_id text NOT NULL,
    version text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    source_file text NOT NULL CHECK (length(btrim(source_file)) > 0),
    start_line integer NOT NULL CHECK (start_line > 0),
    end_line integer NOT NULL CHECK (end_line >= start_line),
    content text NOT NULL CHECK (length(btrim(content)) > 0),
    indexed_at timestamptz NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    FOREIGN KEY (article_id, version)
        REFERENCES knowledge_article (article_id, version)
        ON DELETE CASCADE,
    UNIQUE (article_id, version, ordinal)
);

CREATE INDEX knowledge_chunk_search_vector
    ON knowledge_chunk USING GIN (search_vector);

CREATE INDEX knowledge_chunk_article_version
    ON knowledge_chunk (article_id, version, ordinal);

CREATE TABLE knowledge_index_state (
    id smallint PRIMARY KEY CHECK (id = 1),
    status text NOT NULL CHECK (status IN ('EMPTY', 'READY', 'FAILED')),
    generation bigint NOT NULL CHECK (generation >= 0),
    source_digest char(64) CHECK (source_digest IS NULL OR source_digest ~ '^[0-9a-f]{64}$'),
    indexed_at timestamptz,
    updated_at timestamptz NOT NULL,
    article_count integer NOT NULL CHECK (article_count >= 0),
    chunk_count integer NOT NULL CHECK (chunk_count >= 0),
    failure_code text,
    failure_message text
);

INSERT INTO knowledge_index_state (
    id, status, generation, indexed_at, updated_at, article_count, chunk_count
) VALUES (1, 'EMPTY', 0, NULL, current_timestamp, 0, 0);

GRANT SELECT, INSERT, UPDATE, DELETE
    ON knowledge_article, knowledge_chunk, knowledge_index_state TO spring_app;
