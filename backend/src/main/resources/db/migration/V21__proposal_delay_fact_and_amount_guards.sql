ALTER TABLE synthetic_order
    ADD CONSTRAINT synthetic_order_delay_representations_consistent
        CHECK (delay_hours = delay_seconds / 3600);

ALTER TABLE compensation_proposal_revision
    ADD CONSTRAINT compensation_proposal_delay_representations_consistent
        CHECK (delay_hours = delay_seconds / 3600),
    ADD CONSTRAINT compensation_proposal_revision_delay_identity
        UNIQUE (id, delay_hours, delay_seconds);

ALTER TABLE approval_evidence_snapshot
    DROP CONSTRAINT approval_evidence_snapshot_proposal_revision_id_fkey,
    ADD CONSTRAINT approval_evidence_delay_representations_consistent
        CHECK (delay_hours = delay_seconds / 3600),
    ADD CONSTRAINT approval_evidence_proposal_delay_fkey
        FOREIGN KEY (proposal_revision_id, delay_hours, delay_seconds)
        REFERENCES compensation_proposal_revision (id, delay_hours, delay_seconds);

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-DELAY-ZERO-PAID', 'customer-demo', 0.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 0.00),
    ('ORDER-DELAY-ROUNDING-ZERO', 'customer-demo', 0.04, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 0.04);
