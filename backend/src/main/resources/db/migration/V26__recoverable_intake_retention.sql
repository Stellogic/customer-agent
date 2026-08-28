ALTER TABLE customer_intake
    ADD COLUMN retention_state text NOT NULL DEFAULT 'ACTIVE'
        CHECK (retention_state IN ('ACTIVE', 'ARCHIVED', 'COMPLETED')),
    ADD COLUMN version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    ADD COLUMN expires_at timestamptz,
    ADD COLUMN archived_at timestamptz,
    ADD COLUMN restored_at timestamptz,
    ADD COLUMN facts_changed boolean NOT NULL DEFAULT false;

UPDATE customer_intake
SET retention_state = CASE WHEN status = 'CONFIRMED' THEN 'COMPLETED' ELSE 'ACTIVE' END,
    expires_at = CASE WHEN status = 'CONFIRMED' THEN NULL ELSE updated_at + interval '7 days' END;

ALTER TABLE customer_intake
    ADD CONSTRAINT customer_intake_retention_shape CHECK (
        (retention_state = 'ACTIVE' AND status <> 'CONFIRMED'
            AND expires_at IS NOT NULL AND archived_at IS NULL)
        OR (retention_state = 'ARCHIVED' AND status <> 'CONFIRMED'
            AND expires_at IS NOT NULL AND archived_at IS NOT NULL)
        OR (retention_state = 'COMPLETED' AND status = 'CONFIRMED'
            AND expires_at IS NULL AND archived_at IS NULL)
    );

CREATE INDEX customer_intake_customer_recovery
    ON customer_intake (customer_id, retention_state, updated_at DESC);

CREATE TABLE customer_intake_transcript (
    id uuid PRIMARY KEY,
    intake_id uuid NOT NULL REFERENCES customer_intake(id) ON DELETE CASCADE,
    ordinal bigint NOT NULL CHECK (ordinal > 0),
    author text NOT NULL CHECK (author IN ('CUSTOMER', 'AGENT')),
    body text NOT NULL CHECK (length(trim(body)) > 0),
    created_at timestamptz NOT NULL,
    UNIQUE (intake_id, ordinal)
);

INSERT INTO customer_intake_transcript (id, intake_id, ordinal, author, body, created_at)
SELECT gen_random_uuid(), id, 1, 'CUSTOMER', original_message, created_at
FROM customer_intake;

INSERT INTO customer_intake_transcript (id, intake_id, ordinal, author, body, created_at)
SELECT gen_random_uuid(), intake_id, ordinal + 1, 'CUSTOMER', customer_message, created_at
FROM (
    SELECT intake_id, customer_message, created_at,
        row_number() OVER (
            PARTITION BY intake_id ORDER BY created_at, request_key
        ) AS ordinal
    FROM customer_intake_message
) messages;

INSERT INTO customer_intake_transcript (id, intake_id, ordinal, author, body, created_at)
SELECT gen_random_uuid(), intake.id, coalesce(messages.message_count, 0) + 2,
    'AGENT', intake.assistant_message, intake.updated_at
FROM customer_intake intake
LEFT JOIN (
    SELECT intake_id, count(*) AS message_count
    FROM customer_intake_message
    GROUP BY intake_id
) messages ON messages.intake_id = intake.id;

CREATE TABLE customer_intake_restore_request (
    intake_id uuid NOT NULL REFERENCES customer_intake(id) ON DELETE CASCADE,
    request_key text NOT NULL,
    request_digest char(64) NOT NULL,
    resulting_version bigint NOT NULL CHECK (resulting_version > 0),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (intake_id, request_key)
);

GRANT SELECT, INSERT ON customer_intake_transcript,
    customer_intake_restore_request TO spring_app;
