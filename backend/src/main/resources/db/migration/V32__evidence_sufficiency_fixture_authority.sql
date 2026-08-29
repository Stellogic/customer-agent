GRANT UPDATE, DELETE ON investigation_fact TO spring_fixture;
GRANT SELECT (generation_id, fact_type) ON investigation_fact TO spring_fixture;
GRANT INSERT, DELETE ON synthetic_pending_action TO spring_fixture;
GRANT SELECT (id) ON synthetic_pending_action TO spring_fixture;
