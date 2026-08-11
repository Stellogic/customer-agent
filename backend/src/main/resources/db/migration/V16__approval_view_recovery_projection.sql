CREATE TABLE approval_view_event (
    proposal_revision_id uuid NOT NULL REFERENCES compensation_proposal_revision(id),
    lease_version bigint NOT NULL CHECK (lease_version > 0),
    sequence bigint NOT NULL CHECK (sequence > 0),
    epoch text NOT NULL CHECK (epoch = 'approval-view-v1'),
    event_type text NOT NULL CHECK (event_type IN ('APPROVAL_AUTHORITY_STARTED', 'APPROVAL_AUTHORITY_ENDED')),
    authority_state text NOT NULL CHECK (authority_state IN ('ACTIVE', 'EXPIRED', 'RELEASED', 'REVOKED', 'DECIDED')),
    occurred_at timestamptz NOT NULL,
    PRIMARY KEY (proposal_revision_id, lease_version, sequence),
    FOREIGN KEY (proposal_revision_id, lease_version)
        REFERENCES approval_lease(proposal_revision_id, lease_version)
);

CREATE FUNCTION publish_approval_view_authority() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    next_sequence bigint;
BEGIN
    SELECT coalesce(max(sequence), 0) + 1 INTO next_sequence
    FROM approval_view_event
    WHERE proposal_revision_id = NEW.proposal_revision_id AND lease_version = NEW.lease_version;
    INSERT INTO approval_view_event (
        proposal_revision_id, lease_version, sequence, epoch, event_type, authority_state, occurred_at
    ) VALUES (
        NEW.proposal_revision_id,
        NEW.lease_version,
        next_sequence,
        'approval-view-v1',
        CASE WHEN NEW.status = 'ACTIVE' THEN 'APPROVAL_AUTHORITY_STARTED' ELSE 'APPROVAL_AUTHORITY_ENDED' END,
        NEW.status,
        coalesce(NEW.decided_at, NEW.released_at, current_timestamp)
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER publish_approval_view_authority_insert
AFTER INSERT ON approval_lease
FOR EACH ROW EXECUTE FUNCTION publish_approval_view_authority();

CREATE TRIGGER publish_approval_view_authority_update
AFTER UPDATE OF status ON approval_lease
FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION publish_approval_view_authority();

INSERT INTO approval_view_event (
    proposal_revision_id, lease_version, sequence, epoch, event_type, authority_state, occurred_at
)
SELECT proposal_revision_id, lease_version, 1, 'approval-view-v1',
       CASE WHEN status = 'ACTIVE' THEN 'APPROVAL_AUTHORITY_STARTED' ELSE 'APPROVAL_AUTHORITY_ENDED' END,
       status, coalesce(decided_at, released_at, claimed_at)
FROM approval_lease;

GRANT SELECT, INSERT ON approval_view_event TO spring_app;
