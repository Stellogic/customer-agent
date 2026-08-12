\set ON_ERROR_STOP on

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('B3-68-BLOCK', 'customer-demo', 268.00, 'CNY', 80, 288000, true, false, false, false, 'delay-policy-v1', 268.00),
    ('B3-68-PROPOSAL', 'customer-demo', 268.00, 'CNY', 80, 288000, true, false, false, false, 'delay-policy-v1', 268.00),
    ('B3-68-LEASE', 'customer-demo', 268.00, 'CNY', 80, 288000, true, false, false, false, 'delay-policy-v1', 268.00);

INSERT INTO support_ticket (
    id, customer_id, order_reference, description, lifecycle_state, handling_mode,
    created_at, first_responded_at
) VALUES
    ('68000000-0000-0000-0000-000000000001', 'customer-demo', 'B3-68-BLOCK', 'B-3 blocker', 'INVESTIGATING', 'AGENT', clock_timestamp(), clock_timestamp()),
    ('68000000-0000-0000-0000-000000000002', 'customer-demo', 'B3-68-PROPOSAL', 'B-3 proposal boundary', 'INVESTIGATING', 'AGENT', clock_timestamp(), clock_timestamp()),
    ('68000000-0000-0000-0000-000000000003', 'customer-demo', 'B3-68-LEASE', 'B-3 lease boundary', 'INVESTIGATING', 'AGENT', clock_timestamp(), clock_timestamp());

INSERT INTO agent_processing_generation (
    id, ticket_id, generation_number, thread_id, status, created_at
) VALUES
    ('68000000-0000-0000-0000-000000000011', '68000000-0000-0000-0000-000000000001', 1, '68000000-0000-0000-0000-000000000021', 'COMPLETED', clock_timestamp()),
    ('68000000-0000-0000-0000-000000000012', '68000000-0000-0000-0000-000000000002', 1, '68000000-0000-0000-0000-000000000022', 'COMPLETED', clock_timestamp()),
    ('68000000-0000-0000-0000-000000000013', '68000000-0000-0000-0000-000000000003', 1, '68000000-0000-0000-0000-000000000023', 'COMPLETED', clock_timestamp());

INSERT INTO compensation_proposal_revision (
    id, proposal_id, revision_number, ticket_id, order_reference, generation_id,
    delay_hours, delay_seconds, compensation_method, amount, reason_code,
    evidence_references, policy_version, content_digest, status, created_at, expires_at
) VALUES
    ('68000000-0000-0000-0000-000000000031', '68000000-0000-0000-0000-000000000041', 1, '68000000-0000-0000-0000-000000000001', 'B3-68-BLOCK', '68000000-0000-0000-0000-000000000011', 80, 288000, 'COUPON', 10.00, 'LOGISTICS_DELAY', '[]', 'delay-policy-v1', repeat('a', 64), 'PENDING_APPROVAL', clock_timestamp(), clock_timestamp() - interval '1 second'),
    ('68000000-0000-0000-0000-000000000032', '68000000-0000-0000-0000-000000000042', 1, '68000000-0000-0000-0000-000000000002', 'B3-68-PROPOSAL', '68000000-0000-0000-0000-000000000012', 80, 288000, 'COUPON', 10.00, 'LOGISTICS_DELAY', '[]', 'delay-policy-v1', repeat('b', 64), 'PENDING_APPROVAL', clock_timestamp(), clock_timestamp() + interval '10 seconds'),
    ('68000000-0000-0000-0000-000000000033', '68000000-0000-0000-0000-000000000043', 1, '68000000-0000-0000-0000-000000000003', 'B3-68-LEASE', '68000000-0000-0000-0000-000000000013', 80, 288000, 'COUPON', 10.00, 'LOGISTICS_DELAY', '[]', 'delay-policy-v1', repeat('c', 64), 'PENDING_APPROVAL', clock_timestamp(), clock_timestamp() + interval '1 minute');

INSERT INTO approval_lease (
    id, proposal_revision_id, approver_id, lease_token, lease_version, status,
    claimed_at, expires_at
) VALUES
    ('68000000-0000-0000-0000-000000000051', '68000000-0000-0000-0000-000000000031', 'approver-demo', '68000000-0000-0000-0000-000000000061', 1, 'ACTIVE', clock_timestamp() - interval '1 minute', clock_timestamp() + interval '1 minute'),
    ('68000000-0000-0000-0000-000000000052', '68000000-0000-0000-0000-000000000033', 'approver-demo', '68000000-0000-0000-0000-000000000062', 1, 'ACTIVE', clock_timestamp() - interval '1 minute', clock_timestamp() + interval '10 seconds');
