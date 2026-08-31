-- 只记录内部辅助请求及受控回执，不写公开消息或业务动作。
CREATE TABLE support_assistance_request (
    support_id text NOT NULL,
    request_id uuid NOT NULL,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    assignment_id uuid NOT NULL REFERENCES support_assignment(id),
    kind text NOT NULL CHECK (kind IN ('summary', 'knowledge', 'policy', 'draft')),
    query text NOT NULL CHECK (char_length(query) BETWEEN 1 AND 200),
    input jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED')),
    result jsonb,
    model_audit jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    PRIMARY KEY (support_id, request_id)
);
