CREATE TABLE intake_model_call (
    invocation_id uuid PRIMARY KEY,
    customer_id text NOT NULL,
    intake_id uuid,
    operation text NOT NULL,
    request_key text NOT NULL,
    phase text NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    status text NOT NULL CHECK (status IN ('PENDING', 'SUCCEEDED', 'FAILED')),
    spring_failure_reason text,
    evidence jsonb
);

CREATE INDEX intake_model_call_intake ON intake_model_call (intake_id, started_at);
GRANT SELECT, INSERT, UPDATE ON intake_model_call TO spring_app;
GRANT SELECT ON intake_model_call TO spring_fixture;
