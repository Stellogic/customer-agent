ALTER TABLE support_workbench_event DROP CONSTRAINT support_workbench_event_epoch_check;
ALTER TABLE support_workbench_event ADD CONSTRAINT support_workbench_event_epoch_check
    CHECK (epoch IN ('support-workbench-v1', 'support-workbench-v2'));

CREATE OR REPLACE FUNCTION validate_support_workbench_event_payload() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF jsonb_typeof(NEW.payload) <> 'object'
       OR NOT (NEW.payload ? 'ticketId')
       OR jsonb_typeof(NEW.payload->'ticketId') <> 'string' THEN
        RAISE EXCEPTION 'support workbench payload must identify one ticket';
    END IF;
    IF NEW.event_type = 'QUEUE_TICKET_REMOVED' AND EXISTS (
        SELECT 1 FROM jsonb_object_keys(NEW.payload) key WHERE key <> 'ticketId'
    ) THEN
        RAISE EXCEPTION 'removed queue payload contains an unknown field';
    END IF;
    IF NEW.event_type = 'QUEUE_TICKET_UPSERTED' AND (
        NOT (NEW.payload ?& ARRAY[
            'ticketId', 'orderReference', 'issueKind', 'lifecycleState', 'handlingMode',
            'sharedEnteredAt', 'escalationEnteredAt'
        ])
        OR EXISTS (
            SELECT 1 FROM jsonb_object_keys(NEW.payload) key
            WHERE key <> ALL (ARRAY[
                'ticketId', 'orderReference', 'issueKind', 'lifecycleState', 'handlingMode',
                'sharedEnteredAt', 'escalationEnteredAt'
            ])
        )
        OR jsonb_typeof(NEW.payload->'orderReference') <> 'string'
        OR jsonb_typeof(NEW.payload->'issueKind') <> 'string'
        OR jsonb_typeof(NEW.payload->'lifecycleState') <> 'string'
        OR jsonb_typeof(NEW.payload->'handlingMode') <> 'string'
        OR jsonb_typeof(NEW.payload->'sharedEnteredAt') NOT IN ('string', 'null')
        OR jsonb_typeof(NEW.payload->'escalationEnteredAt') NOT IN ('string', 'null')
    ) THEN
        RAISE EXCEPTION 'invalid support queue summary payload';
    END IF;
    IF NEW.payload::text ~* '"(customerId|description|reasonCode|investigation|message|note|audit|reasoning|checkpoint|token|thread|run|trace|approval|rawModel|rawTool)"[[:space:]]*:' THEN
        RAISE EXCEPTION 'support workbench payload contains a sensitive field';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION publish_support_workbench_ticket(
    changed_ticket_id uuid,
    changed_at timestamptz
) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    ticket_row record;
    shared_entered timestamptz;
    escalation_entered timestamptz;
BEGIN
    SELECT order_reference, issue_kind, lifecycle_state, handling_mode INTO ticket_row
    FROM support_ticket WHERE id = changed_ticket_id;
    SELECT min(entered_at), min(entered_at) FILTER (WHERE reason_code = 'SLA_BREACH')
    INTO shared_entered, escalation_entered
    FROM shared_support_queue_entry WHERE ticket_id = changed_ticket_id;

    IF shared_entered IS NULL THEN
        INSERT INTO support_workbench_event (epoch, event_type, payload, occurred_at)
        VALUES (
            'support-workbench-v2',
            'QUEUE_TICKET_REMOVED',
            jsonb_build_object('ticketId', changed_ticket_id::text),
            changed_at
        );
    ELSE
        INSERT INTO support_workbench_event (epoch, event_type, payload, occurred_at)
        VALUES (
            'support-workbench-v2',
            'QUEUE_TICKET_UPSERTED',
            jsonb_build_object(
                'ticketId', changed_ticket_id::text,
                'orderReference', ticket_row.order_reference,
                'issueKind', ticket_row.issue_kind,
                'lifecycleState', ticket_row.lifecycle_state,
                'handlingMode', ticket_row.handling_mode,
                'sharedEnteredAt', shared_entered,
                'escalationEnteredAt', escalation_entered
            ),
            changed_at
        );
    END IF;
END;
$$;

INSERT INTO support_workbench_event (epoch, event_type, payload, occurred_at)
SELECT
    'support-workbench-v2',
    'QUEUE_TICKET_UPSERTED',
    jsonb_build_object(
        'ticketId', q.ticket_id::text,
        'orderReference', t.order_reference,
        'issueKind', t.issue_kind,
        'lifecycleState', t.lifecycle_state,
        'handlingMode', t.handling_mode,
        'sharedEnteredAt', min(q.entered_at),
        'escalationEnteredAt', min(q.entered_at) FILTER (WHERE q.reason_code = 'SLA_BREACH')
    ),
    min(q.entered_at)
FROM shared_support_queue_entry q
JOIN support_ticket t ON t.id = q.ticket_id
GROUP BY q.ticket_id, t.order_reference, t.issue_kind, t.lifecycle_state, t.handling_mode
ORDER BY min(q.entered_at), q.ticket_id;
