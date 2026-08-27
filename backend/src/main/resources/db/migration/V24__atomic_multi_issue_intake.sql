ALTER TABLE customer_intake DROP CONSTRAINT customer_intake_issue_kind_check;
ALTER TABLE customer_intake DROP CONSTRAINT customer_intake_check;
ALTER TABLE customer_intake ADD CONSTRAINT customer_intake_issue_kind_check
    CHECK (issue_kind IS NULL OR issue_kind IN (
        'LOGISTICS_DELAY', 'PACKAGE_NOT_RECEIVED', 'DUPLICATE_CHARGE'
    ));

ALTER TABLE support_ticket DROP CONSTRAINT support_ticket_issue_kind_check;
ALTER TABLE support_ticket ADD CONSTRAINT support_ticket_issue_kind_check
    CHECK (issue_kind IN (
        'LOGISTICS_DELAY', 'PACKAGE_NOT_RECEIVED', 'DUPLICATE_CHARGE', 'OTHER'
    ));

CREATE TABLE customer_intake_issue (
    intake_id uuid NOT NULL REFERENCES customer_intake(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    issue_kind text NOT NULL CHECK (issue_kind IN (
        'LOGISTICS_DELAY', 'PACKAGE_NOT_RECEIVED', 'DUPLICATE_CHARGE'
    )),
    issue_summary text NOT NULL CHECK (length(trim(issue_summary)) > 0),
    PRIMARY KEY (intake_id, ordinal),
    UNIQUE (intake_id, issue_kind)
);

INSERT INTO customer_intake_issue (intake_id, ordinal, issue_kind, issue_summary)
SELECT id, 1, issue_kind, issue_summary
FROM customer_intake
WHERE issue_kind IS NOT NULL AND issue_summary IS NOT NULL;

CREATE TABLE customer_intake_pending_issue (
    intake_id uuid NOT NULL REFERENCES customer_intake(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    issue_kind text NOT NULL CHECK (issue_kind IN (
        'LOGISTICS_DELAY', 'PACKAGE_NOT_RECEIVED', 'DUPLICATE_CHARGE'
    )),
    PRIMARY KEY (intake_id, ordinal),
    UNIQUE (intake_id, issue_kind)
);

CREATE TABLE shared_intake_record (
    id uuid PRIMARY KEY,
    intake_id uuid NOT NULL UNIQUE REFERENCES customer_intake(id),
    customer_id text NOT NULL,
    order_reference text NOT NULL,
    original_message text NOT NULL,
    customer_confirmation text NOT NULL,
    confirmed_at timestamptz NOT NULL
);

CREATE TABLE shared_intake_issue (
    id uuid PRIMARY KEY,
    shared_intake_record_id uuid NOT NULL REFERENCES shared_intake_record(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    issue_kind text NOT NULL CHECK (issue_kind IN (
        'LOGISTICS_DELAY', 'PACKAGE_NOT_RECEIVED', 'DUPLICATE_CHARGE'
    )),
    ticket_id uuid NOT NULL UNIQUE REFERENCES support_ticket(id),
    UNIQUE (shared_intake_record_id, ordinal),
    UNIQUE (shared_intake_record_id, issue_kind)
);

ALTER TABLE customer_intake
    ADD COLUMN shared_intake_record_id uuid UNIQUE REFERENCES shared_intake_record(id);

GRANT SELECT, INSERT, UPDATE, DELETE ON customer_intake_issue, customer_intake_pending_issue TO spring_app;
GRANT SELECT, INSERT ON shared_intake_record, shared_intake_issue TO spring_app;
