-- =============================================================================
-- 003_crm_cases.sql — Phase 2: Casos CRM
--
-- Creates crm.cases and crm.case_notes, and links compliance.alerts to cases.
-- Run via: python3 lambda/migrations/run_migration.py lambda/migrations/003_crm_cases.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- cases — investigation cases opened by compliance analysts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.cases (
    case_id       VARCHAR(36)   NOT NULL,
    title         VARCHAR(255)  NOT NULL,
    description   VARCHAR(2000),
    status        VARCHAR(20)   NOT NULL DEFAULT 'open',
    priority      VARCHAR(10)   NOT NULL DEFAULT 'medium',
    entity_type   VARCHAR(50),
    entity_id     VARCHAR(255),
    report_name   VARCHAR(200),
    assigned_to   VARCHAR(255),
    created_by    VARCHAR(255)  NOT NULL,
    created_at    TIMESTAMP     NOT NULL DEFAULT GETDATE(),
    updated_at    TIMESTAMP     NOT NULL DEFAULT GETDATE(),
    closed_at     TIMESTAMP,
    PRIMARY KEY (case_id)
);

-- ---------------------------------------------------------------------------
-- case_notes — chronological investigation notes per case
-- SORTKEY on (case_id, created_at) makes per-case note fetches efficient.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.case_notes (
    note_id       BIGINT        IDENTITY(1,1) NOT NULL,
    case_id       VARCHAR(36)   NOT NULL,
    author_email  VARCHAR(255),
    content       VARCHAR(4000) NOT NULL,
    created_at    TIMESTAMP     NOT NULL DEFAULT GETDATE(),
    PRIMARY KEY (note_id)
) SORTKEY (case_id, created_at);

-- ---------------------------------------------------------------------------
-- Link compliance.alerts to cases (optional — an alert can belong to a case)
-- ---------------------------------------------------------------------------
ALTER TABLE compliance.alerts ADD COLUMN case_id VARCHAR(36);
