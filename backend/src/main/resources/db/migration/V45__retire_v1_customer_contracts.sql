-- Backfill v1 confirmed intakes into the array-based v4 history before removing singular responses.
INSERT INTO shared_intake_record (
    id, intake_id, customer_id, order_reference, original_message,
    customer_confirmation, confirmed_at
)
SELECT gen_random_uuid(), intake.id, intake.customer_id, intake.candidate_order_reference,
       intake.original_message, confirmation.customer_message, intake.confirmed_at
FROM customer_intake intake
JOIN LATERAL (
    SELECT message.customer_message
    FROM customer_intake_message message
    WHERE message.intake_id = intake.id
    ORDER BY message.created_at DESC
    LIMIT 1
) confirmation ON true
WHERE intake.status = 'CONFIRMED'
  AND intake.ticket_id IS NOT NULL
  AND intake.shared_intake_record_id IS NULL;

UPDATE customer_intake intake
SET shared_intake_record_id = record.id
FROM shared_intake_record record
WHERE record.intake_id = intake.id
  AND intake.shared_intake_record_id IS NULL;

INSERT INTO shared_intake_issue (
    id, shared_intake_record_id, ordinal, issue_kind, ticket_id
)
SELECT gen_random_uuid(), intake.shared_intake_record_id, 1, intake.issue_kind, intake.ticket_id
FROM customer_intake intake
WHERE intake.status = 'CONFIRMED'
  AND intake.shared_intake_record_id IS NOT NULL
  AND intake.ticket_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM shared_intake_issue issue
      WHERE issue.shared_intake_record_id = intake.shared_intake_record_id
  );

-- Closed tickets remain selectable duplicate candidates so a confirmed follow-up can
-- preserve the closure domain's linked-ticket semantics.
ALTER TABLE customer_intake_duplicate_match
    DROP CONSTRAINT customer_intake_duplicate_match_lifecycle_state_check;
ALTER TABLE customer_intake_duplicate_match
    ADD CONSTRAINT customer_intake_duplicate_match_lifecycle_state_check
    CHECK (lifecycle_state IN (
        'NEW', 'INVESTIGATING', 'WAITING_FOR_CUSTOMER', 'WAITING_FOR_EXTERNAL',
        'RESOLVED', 'CLOSED'
    ));

-- Preserve customer conversation history while moving the only active epoch to v2.
UPDATE customer_public_event
SET epoch = 'public-conversation-v2'
WHERE epoch = 'customer-public-v1';

ALTER TABLE customer_public_event
    ADD CONSTRAINT customer_public_event_epoch_check
    CHECK (epoch = 'public-conversation-v2');

CREATE OR REPLACE FUNCTION project_customer_auto_resolution() RETURNS trigger
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
    SELECT NEW.ticket_id, 'public-conversation-v2', coalesce(max(sequence), 0) + 1,
           'AUTO_RESOLUTION_CHANGED', jsonb_build_object(
               'autoResolution', jsonb_build_object(
                   'status', NEW.status,
                   'dueAt', CASE WHEN NEW.status = 'PENDING' THEN NEW.due_at ELSE NULL END
               )
           ), NEW.updated_at
    FROM customer_public_event
    WHERE ticket_id = NEW.ticket_id AND epoch = 'public-conversation-v2';
    RETURN NEW;
END;
$$;

-- V28 dual-published v1 and v2. Keep those historical rows for audit, but publish only v2 now.
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
