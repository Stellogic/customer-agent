-- #162: deadlines belong to Spring and survive reconnects and process restarts.
CREATE TABLE ticket_auto_resolution (
    ticket_id uuid PRIMARY KEY REFERENCES support_ticket(id),
    generation_id uuid NOT NULL REFERENCES agent_processing_generation(id),
    policy_version text NOT NULL,
    scenario text NOT NULL,
    conclusion jsonb NOT NULL,
    reply_message_id uuid NOT NULL REFERENCES public_message(id),
    customer_message_sequence bigint NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING', 'CANCELLED', 'REEVALUATING', 'RESOLVED')),
    due_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CHECK (due_at = created_at + interval '5 minutes')
);

CREATE INDEX ticket_auto_resolution_due ON ticket_auto_resolution(due_at)
    WHERE status = 'PENDING';
GRANT SELECT, INSERT, UPDATE ON ticket_auto_resolution TO spring_app;

-- Use the existing order allowance lock for authoritative mutations as well as readers.
-- No new write privilege over synthetic order facts is granted to the application.
CREATE FUNCTION serialize_auto_resolution_order_facts() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(OLD.order_reference || E'\nCOMPENSATION_ALLOWANCE', 0));
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(NEW.order_reference || E'\nCOMPENSATION_ALLOWANCE', 0));
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;
CREATE TRIGGER serialize_auto_resolution_order
BEFORE UPDATE OR DELETE ON synthetic_order
FOR EACH ROW EXECUTE FUNCTION serialize_auto_resolution_order_facts();
CREATE TRIGGER serialize_auto_resolution_pending_action
BEFORE INSERT OR UPDATE OR DELETE ON synthetic_pending_action
FOR EACH ROW EXECUTE FUNCTION serialize_auto_resolution_order_facts();
CREATE TRIGGER serialize_auto_resolution_compensation
BEFORE INSERT OR UPDATE OR DELETE ON compensation_proposal_revision
FOR EACH ROW EXECUTE FUNCTION serialize_auto_resolution_order_facts();

ALTER TABLE support_ticket DROP CONSTRAINT support_ticket_handoff_reason_check;
ALTER TABLE support_ticket ADD CONSTRAINT support_ticket_handoff_reason_check CHECK (
    human_handoff_reason_code IS NULL OR human_handoff_reason_code IN (
        'CUSTOMER_REQUESTED', 'CUSTOMER_REQUESTED_HUMAN', 'TOOL_RETRY_EXHAUSTED',
        'FACT_CONFLICT', 'INVALID_MODEL_OUTPUT', 'INVALID_TOOL_RESPONSE',
        'REQUIRED_FACT_MISSING', 'UNSUPPORTED_SCENARIO', 'APPROVAL_REJECTED',
        'LOGISTICS_STALLED', 'PACKAGE_SIGNED_NOT_RECEIVED', 'PACKAGE_SUSPECTED_LOST',
        'DUPLICATE_CHARGE', 'OTHER_REQUIRES_HUMAN', 'FACTS_INSUFFICIENT',
        'ORDER_RULE_EXPLAINED', 'REFUND_STATUS_EXPLAINED', 'DELAY_UNDER_24_HOURS'
    ));
