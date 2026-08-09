CREATE TABLE baseline_probe (
    id smallint PRIMARY KEY CHECK (id = 1),
    installed_at timestamptz NOT NULL DEFAULT current_timestamp
);

INSERT INTO baseline_probe (id) VALUES (1);

GRANT SELECT ON baseline_probe TO spring_app;

