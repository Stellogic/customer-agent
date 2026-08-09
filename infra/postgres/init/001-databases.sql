CREATE ROLE spring_migrator LOGIN PASSWORD 'local-spring-migrator' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE spring_app LOGIN PASSWORD 'local-spring-app' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE agent_migrator LOGIN PASSWORD 'local-agent-migrator' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE agent_runtime LOGIN PASSWORD 'local-agent-runtime' NOSUPERUSER NOCREATEDB NOCREATEROLE;

CREATE DATABASE customer_agent OWNER spring_migrator;
CREATE DATABASE agent_checkpoint OWNER agent_migrator;

REVOKE CONNECT ON DATABASE customer_agent FROM PUBLIC;
REVOKE CONNECT ON DATABASE agent_checkpoint FROM PUBLIC;
GRANT CONNECT ON DATABASE customer_agent TO spring_migrator, spring_app;
GRANT CONNECT ON DATABASE agent_checkpoint TO agent_migrator, agent_runtime;

\connect customer_agent
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO spring_app;

\connect agent_checkpoint
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO agent_runtime;

