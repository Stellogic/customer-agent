ALTER TABLE support_workbench_event DROP CONSTRAINT support_workbench_event_epoch_check;
ALTER TABLE support_workbench_event ADD CONSTRAINT support_workbench_event_epoch_check
    CHECK (epoch IN ('support-workbench-v1', 'support-workbench-v2'));

ALTER TABLE support_workbench_event ADD COLUMN epoch_sequence bigint;

UPDATE support_workbench_event
SET epoch_sequence = sequence;

ALTER TABLE support_workbench_event ALTER COLUMN epoch_sequence SET NOT NULL;
CREATE UNIQUE INDEX support_workbench_event_epoch_sequence_key
    ON support_workbench_event (epoch, epoch_sequence);

CREATE TABLE support_workbench_epoch_cursor (
    epoch text PRIMARY KEY CHECK (epoch IN ('support-workbench-v1', 'support-workbench-v2')),
    sequence bigint NOT NULL CHECK (sequence >= 0)
);

INSERT INTO support_workbench_epoch_cursor (epoch, sequence)
VALUES
    (
        'support-workbench-v1',
        coalesce((
            SELECT max(epoch_sequence) FROM support_workbench_event
            WHERE epoch = 'support-workbench-v1'
        ), 0)
    ),
    (
        'support-workbench-v2',
        coalesce((
            SELECT max(epoch_sequence) FROM support_workbench_event
            WHERE epoch = 'support-workbench-v2'
        ), 0)
    );

CREATE FUNCTION assign_support_workbench_epoch_sequence() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.epoch_sequence IS NULL THEN
        UPDATE support_workbench_epoch_cursor
        SET sequence = sequence + 1
        WHERE epoch = NEW.epoch
        RETURNING sequence INTO NEW.epoch_sequence;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER assign_support_workbench_epoch_sequence
BEFORE INSERT ON support_workbench_event
FOR EACH ROW EXECUTE FUNCTION assign_support_workbench_epoch_sequence();

GRANT SELECT, UPDATE ON support_workbench_epoch_cursor TO spring_app;
GRANT SELECT ON support_workbench_epoch_cursor TO spring_fixture;

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
    IF NEW.event_type = 'QUEUE_TICKET_UPSERTED' AND NEW.epoch = 'support-workbench-v2' AND (
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
    IF NEW.event_type = 'QUEUE_TICKET_UPSERTED' AND NEW.epoch = 'support-workbench-v1' AND (
        NOT (NEW.payload ?& ARRAY[
            'ticketId', 'lifecycleState', 'handlingMode', 'sharedEnteredAt', 'escalationEnteredAt'
        ])
        OR EXISTS (
            SELECT 1 FROM jsonb_object_keys(NEW.payload) key
            WHERE key <> ALL (ARRAY[
                'ticketId', 'lifecycleState', 'handlingMode',
                'sharedEnteredAt', 'escalationEnteredAt'
            ])
        )
        OR jsonb_typeof(NEW.payload->'lifecycleState') <> 'string'
        OR jsonb_typeof(NEW.payload->'handlingMode') <> 'string'
        OR jsonb_typeof(NEW.payload->'sharedEnteredAt') NOT IN ('string', 'null')
        OR jsonb_typeof(NEW.payload->'escalationEnteredAt') NOT IN ('string', 'null')
    ) THEN
        RAISE EXCEPTION 'invalid legacy support queue summary payload';
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
            'support-workbench-v1',
            'QUEUE_TICKET_REMOVED',
            jsonb_build_object('ticketId', changed_ticket_id::text),
            changed_at
        );
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
            'support-workbench-v1',
            'QUEUE_TICKET_UPSERTED',
            jsonb_build_object(
                'ticketId', changed_ticket_id::text,
                'lifecycleState', ticket_row.lifecycle_state,
                'handlingMode', ticket_row.handling_mode,
                'sharedEnteredAt', shared_entered,
                'escalationEnteredAt', escalation_entered
            ),
            changed_at
        );
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
