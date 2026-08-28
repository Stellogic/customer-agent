CREATE TABLE intake_assistance_request (
    id uuid PRIMARY KEY,
    intake_id uuid NOT NULL REFERENCES customer_intake(id),
    reason_code text NOT NULL CHECK (reason_code IN (
        'AGENT_UNAVAILABLE', 'TOOL_UNAVAILABLE', 'CUSTOMER_REQUESTED', 'UNSUPPORTED_REQUEST'
    )),
    status text NOT NULL CHECK (status IN (
        'QUEUED', 'CLAIMED', 'WAITING_FOR_CUSTOMER', 'COMPLETED'
    )),
    support_id text,
    requested_at timestamptz NOT NULL,
    claimed_at timestamptz,
    claim_expires_at timestamptz,
    completed_at timestamptz,
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (
        (status = 'QUEUED' AND support_id IS NULL AND claimed_at IS NULL
            AND claim_expires_at IS NULL AND completed_at IS NULL)
        OR (status IN ('CLAIMED', 'WAITING_FOR_CUSTOMER') AND support_id IS NOT NULL
            AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL
            AND completed_at IS NULL)
        OR (status = 'COMPLETED' AND support_id IS NOT NULL
            AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL
            AND completed_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX intake_assistance_one_open_request
    ON intake_assistance_request (intake_id)
    WHERE status <> 'COMPLETED';

CREATE TABLE intake_assistance_proposal_request (
    assistance_request_id uuid NOT NULL REFERENCES intake_assistance_request(id),
    request_key text NOT NULL,
    request_digest char(64) NOT NULL,
    support_id text NOT NULL,
    previous_order_reference text,
    previous_issues jsonb NOT NULL,
    proposed_order_reference text NOT NULL,
    proposed_issues jsonb NOT NULL,
    resulting_intake_version bigint NOT NULL CHECK (resulting_intake_version > 0),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (assistance_request_id, request_key)
);

CREATE TABLE intake_assistance_event (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    epoch text NOT NULL CHECK (epoch = 'intake-assistance-v1'),
    event_type text NOT NULL CHECK (event_type IN (
        'ASSISTANCE_REQUEST_UPSERTED', 'ASSISTANCE_REQUEST_REMOVED'
    )),
    payload jsonb NOT NULL,
    occurred_at timestamptz NOT NULL
);

CREATE INDEX intake_assistance_event_epoch_sequence
    ON intake_assistance_event (epoch, sequence);

GRANT SELECT, INSERT, UPDATE ON intake_assistance_request TO spring_app;
GRANT SELECT, INSERT ON intake_assistance_proposal_request, intake_assistance_event TO spring_app;
GRANT USAGE, SELECT ON SEQUENCE intake_assistance_event_sequence_seq TO spring_app;
GRANT SELECT ON intake_assistance_request, intake_assistance_proposal_request,
    intake_assistance_event TO spring_fixture;
