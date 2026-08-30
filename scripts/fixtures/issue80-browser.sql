\set ON_ERROR_STOP on

INSERT INTO support_ticket (
    id, customer_id, order_reference, description, lifecycle_state, handling_mode,
    created_at, first_responded_at
) VALUES (
    '80000000-0000-0000-0000-000000000001', 'customer-demo', 'ORDER-DELAY-001',
    'Issue #80 禁止自审派生版本', 'INVESTIGATING', 'AGENT',
    '2026-08-09T13:50:00Z', '2026-08-09T13:51:00Z'
);

INSERT INTO support_ticket (
    id, customer_id, order_reference, description, lifecycle_state, handling_mode,
    created_at, first_responded_at
) VALUES (
    '80000000-0000-0000-0000-000000000009', 'other-customer', 'ORDER-DELAY-OTHER',
    'Issue #80 其他客户不可见工单', 'NEW', 'HUMAN',
    '2026-08-09T13:56:00Z', NULL
);

INSERT INTO shared_support_queue_entry (ticket_id, reason_code, entered_at) VALUES (
    '80000000-0000-0000-0000-000000000009', 'SLA_BREACH', '2026-08-09T13:57:00Z'
);

INSERT INTO agent_processing_generation (
    id, ticket_id, generation_number, thread_id, status, created_at
) VALUES
    ('80000000-0000-0000-0000-000000000002', '80000000-0000-0000-0000-000000000001', 1,
     '80000000-0000-0000-0000-000000000003', 'COMPLETED', '2026-08-09T13:51:00Z'),
    ('80000000-0000-0000-0000-000000000004', '80000000-0000-0000-0000-000000000001', 2,
     '80000000-0000-0000-0000-000000000005', 'ACTIVE', '2026-08-09T13:54:00Z');

INSERT INTO compensation_proposal_revision (
    id, proposal_id, revision_number, ticket_id, order_reference, generation_id,
    delay_hours, delay_seconds, compensation_method, amount, reason_code,
    evidence_references, policy_version, content_digest, status, created_at, expires_at
) VALUES (
    '80000000-0000-0000-0000-000000000006', '80000000-0000-0000-0000-000000000007', 1,
    '80000000-0000-0000-0000-000000000001', 'ORDER-DELAY-001',
    '80000000-0000-0000-0000-000000000002', 80, 288000, 'SIMULATED_PARTIAL_REFUND',
    26.80, 'LOGISTICS_DELAY', '["order:ORDER-DELAY-001","logistics:ORDER-DELAY-001"]',
    'delay-policy-v1', repeat('a', 64), 'SUPERSEDED',
    '2026-08-09T13:52:00Z', '2026-08-10T13:52:00Z'
);

INSERT INTO approval_evidence_snapshot (
    proposal_revision_id, order_reference, delay_hours, delay_seconds, paid_amount,
    total_available_compensation_amount, active_reservation_amount,
    remaining_available_compensation_amount, paid, cancelled, fully_refunded,
    existing_compensation, evidence_references, captured_at
) SELECT
    '80000000-0000-0000-0000-000000000006', order_reference, 80, 288000, paid_amount,
    available_compensation_amount, 0.00, available_compensation_amount,
    paid, cancelled, fully_refunded, existing_compensation,
    '["order:ORDER-DELAY-001","logistics:ORDER-DELAY-001"]', '2026-08-09T13:52:00Z'
FROM synthetic_order WHERE order_reference = 'ORDER-DELAY-001';

INSERT INTO audit_event (
    ticket_id, event_type, actor_id, occurred_at, subject_type, subject_id
) VALUES (
    '80000000-0000-0000-0000-000000000001',
    'COMPENSATION_PROPOSAL_REVISION_CREATED_BY_SUPPORT', 'internal-demo',
    '2026-08-09T13:53:00Z', 'COMPENSATION_PROPOSAL_REVISION',
    '80000000-0000-0000-0000-000000000006'
);

INSERT INTO compensation_proposal_revision (
    id, proposal_id, revision_number, ticket_id, order_reference, generation_id,
    delay_hours, delay_seconds, compensation_method, amount, reason_code,
    evidence_references, policy_version, content_digest, status, created_at, expires_at
) VALUES (
    '80000000-0000-0000-0000-000000000008', '80000000-0000-0000-0000-000000000007', 2,
    '80000000-0000-0000-0000-000000000001', 'ORDER-DELAY-001',
    '80000000-0000-0000-0000-000000000004', 80, 288000, 'SIMULATED_PARTIAL_REFUND',
    26.80, 'LOGISTICS_DELAY', '["order:ORDER-DELAY-001","logistics:ORDER-DELAY-001"]',
    'delay-policy-v1', repeat('b', 64), 'PENDING_APPROVAL',
    '2026-08-09T13:55:00Z', '2026-08-10T13:55:00Z'
);

INSERT INTO approval_evidence_snapshot (
    proposal_revision_id, order_reference, delay_hours, delay_seconds, paid_amount,
    total_available_compensation_amount, active_reservation_amount,
    remaining_available_compensation_amount, paid, cancelled, fully_refunded,
    existing_compensation, evidence_references, captured_at
) SELECT
    '80000000-0000-0000-0000-000000000008', order_reference, 80, 288000, paid_amount,
    available_compensation_amount, 0.00, available_compensation_amount,
    paid, cancelled, fully_refunded, existing_compensation,
    '["order:ORDER-DELAY-001","logistics:ORDER-DELAY-001"]', '2026-08-09T13:55:00Z'
FROM synthetic_order WHERE order_reference = 'ORDER-DELAY-001';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM compensation_proposal_revision_support_participant
        WHERE proposal_revision_id = '80000000-0000-0000-0000-000000000008'
          AND support_id = 'internal-demo'
    ) THEN
        RAISE EXCEPTION 'derived revision did not inherit internal-demo participant';
    END IF;
END $$;
