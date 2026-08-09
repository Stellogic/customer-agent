ALTER TABLE compensation_proposal_revision ADD COLUMN expires_at timestamptz;
UPDATE compensation_proposal_revision SET expires_at = created_at + interval '24 hours';
ALTER TABLE compensation_proposal_revision ALTER COLUMN expires_at SET NOT NULL;

ALTER TABLE audit_event
    ADD COLUMN subject_type text,
    ADD COLUMN subject_id uuid,
    ADD COLUMN authorization_version bigint,
    ADD CONSTRAINT audit_event_subject_complete CHECK (
        (subject_type IS NULL AND subject_id IS NULL)
        OR (subject_type IS NOT NULL AND subject_id IS NOT NULL)
    ),
    ADD CONSTRAINT audit_event_authorization_version_positive CHECK (
        authorization_version IS NULL OR authorization_version > 0
    );

CREATE OR REPLACE FUNCTION reject_proposal_content_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.proposal_id, NEW.revision_number, NEW.ticket_id, NEW.order_reference,
           NEW.generation_id, NEW.delay_hours, NEW.delay_seconds, NEW.compensation_method, NEW.amount,
           NEW.reason_code, NEW.evidence_references, NEW.policy_version,
           NEW.content_digest, NEW.created_at, NEW.expires_at)
       IS DISTINCT FROM
       ROW(OLD.proposal_id, OLD.revision_number, OLD.ticket_id, OLD.order_reference,
           OLD.generation_id, OLD.delay_hours, OLD.delay_seconds, OLD.compensation_method, OLD.amount,
           OLD.reason_code, OLD.evidence_references, OLD.policy_version,
           OLD.content_digest, OLD.created_at, OLD.expires_at) THEN
        RAISE EXCEPTION 'compensation proposal revision content is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE approval_lease (
    id uuid PRIMARY KEY,
    proposal_revision_id uuid NOT NULL REFERENCES compensation_proposal_revision(id),
    approver_id text NOT NULL,
    lease_token uuid NOT NULL UNIQUE,
    lease_version bigint NOT NULL CHECK (lease_version > 0),
    status text NOT NULL CHECK (status IN ('ACTIVE', 'EXPIRED', 'RELEASED', 'REVOKED')),
    claimed_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > claimed_at),
    released_at timestamptz,
    UNIQUE (proposal_revision_id, lease_version)
);

CREATE UNIQUE INDEX one_active_approval_lease_per_revision
    ON approval_lease (proposal_revision_id) WHERE status = 'ACTIVE';

CREATE TABLE approval_claim_request (
    approver_id text NOT NULL,
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    proposal_revision_id uuid NOT NULL REFERENCES compensation_proposal_revision(id),
    lease_id uuid NOT NULL UNIQUE REFERENCES approval_lease(id),
    lease_token uuid NOT NULL,
    lease_version bigint NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (approver_id, request_id),
    FOREIGN KEY (proposal_revision_id, lease_version)
        REFERENCES approval_lease(proposal_revision_id, lease_version)
);

CREATE TABLE approval_release_request (
    approver_id text NOT NULL,
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    proposal_revision_id uuid NOT NULL REFERENCES compensation_proposal_revision(id),
    lease_token uuid NOT NULL,
    lease_version bigint NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (approver_id, request_id),
    FOREIGN KEY (proposal_revision_id, lease_version)
        REFERENCES approval_lease(proposal_revision_id, lease_version)
);

CREATE FUNCTION revoke_approval_lease_when_proposal_invalidated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'PENDING_APPROVAL' AND NEW.status <> 'PENDING_APPROVAL' THEN
        UPDATE approval_lease SET status = 'REVOKED'
        WHERE proposal_revision_id = NEW.id AND status = 'ACTIVE';
        IF FOUND THEN
            INSERT INTO audit_event (
                ticket_id, event_type, actor_id, occurred_at,
                subject_type, subject_id, authorization_version
            )
            SELECT NEW.ticket_id, 'APPROVAL_LEASE_REVOKED', 'spring-system', current_timestamp,
                   'COMPENSATION_PROPOSAL_REVISION', NEW.id, max(lease_version)
            FROM approval_lease WHERE proposal_revision_id = NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER revoke_approval_lease_on_proposal_status_change
AFTER UPDATE OF status ON compensation_proposal_revision
FOR EACH ROW EXECUTE FUNCTION revoke_approval_lease_when_proposal_invalidated();

GRANT SELECT, INSERT, UPDATE ON approval_lease, approval_claim_request, approval_release_request TO spring_app;
