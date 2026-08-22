CREATE TABLE compensation_proposal_revision_support_participant (
    proposal_revision_id uuid NOT NULL REFERENCES compensation_proposal_revision(id),
    support_id text NOT NULL CHECK (btrim(support_id) <> ''),
    first_participated_at timestamptz NOT NULL,
    PRIMARY KEY (proposal_revision_id, support_id)
);

CREATE INDEX compensation_proposal_revision_participant_by_support
    ON compensation_proposal_revision_support_participant (support_id, proposal_revision_id);

-- Existing audit facts are the only deterministic source for historical content participation.
-- Assignment or ticket access is deliberately not used because neither means that the support
-- worker created, changed, or submitted proposal content.
INSERT INTO compensation_proposal_revision_support_participant (
    proposal_revision_id, support_id, first_participated_at
)
SELECT subject_id, actor_id, min(occurred_at)
FROM audit_event
WHERE subject_type = 'COMPENSATION_PROPOSAL_REVISION'
  AND event_type IN (
      'COMPENSATION_PROPOSAL_REVISION_CREATED_BY_SUPPORT',
      'COMPENSATION_PROPOSAL_REVISION_MODIFIED_BY_SUPPORT',
      'COMPENSATION_PROPOSAL_REVISION_SUBMITTED_BY_SUPPORT'
  )
GROUP BY subject_id, actor_id
ON CONFLICT DO NOTHING;

-- Every later revision of the same proposal inherits every earlier revision's participants.
-- A distinct proposal_id is an independent proposal and therefore starts a new set.
INSERT INTO compensation_proposal_revision_support_participant (
    proposal_revision_id, support_id, first_participated_at
)
SELECT child.id, participant.support_id, min(participant.first_participated_at)
FROM compensation_proposal_revision child
JOIN compensation_proposal_revision ancestor
  ON ancestor.proposal_id = child.proposal_id
 AND ancestor.revision_number < child.revision_number
JOIN compensation_proposal_revision_support_participant participant
  ON participant.proposal_revision_id = ancestor.id
GROUP BY child.id, participant.support_id
ON CONFLICT DO NOTHING;

-- Preserve lease rows while terminating any active authority that the deterministic backfill
-- has proved belongs to a participant.
UPDATE approval_lease lease
SET status = 'REVOKED'
WHERE lease.status = 'ACTIVE'
  AND EXISTS (
      SELECT 1
      FROM compensation_proposal_revision_support_participant participant
      WHERE participant.proposal_revision_id = lease.proposal_revision_id
        AND participant.support_id = lease.approver_id
  );

CREATE FUNCTION inherit_proposal_revision_support_participants() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Serialize every revision derivation and participant append in one proposal lineage.
    PERFORM pg_advisory_xact_lock(hashtextextended(
        NEW.proposal_id::text || E'\nPROPOSAL_SUPPORT_PARTICIPANT_LINEAGE', 0));
    INSERT INTO compensation_proposal_revision_support_participant (
        proposal_revision_id, support_id, first_participated_at
    )
    SELECT NEW.id, participant.support_id, min(participant.first_participated_at)
    FROM compensation_proposal_revision ancestor
    JOIN compensation_proposal_revision_support_participant participant
      ON participant.proposal_revision_id = ancestor.id
    WHERE ancestor.proposal_id = NEW.proposal_id
      AND ancestor.revision_number < NEW.revision_number
    GROUP BY participant.support_id
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE TRIGGER inherit_proposal_revision_support_participants_on_insert
AFTER INSERT ON compensation_proposal_revision
FOR EACH ROW EXECUTE FUNCTION inherit_proposal_revision_support_participants();

CREATE FUNCTION record_proposal_revision_support_participation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.subject_type = 'COMPENSATION_PROPOSAL_REVISION'
       AND NEW.event_type IN (
           'COMPENSATION_PROPOSAL_REVISION_CREATED_BY_SUPPORT',
           'COMPENSATION_PROPOSAL_REVISION_MODIFIED_BY_SUPPORT',
           'COMPENSATION_PROPOSAL_REVISION_SUBMITTED_BY_SUPPORT'
       ) THEN
        -- Append the fact to the edited revision and every already-derived descendant. The
        -- proposal-level lock pairs with the revision-insert trigger: whichever transaction
        -- wins, the child either inherits this fact or is deterministically backfilled here.
        INSERT INTO compensation_proposal_revision_support_participant (
            proposal_revision_id, support_id, first_participated_at
        )
        SELECT descendant.id, NEW.actor_id, NEW.occurred_at
        FROM compensation_proposal_revision source
        JOIN compensation_proposal_revision descendant
          ON descendant.proposal_id = source.proposal_id
         AND descendant.revision_number >= source.revision_number
        WHERE source.id = NEW.subject_id
        ON CONFLICT (proposal_revision_id, support_id) DO UPDATE
        SET first_participated_at = least(
            compensation_proposal_revision_support_participant.first_participated_at,
            EXCLUDED.first_participated_at
        );
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER record_proposal_revision_support_participation_from_audit
AFTER INSERT ON audit_event
FOR EACH ROW EXECUTE FUNCTION record_proposal_revision_support_participation();

CREATE FUNCTION fence_proposal_revision_support_participant() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    participant_proposal_id uuid;
BEGIN
    SELECT proposal_id INTO STRICT participant_proposal_id
    FROM compensation_proposal_revision
    WHERE id = NEW.proposal_revision_id;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        participant_proposal_id::text || E'\nPROPOSAL_SUPPORT_PARTICIPANT_LINEAGE', 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        NEW.proposal_revision_id::text || E'\nPROPOSAL_REVISION_SUPPORT_PARTICIPANT', 0));
    -- Serialize participant changes with claim and decision transactions on the revision row.
    PERFORM id FROM compensation_proposal_revision
    WHERE id = NEW.proposal_revision_id
    FOR UPDATE;

    UPDATE approval_lease
    SET status = 'REVOKED'
    WHERE proposal_revision_id = NEW.proposal_revision_id
      AND approver_id = NEW.support_id
      AND status = 'ACTIVE';
    RETURN NEW;
END;
$$;

CREATE TRIGGER fence_proposal_revision_support_participant_on_insert
BEFORE INSERT ON compensation_proposal_revision_support_participant
FOR EACH ROW EXECUTE FUNCTION fence_proposal_revision_support_participant();

CREATE FUNCTION reject_support_participant_approval_lease() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'ACTIVE' AND EXISTS (
        SELECT 1
        FROM compensation_proposal_revision_support_participant participant
        WHERE participant.proposal_revision_id = NEW.proposal_revision_id
          AND participant.support_id = NEW.approver_id
    ) THEN
        RAISE EXCEPTION 'proposal revision support participant cannot hold an approval lease'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'approval_lease_support_participant_separation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER reject_support_participant_approval_lease_write
BEFORE INSERT OR UPDATE OF status, approver_id, proposal_revision_id ON approval_lease
FOR EACH ROW EXECUTE FUNCTION reject_support_participant_approval_lease();

CREATE FUNCTION reject_support_participant_proposal_decision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM compensation_proposal_revision_support_participant participant
        WHERE participant.proposal_revision_id = NEW.proposal_revision_id
          AND participant.support_id = NEW.approver_id
    ) THEN
        RAISE EXCEPTION 'proposal revision support participant cannot decide the proposal'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'proposal_decision_support_participant_separation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER reject_support_participant_proposal_decision_insert
BEFORE INSERT ON proposal_decision
FOR EACH ROW EXECUTE FUNCTION reject_support_participant_proposal_decision();

GRANT SELECT, INSERT ON compensation_proposal_revision_support_participant TO spring_app;
GRANT UPDATE (first_participated_at)
    ON compensation_proposal_revision_support_participant TO spring_app;
GRANT SELECT, INSERT ON compensation_proposal_revision_support_participant TO spring_fixture;
