-- Issue #161: multi-problem investigation synthetic authority and issue kinds.

ALTER TABLE synthetic_order
    ADD COLUMN IF NOT EXISTS logistics_status text NOT NULL DEFAULT 'IN_TRANSIT',
    ADD COLUMN IF NOT EXISTS order_rule_summary text NOT NULL DEFAULT 'ADDRESS_CHANGE_AND_CANCEL_RULES_V1',
    ADD COLUMN IF NOT EXISTS duplicate_charge_suspected boolean NOT NULL DEFAULT false;

ALTER TABLE synthetic_order
    DROP CONSTRAINT IF EXISTS synthetic_order_logistics_status_check;

ALTER TABLE synthetic_order
    ADD CONSTRAINT synthetic_order_logistics_status_check
    CHECK (logistics_status IN (
        'IN_TRANSIT',
        'STALLED',
        'SIGNED',
        'SUSPECTED_LOST'
    ));

ALTER TABLE customer_intake DROP CONSTRAINT IF EXISTS customer_intake_issue_kind_check;
ALTER TABLE customer_intake ADD CONSTRAINT customer_intake_issue_kind_check
    CHECK (issue_kind IS NULL OR issue_kind IN (
        'LOGISTICS_DELAY',
        'PACKAGE_NOT_RECEIVED',
        'DUPLICATE_CHARGE',
        'ORDER_OPERATION_OR_RULE',
        'OTHER'
    ));

ALTER TABLE support_ticket DROP CONSTRAINT IF EXISTS support_ticket_issue_kind_check;
ALTER TABLE support_ticket ADD CONSTRAINT support_ticket_issue_kind_check
    CHECK (issue_kind IN (
        'LOGISTICS_DELAY',
        'PACKAGE_NOT_RECEIVED',
        'DUPLICATE_CHARGE',
        'ORDER_OPERATION_OR_RULE',
        'OTHER'
    ));

ALTER TABLE customer_intake_issue DROP CONSTRAINT IF EXISTS customer_intake_issue_issue_kind_check;
ALTER TABLE customer_intake_issue ADD CONSTRAINT customer_intake_issue_issue_kind_check
    CHECK (issue_kind IN (
        'LOGISTICS_DELAY',
        'PACKAGE_NOT_RECEIVED',
        'DUPLICATE_CHARGE',
        'ORDER_OPERATION_OR_RULE',
        'OTHER'
    ));

ALTER TABLE customer_intake_pending_issue DROP CONSTRAINT IF EXISTS customer_intake_pending_issue_issue_kind_check;
ALTER TABLE customer_intake_pending_issue ADD CONSTRAINT customer_intake_pending_issue_issue_kind_check
    CHECK (issue_kind IN (
        'LOGISTICS_DELAY',
        'PACKAGE_NOT_RECEIVED',
        'DUPLICATE_CHARGE',
        'ORDER_OPERATION_OR_RULE',
        'OTHER'
    ));

ALTER TABLE shared_intake_issue DROP CONSTRAINT IF EXISTS shared_intake_issue_issue_kind_check;
ALTER TABLE shared_intake_issue ADD CONSTRAINT shared_intake_issue_issue_kind_check
    CHECK (issue_kind IN (
        'LOGISTICS_DELAY',
        'PACKAGE_NOT_RECEIVED',
        'DUPLICATE_CHARGE',
        'ORDER_OPERATION_OR_RULE',
        'OTHER'
    ));

-- Representative synthetic scenarios for #161 acceptance.
INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount, logistics_status, order_rule_summary, duplicate_charge_suspected
) VALUES
    ('ORDER-STALL-161', 'customer-161', 128.00, 'CNY', 96, 345600, true, false, false, false, 'delay-policy-v1', 20.00, 'STALLED', 'ADDRESS_CHANGE_AND_CANCEL_RULES_V1', false),
    ('ORDER-SIGNED-161', 'customer-161', 88.00, 'CNY', 0, 0, true, false, false, false, 'delay-policy-v1', 20.00, 'SIGNED', 'ADDRESS_CHANGE_AND_CANCEL_RULES_V1', false),
    ('ORDER-LOST-161', 'customer-161', 156.00, 'CNY', 120, 432000, true, false, false, false, 'delay-policy-v1', 20.00, 'SUSPECTED_LOST', 'ADDRESS_CHANGE_AND_CANCEL_RULES_V1', false),
    ('ORDER-DUP-161', 'customer-161', 99.00, 'CNY', 0, 0, true, false, false, false, 'delay-policy-v1', 20.00, 'IN_TRANSIT', 'ADDRESS_CHANGE_AND_CANCEL_RULES_V1', true),
    ('ORDER-REFUND-161', 'customer-161', 64.00, 'CNY', 0, 0, true, false, true, false, 'delay-policy-v1', 0.00, 'IN_TRANSIT', 'ADDRESS_CHANGE_AND_CANCEL_RULES_V1', false),
    ('ORDER-RULE-161', 'customer-161', 210.00, 'CNY', 0, 0, true, false, false, false, 'delay-policy-v1', 20.00, 'IN_TRANSIT', 'ADDRESS_CHANGE_BEFORE_SHIPMENT_CANCEL_BEFORE_PICKUP_V1', false),
    ('ORDER-OTHER-161', 'customer-161', 45.00, 'CNY', 0, 0, true, false, false, false, 'delay-policy-v1', 20.00, 'IN_TRANSIT', 'ADDRESS_CHANGE_AND_CANCEL_RULES_V1', false)
ON CONFLICT (order_reference) DO UPDATE SET
    logistics_status = EXCLUDED.logistics_status,
    order_rule_summary = EXCLUDED.order_rule_summary,
    duplicate_charge_suspected = EXCLUDED.duplicate_charge_suspected,
    delay_hours = EXCLUDED.delay_hours,
    delay_seconds = EXCLUDED.delay_seconds,
    paid = EXCLUDED.paid,
    cancelled = EXCLUDED.cancelled,
    fully_refunded = EXCLUDED.fully_refunded,
    existing_compensation = EXCLUDED.existing_compensation,
    policy_version = EXCLUDED.policy_version,
    available_compensation_amount = EXCLUDED.available_compensation_amount;

ALTER TABLE support_ticket DROP CONSTRAINT IF EXISTS support_ticket_handoff_reason_check;
ALTER TABLE support_ticket ADD CONSTRAINT support_ticket_handoff_reason_check
    CHECK (human_handoff_reason_code IS NULL OR human_handoff_reason_code IN (
        'CUSTOMER_REQUESTED', 'CUSTOMER_REQUESTED_HUMAN', 'TOOL_RETRY_EXHAUSTED',
        'FACT_CONFLICT', 'INVALID_MODEL_OUTPUT', 'INVALID_TOOL_RESPONSE',
        'REQUIRED_FACT_MISSING', 'UNSUPPORTED_SCENARIO', 'APPROVAL_REJECTED',
        'LOGISTICS_STALLED', 'PACKAGE_SIGNED_NOT_RECEIVED', 'PACKAGE_SUSPECTED_LOST',
        'DUPLICATE_CHARGE', 'OTHER_REQUIRES_HUMAN', 'FACTS_INSUFFICIENT',
        'ORDER_RULE_EXPLAINED', 'REFUND_STATUS_EXPLAINED'
    ));
