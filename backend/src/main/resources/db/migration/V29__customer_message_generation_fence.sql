CREATE TABLE customer_public_message_request (
    customer_id text NOT NULL,
    message_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    outcome text NOT NULL CHECK (outcome = 'ACCEPTED'),
    received_at timestamptz NOT NULL,
    PRIMARY KEY (customer_id, message_id)
);

ALTER TABLE customer_public_event DROP CONSTRAINT customer_public_event_event_type_check;
ALTER TABLE customer_public_event ADD CONSTRAINT customer_public_event_event_type_check
    CHECK (event_type IN (
        'TICKET_ACCEPTED', 'PUBLIC_MESSAGE_APPENDED', 'TICKET_RESOLVED',
        'CUSTOMER_CLARIFICATION_REQUESTED', 'TICKET_INVESTIGATION_RESUMED',
        'TICKET_HANDED_OFF', 'TICKET_REOPENED', 'TICKET_CLOSED',
        'CUSTOMER_MESSAGE_ACCEPTED', 'AGENT_PROCESSING_TERMINATED',
        'AGENT_PROCESSING_STARTED'
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
        WHEN 'CUSTOMER_MESSAGE_ACCEPTED' THEN ARRAY['author', 'body', 'sentAt']
        WHEN 'AGENT_PROCESSING_TERMINATED' THEN ARRAY['reason']
        WHEN 'AGENT_PROCESSING_STARTED' THEN ARRAY['state']
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
    IF NEW.event_type IN ('PUBLIC_MESSAGE_APPENDED', 'CUSTOMER_MESSAGE_ACCEPTED') AND NOT (
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

GRANT SELECT, INSERT ON customer_public_message_request TO spring_app;
