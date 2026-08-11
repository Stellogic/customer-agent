ALTER TABLE customer_public_event
    ADD COLUMN agent_generation bigint NOT NULL DEFAULT 0 CHECK (agent_generation >= 0);

UPDATE customer_public_event e
SET agent_generation = generation.latest
FROM (
    SELECT ticket_id, max(generation_number) AS latest
    FROM agent_processing_generation
    GROUP BY ticket_id
) generation
WHERE generation.ticket_id = e.ticket_id;

CREATE FUNCTION validate_customer_public_event_payload() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    allowed_keys text[];
BEGIN
    SELECT coalesce(max(generation_number), 0)
    INTO NEW.agent_generation
    FROM agent_processing_generation
    WHERE ticket_id = NEW.ticket_id;
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

CREATE TRIGGER guard_customer_public_event_payload
BEFORE INSERT OR UPDATE ON customer_public_event
FOR EACH ROW EXECUTE FUNCTION validate_customer_public_event_payload();
