-- =============================================================================
-- 002_alerts_crm_columns.sql — Phase 1: Bandeja de Alertas CRM
--
-- Adds CRM-level columns to the existing compliance.alerts table.
-- Run via: python3 lambda/migrations/run_migration.py lambda/migrations/002_alerts_crm_columns.sql
--
-- Note: Redshift does not support ADD COLUMN IF NOT EXISTS.
-- This migration is idempotent only on first run — re-running will fail with
-- "column already exists", which is safe to ignore.
-- =============================================================================

-- Priority: high / medium / low (default medium)
ALTER TABLE compliance.alerts ADD COLUMN priority VARCHAR(10) DEFAULT 'medium';

-- Who is currently investigating this alert
ALTER TABLE compliance.alerts ADD COLUMN assigned_to VARCHAR(255);

-- Who reviewed/closed it
ALTER TABLE compliance.alerts ADD COLUMN reviewed_by VARCHAR(255);

-- Analyst investigation notes (persists across status changes)
ALTER TABLE compliance.alerts ADD COLUMN notes VARCHAR(2000);
