ALTER TABLE support_ticket
    ADD COLUMN resolved_at timestamptz,
    ADD COLUMN close_due_at timestamptz,
    ADD COLUMN closed_at timestamptz,
    ADD COLUMN close_reason text CHECK (close_reason IS NULL OR close_reason = 'WAITING_PERIOD_EXPIRED'),
    ADD COLUMN follow_up_of uuid REFERENCES support_ticket(id),
    ADD COLUMN issue_kind text NOT NULL DEFAULT 'LOGISTICS_DELAY'
        CHECK (issue_kind IN ('LOGISTICS_DELAY', 'OTHER')),
    ADD CONSTRAINT support_ticket_not_its_own_follow_up CHECK (follow_up_of IS NULL OR follow_up_of <> id);

WITH resolution AS (
    SELECT ticket_id, max(occurred_at) AS occurred_at
    FROM (
        SELECT ticket_id, occurred_at FROM audit_event WHERE event_type = 'TICKET_RESOLVED'
        UNION ALL
        SELECT ticket_id, occurred_at FROM customer_public_event WHERE event_type = 'TICKET_RESOLVED'
    ) evidence
    GROUP BY ticket_id
)
UPDATE support_ticket ticket
SET resolved_at = resolution.occurred_at,
    close_due_at = resolution.occurred_at + interval '72 hours'
FROM resolution
WHERE ticket.id = resolution.ticket_id AND ticket.lifecycle_state IN ('RESOLVED', 'CLOSED');

WITH closure AS (
    SELECT ticket_id, max(occurred_at) AS occurred_at
    FROM (
        SELECT ticket_id, occurred_at FROM audit_event WHERE event_type = 'TICKET_CLOSED'
        UNION ALL
        SELECT ticket_id, occurred_at FROM customer_public_event WHERE event_type = 'TICKET_CLOSED'
    ) evidence
    GROUP BY ticket_id
)
UPDATE support_ticket ticket
SET closed_at = closure.occurred_at,
    close_reason = 'WAITING_PERIOD_EXPIRED'
FROM closure
WHERE ticket.id = closure.ticket_id AND ticket.lifecycle_state = 'CLOSED';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM support_ticket
        WHERE lifecycle_state IN ('RESOLVED', 'CLOSED') AND resolved_at IS NULL
    ) THEN
        RAISE EXCEPTION 'cannot infer historical resolved_at without a TICKET_RESOLVED audit or public event';
    END IF;
    IF EXISTS (
        SELECT 1 FROM support_ticket WHERE lifecycle_state = 'CLOSED' AND closed_at IS NULL
    ) THEN
        RAISE EXCEPTION 'cannot infer historical closed_at without a TICKET_CLOSED audit or public event';
    END IF;
END;
$$;

ALTER TABLE support_ticket ADD CONSTRAINT support_ticket_closure_timestamps_check CHECK (
    (lifecycle_state = 'RESOLVED' AND resolved_at IS NOT NULL AND close_due_at = resolved_at + interval '72 hours'
        AND closed_at IS NULL AND close_reason IS NULL)
    OR (lifecycle_state = 'CLOSED' AND resolved_at IS NOT NULL AND close_due_at = resolved_at + interval '72 hours'
        AND closed_at IS NOT NULL AND closed_at >= close_due_at AND close_reason = 'WAITING_PERIOD_EXPIRED')
    OR (lifecycle_state NOT IN ('RESOLVED', 'CLOSED') AND resolved_at IS NULL AND close_due_at IS NULL
        AND closed_at IS NULL AND close_reason IS NULL)
);

CREATE INDEX due_ticket_closure ON support_ticket (close_due_at)
    WHERE lifecycle_state = 'RESOLVED';

CREATE TABLE customer_reply_request (
    customer_id text NOT NULL,
    message_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    original_ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    result_ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    outcome text NOT NULL CHECK (outcome IN ('REOPENED', 'LINKED_TICKET_CREATED')),
    received_at timestamptz NOT NULL,
    PRIMARY KEY (customer_id, message_id)
);

ALTER TABLE shared_support_queue_entry DROP CONSTRAINT shared_support_queue_entry_reason_code_check;
ALTER TABLE shared_support_queue_entry ADD CONSTRAINT shared_support_queue_entry_reason_code_check
    CHECK (reason_code IN (
        'SLA_BREACH', 'CUSTOMER_REQUESTED_HANDOFF', 'AGENT_HUMAN_HANDOFF',
        'APPROVAL_REJECTED_HANDOFF', 'UNSUPPORTED_ISSUE'
    ));

ALTER TABLE customer_public_event DROP CONSTRAINT customer_public_event_event_type_check;
ALTER TABLE customer_public_event ADD CONSTRAINT customer_public_event_event_type_check
    CHECK (event_type IN (
        'TICKET_ACCEPTED', 'PUBLIC_MESSAGE_APPENDED', 'TICKET_RESOLVED',
        'CUSTOMER_CLARIFICATION_REQUESTED', 'TICKET_INVESTIGATION_RESUMED',
        'TICKET_HANDED_OFF', 'TICKET_REOPENED', 'TICKET_CLOSED'
    ));

CREATE OR REPLACE FUNCTION validate_customer_public_event_payload() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    allowed_keys text[];
BEGIN
    IF NEW.agent_generation = 0 THEN
        SELECT coalesce(max(generation_number), 0)
        INTO NEW.agent_generation
        FROM agent_processing_generation
        WHERE ticket_id = NEW.ticket_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM agent_processing_generation
        WHERE ticket_id = NEW.ticket_id AND generation_number = NEW.agent_generation
    ) THEN
        RAISE EXCEPTION 'customer public event generation is not scoped to the ticket';
    END IF;
    IF jsonb_typeof(NEW.payload) <> 'object' THEN
        RAISE EXCEPTION 'customer public payload must be an object';
    END IF;

    allowed_keys := CASE NEW.event_type
        WHEN 'TICKET_ACCEPTED' THEN ARRAY['ticketId', 'lifecycleState', 'handlingMode']
        WHEN 'PUBLIC_MESSAGE_APPENDED' THEN ARRAY['author', 'body', 'sentAt']
        WHEN 'TICKET_RESOLVED' THEN ARRAY['lifecycleState']
        WHEN 'CUSTOMER_CLARIFICATION_REQUESTED' THEN ARRAY['lifecycleState', 'clarification']
        WHEN 'TICKET_INVESTIGATION_RESUMED' THEN ARRAY['lifecycleState', 'clarification']
        WHEN 'TICKET_HANDED_OFF' THEN ARRAY['handlingMode', 'clarification']
        WHEN 'TICKET_REOPENED' THEN ARRAY['lifecycleState']
        WHEN 'TICKET_CLOSED' THEN ARRAY['lifecycleState']
        ELSE NULL
    END;
    IF allowed_keys IS NULL OR EXISTS (
        SELECT 1 FROM jsonb_object_keys(NEW.payload) AS payload_key
        WHERE payload_key <> ALL (allowed_keys)
    ) THEN
        RAISE EXCEPTION 'customer public payload contains an unknown or internal field';
    END IF;
    IF NEW.payload::text ~* '"(reasoning|checkpoint|token|thread|run|trace|approval|rawModel|rawTool)"[[:space:]]*:' THEN
        RAISE EXCEPTION 'customer public payload contains a sensitive field';
    END IF;
    IF NEW.event_type = 'PUBLIC_MESSAGE_APPENDED' AND NOT (
        NEW.payload ?& ARRAY['author', 'body', 'sentAt']
        AND NEW.payload->>'author' IN ('CUSTOMER', 'SUPPORT', 'AGENT')
        AND jsonb_typeof(NEW.payload->'body') = 'string'
        AND jsonb_typeof(NEW.payload->'sentAt') = 'string'
    ) THEN
        RAISE EXCEPTION 'invalid public message payload';
    END IF;
    IF NEW.event_type = 'PUBLIC_MESSAGE_APPENDED' AND NEW.payload->>'author' = 'AGENT'
       AND NOT EXISTS (
        SELECT 1
        FROM agent_processing_generation g
        JOIN support_ticket t ON t.id = g.ticket_id
        WHERE g.ticket_id = NEW.ticket_id
          AND g.generation_number = NEW.agent_generation
          AND g.status IN ('ACTIVE', 'COMPLETED')
          AND g.generation_number = (
              SELECT max(current_generation.generation_number)
              FROM agent_processing_generation current_generation
              WHERE current_generation.ticket_id = NEW.ticket_id
          )
          AND t.handling_mode = 'AGENT'
          AND NOT t.customer_human_preference
    ) THEN
        RAISE EXCEPTION 'stale agent generation cannot enter the customer public projection';
    END IF;
    IF NEW.event_type IN ('CUSTOMER_CLARIFICATION_REQUESTED', 'TICKET_INVESTIGATION_RESUMED')
       AND NEW.payload->'clarification' IS DISTINCT FROM 'null'::jsonb AND NOT (
        jsonb_typeof(NEW.payload->'clarification') = 'object'
        AND NEW.payload->'clarification' ?& ARRAY['id', 'promptCode', 'question']
        AND NOT EXISTS (
            SELECT 1 FROM jsonb_object_keys(NEW.payload->'clarification') AS clarification_key
            WHERE clarification_key <> ALL (ARRAY['id', 'promptCode', 'question'])
        )
    ) THEN
        RAISE EXCEPTION 'invalid public clarification payload';
    END IF;
    RETURN NEW;
END;
$$;

GRANT SELECT, INSERT ON customer_reply_request TO spring_app;
