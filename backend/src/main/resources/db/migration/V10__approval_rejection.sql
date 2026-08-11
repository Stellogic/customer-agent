ALTER TABLE support_ticket DROP CONSTRAINT support_ticket_handoff_reason_check;
ALTER TABLE support_ticket ADD CONSTRAINT support_ticket_handoff_reason_check
    CHECK (human_handoff_reason_code IS NULL OR human_handoff_reason_code IN (
        'CUSTOMER_REQUESTED', 'TOOL_RETRY_EXHAUSTED', 'FACT_CONFLICT',
        'INVALID_TOOL_RESPONSE', 'REQUIRED_FACT_MISSING', 'UNSUPPORTED_SCENARIO',
        'APPROVAL_REJECTED'
    ));

ALTER TABLE shared_support_queue_entry DROP CONSTRAINT shared_support_queue_entry_reason_code_check;
ALTER TABLE shared_support_queue_entry ADD CONSTRAINT shared_support_queue_entry_reason_code_check
    CHECK (reason_code IN (
        'SLA_BREACH', 'CUSTOMER_REQUESTED_HANDOFF', 'AGENT_HUMAN_HANDOFF',
        'APPROVAL_REJECTED_HANDOFF'
    ));

ALTER TABLE approval_lease
    DROP CONSTRAINT approval_lease_status_check,
    ADD COLUMN decided_at timestamptz,
    ADD CONSTRAINT approval_lease_status_check
        CHECK (status IN ('ACTIVE', 'EXPIRED', 'RELEASED', 'REVOKED', 'DECIDED')),
    ADD CONSTRAINT approval_lease_decided_at_complete
        CHECK ((status = 'DECIDED') = (decided_at IS NOT NULL));

CREATE TABLE approval_decision (
    id uuid PRIMARY KEY,
    proposal_revision_id uuid NOT NULL UNIQUE REFERENCES compensation_proposal_revision(id),
    proposal_revision integer NOT NULL CHECK (proposal_revision > 0),
    content_digest char(64) NOT NULL,
    approver_id text NOT NULL,
    lease_token uuid NOT NULL,
    lease_version bigint NOT NULL CHECK (lease_version > 0),
    -- #21 与后继批准命令共享这一唯一仲裁点，避免按 endpoint 各建一套决定身份。
    decision_type text NOT NULL CHECK (decision_type IN ('APPROVED', 'REJECTED')),
    internal_reason text,
    decided_at timestamptz NOT NULL,
    FOREIGN KEY (proposal_revision_id, lease_version)
        REFERENCES approval_lease(proposal_revision_id, lease_version),
    CHECK (
        (decision_type = 'REJECTED' AND internal_reason IS NOT NULL AND btrim(internal_reason) <> '')
        OR decision_type = 'APPROVED'
    )
);

CREATE TABLE approval_decision_request (
    approver_id text NOT NULL,
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    decision_id uuid NOT NULL UNIQUE REFERENCES approval_decision(id),
    proposal_revision_id uuid NOT NULL,
    proposal_revision integer NOT NULL CHECK (proposal_revision > 0),
    content_digest char(64) NOT NULL,
    lease_token uuid NOT NULL,
    lease_version bigint NOT NULL CHECK (lease_version > 0),
    decision_type text NOT NULL CHECK (decision_type IN ('APPROVED', 'REJECTED')),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (approver_id, request_id),
    FOREIGN KEY (proposal_revision_id) REFERENCES compensation_proposal_revision(id),
    FOREIGN KEY (proposal_revision_id, lease_version)
        REFERENCES approval_lease(proposal_revision_id, lease_version)
);

GRANT SELECT, INSERT ON approval_decision, approval_decision_request TO spring_app;
