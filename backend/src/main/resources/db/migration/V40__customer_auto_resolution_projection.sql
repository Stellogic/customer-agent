ALTER TABLE customer_public_event DROP CONSTRAINT customer_public_event_event_type_check;
ALTER TABLE customer_public_event ADD CONSTRAINT customer_public_event_event_type_check
    CHECK (event_type IN (
        'TICKET_ACCEPTED', 'PUBLIC_MESSAGE_APPENDED', 'TICKET_RESOLVED',
        'CUSTOMER_CLARIFICATION_REQUESTED', 'TICKET_INVESTIGATION_RESUMED',
        'TICKET_HANDED_OFF', 'TICKET_REOPENED', 'TICKET_CLOSED',
        'CUSTOMER_MESSAGE_ACCEPTED', 'AGENT_PROCESSING_TERMINATED',
        'AGENT_PROCESSING_STARTED', 'AGENT_REPLY_LOADING',
        'PUBLIC_PROGRESS_UPDATED', 'AGENT_REPLY_STREAM_STARTED',
        'AGENT_REPLY_CONTENT_DELTA', 'AGENT_REPLY_COMPLETED',
        'AGENT_REPLY_ABORTED', 'AGENT_REPLY_FAILED', 'AUTO_RESOLUTION_CHANGED',
        'COMPENSATION_REVIEW_PENDING', 'COMPENSATION_REVIEW_CLEARED'
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
        WHEN 'AGENT_REPLY_LOADING' THEN ARRAY['status']
        WHEN 'PUBLIC_PROGRESS_UPDATED' THEN ARRAY['stage']
        WHEN 'AGENT_REPLY_STREAM_STARTED' THEN ARRAY['status']
        WHEN 'AGENT_REPLY_CONTENT_DELTA' THEN ARRAY['chunkIndex', 'delta']
        WHEN 'AGENT_REPLY_COMPLETED' THEN ARRAY['status']
        WHEN 'AGENT_REPLY_ABORTED' THEN ARRAY['status']
        WHEN 'AGENT_REPLY_FAILED' THEN ARRAY['status']
        WHEN 'AUTO_RESOLUTION_CHANGED' THEN ARRAY['autoResolution']
        WHEN 'TICKET_RESOLVED' THEN ARRAY['lifecycleState']
        WHEN 'CUSTOMER_CLARIFICATION_REQUESTED' THEN ARRAY['lifecycleState', 'clarification']
        WHEN 'TICKET_INVESTIGATION_RESUMED' THEN ARRAY['lifecycleState', 'clarification']
        WHEN 'TICKET_HANDED_OFF' THEN ARRAY['handlingMode', 'clarification']
        WHEN 'TICKET_REOPENED' THEN ARRAY['lifecycleState']
        WHEN 'TICKET_CLOSED' THEN ARRAY['lifecycleState']
        WHEN 'COMPENSATION_REVIEW_PENDING' THEN ARRAY['compensationMethod', 'amount', 'status']
        WHEN 'COMPENSATION_REVIEW_CLEARED' THEN ARRAY['status']
        ELSE NULL
    END;
    IF allowed_keys IS NULL OR EXISTS (
        SELECT 1 FROM jsonb_object_keys(NEW.payload) AS payload_key
        WHERE payload_key <> ALL (allowed_keys)
    ) THEN
        RAISE EXCEPTION 'customer public payload contains an unknown or internal field';
    END IF;
    IF NEW.payload::text ~* '"(reasoning|checkpoint|token|thread|run|trace|approval|rawModel|rawTool|provider)"[[:space:]]*:' THEN
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
    IF NEW.event_type = 'COMPENSATION_REVIEW_PENDING' AND (
        jsonb_typeof(NEW.payload->'compensationMethod') IS DISTINCT FROM 'string'
        OR NEW.payload->>'compensationMethod' NOT IN ('COUPON', 'SIMULATED_PARTIAL_REFUND')
        OR jsonb_typeof(NEW.payload->'amount') IS DISTINCT FROM 'string'
        OR NEW.payload->>'amount' !~ '^[0-9]+\.[0-9]{2}$'
        OR jsonb_typeof(NEW.payload->'status') IS DISTINCT FROM 'string'
        OR NEW.payload->>'status' <> 'PENDING_REVIEW'
    ) THEN
        RAISE EXCEPTION 'invalid compensation review payload';
    END IF;
    IF NEW.event_type = 'COMPENSATION_REVIEW_CLEARED' AND (
        jsonb_typeof(NEW.payload->'status') IS DISTINCT FROM 'string'
        OR NEW.payload->>'status' NOT IN ('APPROVED', 'REJECTED')
    ) THEN
        RAISE EXCEPTION 'invalid compensation review cleared payload';
    END IF;
    IF NEW.event_type = 'AGENT_REPLY_CONTENT_DELTA' AND NOT (
        NEW.payload ?& ARRAY['chunkIndex', 'delta']
        AND jsonb_typeof(NEW.payload->'chunkIndex') = 'number'
        AND (NEW.payload->>'chunkIndex')::integer >= 0
        AND jsonb_typeof(NEW.payload->'delta') = 'string'
        AND char_length(NEW.payload->>'delta') BETWEEN 1 AND 512
    ) THEN
        RAISE EXCEPTION 'invalid public reply delta';
    END IF;
    IF NEW.event_type = 'PUBLIC_PROGRESS_UPDATED' AND NOT (
        NEW.payload->>'stage' IN ('UNDERSTANDING', 'VERIFYING_FACTS', 'QUERYING_RULES', 'COMPOSING_REPLY')
    ) THEN
        RAISE EXCEPTION 'invalid public progress stage';
    END IF;
    IF NEW.event_type LIKE 'AGENT_REPLY_%' AND NEW.event_type <> 'AGENT_REPLY_CONTENT_DELTA'
       AND NEW.event_type <> 'AGENT_REPLY_STREAM_STARTED' AND NEW.event_type <> 'AGENT_REPLY_LOADING'
       AND NEW.payload->>'status' NOT IN ('COMPLETED', 'ABORTED', 'FAILED') THEN
        RAISE EXCEPTION 'invalid public reply terminal state';
    END IF;
    IF NEW.event_type = 'AGENT_REPLY_LOADING' AND NEW.payload->>'status' <> 'LOADING' THEN
        RAISE EXCEPTION 'invalid public reply loading state';
    END IF;
    IF NEW.event_type = 'AGENT_REPLY_STREAM_STARTED' AND NEW.payload->>'status' <> 'STREAMING' THEN
        RAISE EXCEPTION 'invalid public reply streaming state';
    END IF;
    IF NEW.event_type IN (
        'PUBLIC_MESSAGE_APPENDED', 'AGENT_REPLY_LOADING', 'PUBLIC_PROGRESS_UPDATED',
        'AGENT_REPLY_STREAM_STARTED', 'AGENT_REPLY_CONTENT_DELTA', 'AGENT_REPLY_COMPLETED',
        'AGENT_REPLY_ABORTED', 'AGENT_REPLY_FAILED'
    ) AND (NEW.event_type <> 'PUBLIC_MESSAGE_APPENDED' OR NEW.payload->>'author' = 'AGENT')
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
    IF NEW.event_type = 'AUTO_RESOLUTION_CHANGED' THEN
        IF jsonb_typeof(NEW.payload->'autoResolution') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'invalid auto resolution payload';
        END IF;
        IF NOT (NEW.payload->'autoResolution' ?& ARRAY['status', 'dueAt']) OR EXISTS (
            SELECT 1 FROM jsonb_object_keys(NEW.payload->'autoResolution') AS candidate_key
            WHERE candidate_key <> ALL (ARRAY['status', 'dueAt'])
        ) OR (NEW.payload->'autoResolution'->>'status' IN (
            'PENDING', 'CANCELLED', 'REEVALUATING', 'RESOLVED'
        )) IS NOT TRUE THEN
            RAISE EXCEPTION 'invalid auto resolution payload';
        END IF;
        IF NEW.payload->'autoResolution'->>'status' = 'PENDING' THEN
            IF jsonb_typeof(NEW.payload->'autoResolution'->'dueAt') IS DISTINCT FROM 'string' THEN
                RAISE EXCEPTION 'pending auto resolution requires due time';
            END IF;
            PERFORM (NEW.payload->'autoResolution'->>'dueAt')::timestamptz;
        ELSIF NEW.payload->'autoResolution'->'dueAt' IS DISTINCT FROM 'null'::jsonb THEN
            RAISE EXCEPTION 'inactive auto resolution must not expose a due time';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- 候选更新与公开事件同事务提交；调用方先取得工单权威锁。
CREATE FUNCTION project_customer_auto_resolution() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status IS NOT DISTINCT FROM NEW.status
           AND OLD.due_at IS NOT DISTINCT FROM NEW.due_at
           AND OLD.generation_id IS NOT DISTINCT FROM NEW.generation_id THEN
            RETURN NEW;
        END IF;
    END IF;
    PERFORM 1 FROM support_ticket WHERE id = NEW.ticket_id FOR UPDATE;
    INSERT INTO customer_public_event (
        ticket_id, epoch, sequence, event_type, payload, occurred_at
    )
    SELECT NEW.ticket_id, 'customer-public-v1', coalesce(max(sequence), 0) + 1,
           'AUTO_RESOLUTION_CHANGED', jsonb_build_object(
               'autoResolution', jsonb_build_object(
                   'status', NEW.status,
                   'dueAt', CASE WHEN NEW.status = 'PENDING' THEN NEW.due_at ELSE NULL END
               )
           ), NEW.updated_at
    FROM customer_public_event
    WHERE ticket_id = NEW.ticket_id AND epoch = 'customer-public-v1';
    RETURN NEW;
END;
$$;

CREATE TRIGGER project_customer_auto_resolution
AFTER INSERT OR UPDATE ON ticket_auto_resolution
FOR EACH ROW EXECUTE FUNCTION project_customer_auto_resolution();
