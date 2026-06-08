-- AnsiQ Database Initialization
-- Run automatically on first PostgreSQL container start
-- Creates extensions and initial schema

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Ensure the schema exists
CREATE SCHEMA IF NOT EXISTS ansiq;

-- Set timezone
ALTER DATABASE ansiq SET timezone TO 'UTC';

-- Create admin user for migrations if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ansiq_admin') THEN
        CREATE ROLE ansiq_admin WITH LOGIN PASSWORD 'ansiq_admin' SUPERUSER;
    END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE ansiq TO ansiq_admin;
GRANT ALL ON SCHEMA public TO ansiq_admin;