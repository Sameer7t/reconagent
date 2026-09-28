-- =============================================================================
-- ReconAgent Enterprise PostgreSQL Database Schema Initialization
-- Automatically provisioned on initial container boot via /docker-entrypoint-initdb.d/
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- 1. Users & Authentication
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Seed default Admin user if not present (Password: admin)
INSERT INTO users (id, email, password_hash, role, is_active)
VALUES (
    gen_random_uuid(),
    'admin@reconagent.local',
    '$2b$12$ECpcJEDJ8xoA5tShrfp79OOK07KRtqOHGR5Q6Ga.izQORGi7zmWrW',
    'Admin',
    TRUE
)
ON CONFLICT (email) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2. Investigations & Autonomous AI Reasoning Traces
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS investigations (
    id VARCHAR(64) PRIMARY KEY,
    case_id VARCHAR(128) NOT NULL,
    status VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    recommendation VARCHAR(64),
    confidence VARCHAR(32),
    requires_human_review BOOLEAN NOT NULL DEFAULT FALSE,
    final_summary TEXT,
    po_file VARCHAR(512),
    invoice_file VARCHAR(512),
    receipt_files JSONB,
    source_files JSONB,
    vendor_name VARCHAR(255),
    po_number VARCHAR(128),
    invoice_number VARCHAR(128),
    receipt_numbers JSONB,
    reconciliation_result JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS investigation_events (
    id VARCHAR(64) PRIMARY KEY,
    investigation_id VARCHAR(64) NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    event_type VARCHAR(64),
    tool_name VARCHAR(128),
    arguments JSONB,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS investigation_evidence (
    id VARCHAR(128) PRIMARY KEY,
    investigation_id VARCHAR(64) NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    source_id VARCHAR(128) NOT NULL,
    field VARCHAR(128),
    value TEXT,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS investigation_findings (
    id VARCHAR(128) PRIMARY KEY,
    investigation_id VARCHAR(64) NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    discrepancy_type VARCHAR(64) NOT NULL,
    explanation TEXT NOT NULL,
    confidence VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_decisions (
    case_id VARCHAR(128) PRIMARY KEY,
    decision VARCHAR(64) NOT NULL,
    status VARCHAR(64) NOT NULL,
    reviewer_id VARCHAR(128) NOT NULL,
    notes TEXT,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 3. Query Optimization Indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_inv_case_id ON investigations(case_id);
CREATE INDEX IF NOT EXISTS idx_inv_status ON investigations(status);
CREATE INDEX IF NOT EXISTS idx_inv_completed_at ON investigations(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_inv_requires_review ON investigations(requires_human_review);
CREATE INDEX IF NOT EXISTS idx_events_inv_id ON investigation_events(investigation_id);
CREATE INDEX IF NOT EXISTS idx_evid_inv_id ON investigation_evidence(investigation_id);
CREATE INDEX IF NOT EXISTS idx_find_inv_id ON investigation_findings(investigation_id);
CREATE INDEX IF NOT EXISTS idx_rev_case_id ON review_decisions(case_id);
