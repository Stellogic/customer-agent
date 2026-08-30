-- 提案是待审建议，只有批准才预占；已消费与有效预占互斥计入订单额度。
DROP INDEX one_active_logistics_compensation_intent;
CREATE UNIQUE INDEX one_active_ticket_compensation_intent
    ON compensation_proposal_revision (ticket_id)
    WHERE status IN ('PENDING_APPROVAL', 'APPROVED');

ALTER TABLE compensation_execution
    DROP CONSTRAINT compensation_execution_order_reference_reason_code_key;

CREATE VIEW order_compensation_allowance AS
SELECT o.order_reference,
       greatest(o.available_compensation_amount - coalesce(r.consumed_amount, 0), 0)
           AS total_available_compensation_amount,
       coalesce(r.active_amount, 0) AS active_reservation_amount,
       coalesce(r.consumed_amount, 0) AS consumed_amount,
       coalesce(p.pending_amount, 0) AS pending_proposal_amount,
       -- 旧系统仅有布尔补偿事实时仍阻止提案；有金额账本的订单按金额核算。
       o.existing_compensation AND coalesce(r.consumed_amount, 0) = 0
           AS unquantified_existing_compensation
FROM synthetic_order o
LEFT JOIN (
    SELECT order_reference,
           sum(amount) FILTER (WHERE status = 'ACTIVE') AS active_amount,
           sum(amount) FILTER (WHERE status = 'CONSUMED') AS consumed_amount
    FROM compensation_reservation GROUP BY order_reference
) r ON r.order_reference = o.order_reference
LEFT JOIN (
    SELECT order_reference, sum(amount) AS pending_amount
    FROM compensation_proposal_revision
    WHERE status = 'PENDING_APPROVAL'
    GROUP BY order_reference
) p ON p.order_reference = o.order_reference;

GRANT SELECT ON order_compensation_allowance TO spring_app, spring_fixture;

CREATE OR REPLACE FUNCTION lock_authoritative_order(p_order_reference text)
RETURNS TABLE (
    paid_amount numeric(12, 2), available_compensation_amount numeric(12, 2),
    delay_hours integer, delay_seconds bigint, paid boolean, cancelled boolean,
    fully_refunded boolean, existing_compensation boolean, policy_version text
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
BEGIN
    PERFORM 1 FROM public.synthetic_order o
    WHERE o.order_reference = p_order_reference FOR UPDATE;
    RETURN QUERY
    SELECT o.paid_amount, a.total_available_compensation_amount,
           o.delay_hours, o.delay_seconds, o.paid, o.cancelled, o.fully_refunded,
           a.unquantified_existing_compensation, o.policy_version
    FROM public.synthetic_order o
    JOIN public.order_compensation_allowance a USING (order_reference)
    WHERE o.order_reference = p_order_reference;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_compensation_reservation_capacity()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    allowance numeric(12, 2);
    already_committed numeric(12, 2);
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.order_reference || E'\nCOMPENSATION_ALLOWANCE', 0));
    SELECT available_compensation_amount INTO STRICT allowance
    FROM synthetic_order WHERE order_reference = NEW.order_reference;
    IF NEW.status IN ('ACTIVE', 'CONSUMED') THEN
        SELECT coalesce(sum(amount), 0) INTO already_committed
        FROM compensation_reservation
        WHERE order_reference = NEW.order_reference
          AND status IN ('ACTIVE', 'CONSUMED') AND id <> NEW.id;
        IF already_committed + NEW.amount > allowance THEN
            RAISE EXCEPTION 'compensation reservation exceeds available allowance'
                USING ERRCODE = '23514', CONSTRAINT = 'compensation_reservation_capacity';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
