ALTER TABLE approval_evidence_snapshot
    RENAME COLUMN available_compensation_amount TO remaining_available_compensation_amount;

ALTER TABLE approval_evidence_snapshot
    ADD COLUMN total_available_compensation_amount numeric(12, 2);

ALTER TABLE approval_evidence_snapshot
    DISABLE TRIGGER approval_evidence_snapshot_immutable;

UPDATE approval_evidence_snapshot
SET total_available_compensation_amount =
    remaining_available_compensation_amount + active_reservation_amount;

ALTER TABLE approval_evidence_snapshot
    ENABLE TRIGGER approval_evidence_snapshot_immutable;

ALTER TABLE approval_evidence_snapshot
    ALTER COLUMN total_available_compensation_amount SET NOT NULL,
    ADD CONSTRAINT approval_evidence_total_available_nonnegative
        CHECK (total_available_compensation_amount >= 0),
    ADD CONSTRAINT approval_evidence_active_reservation_nonnegative
        CHECK (active_reservation_amount >= 0),
    ADD CONSTRAINT approval_evidence_remaining_available_nonnegative
        CHECK (remaining_available_compensation_amount >= 0),
    ADD CONSTRAINT approval_evidence_allowance_components_consistent
        CHECK (
            remaining_available_compensation_amount + active_reservation_amount
                = total_available_compensation_amount
        );

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-DELAY-APPROVAL-RESERVED', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00);

INSERT INTO compensation_reservation (
    id, order_reference, amount, status, created_at
) VALUES
    ('19000000-0000-0000-0000-000000000001',
     'ORDER-DELAY-APPROVAL-RESERVED', 10.00, 'ACTIVE', '2026-08-09T13:00:00Z');
