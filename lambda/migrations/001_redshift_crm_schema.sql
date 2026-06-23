-- =============================================================================
-- 001_redshift_crm_schema.sql — Phase 0 CRM schema for Redshift
--
-- Creates the `crm` schema and initial tables inside the existing `dev` database.
-- Run via: python3 lambda/migrations/run_migration.py lambda/migrations/001_redshift_crm_schema.sql
--
-- Redshift notes vs MySQL DDL:
--   - IDENTITY(1,1) instead of AUTO_INCREMENT
--   - BOOLEAN instead of TINYINT(1)
--   - SUPER instead of JSON (use JSON_PARSE() to insert)
--   - TIMESTAMP instead of DATETIME
--   - GETDATE() instead of CURRENT_TIMESTAMP
--   - ON UPDATE CURRENT_TIMESTAMP not supported — handled in application code
--   - UNIQUE / FK constraints are metadata only (not enforced by Redshift)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS crm;

-- ---------------------------------------------------------------------------
-- roles — analyst / admin / super_admin
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.roles (
    id          INT          IDENTITY(1,1) NOT NULL,
    name        VARCHAR(50)  NOT NULL,
    description VARCHAR(255),
    created_at  TIMESTAMP    NOT NULL DEFAULT GETDATE(),
    PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------
-- modules — feature areas users can be granted access to
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.modules (
    id           INT          IDENTITY(1,1) NOT NULL,
    name         VARCHAR(50)  NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description  VARCHAR(255),
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    sort_order   INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------
-- users — authenticated operators
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.users (
    id            INT          IDENTITY(1,1) NOT NULL,
    email         VARCHAR(255) NOT NULL,
    full_name     VARCHAR(255),
    role_id       INT          NOT NULL,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP    NOT NULL DEFAULT GETDATE(),
    updated_at    TIMESTAMP    NOT NULL DEFAULT GETDATE(),
    last_login_at TIMESTAMP,
    PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------
-- user_permissions — per-module read/write grants
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.user_permissions (
    id         INT       IDENTITY(1,1) NOT NULL,
    user_id    INT       NOT NULL,
    module_id  INT       NOT NULL,
    can_read   BOOLEAN   NOT NULL DEFAULT TRUE,
    can_write  BOOLEAN   NOT NULL DEFAULT FALSE,
    granted_at TIMESTAMP NOT NULL DEFAULT GETDATE(),
    granted_by INT,
    PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------
-- audit_log — immutable record of every write action
-- SORTKEY on created_at makes time-range queries efficient.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.audit_log (
    id          BIGINT       IDENTITY(1,1) NOT NULL,
    user_email  VARCHAR(255),
    action      VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),
    entity_id   VARCHAR(100),
    old_value   SUPER,
    new_value   SUPER,
    ip_address  VARCHAR(45),
    user_agent  VARCHAR(500),
    created_at  TIMESTAMP    NOT NULL DEFAULT GETDATE(),
    PRIMARY KEY (id)
) SORTKEY (created_at);

-- =============================================================================
-- Seed data — roles (idempotent)
-- =============================================================================
INSERT INTO crm.roles (name, description)
SELECT 'ANALYST', 'Analista de cumplimiento — lectura en todos los módulos'
WHERE NOT EXISTS (SELECT 1 FROM crm.roles WHERE name = 'ANALYST');

INSERT INTO crm.roles (name, description)
SELECT 'ADMIN', 'Administrador — lectura y escritura, excepto gestión de usuarios'
WHERE NOT EXISTS (SELECT 1 FROM crm.roles WHERE name = 'ADMIN');

INSERT INTO crm.roles (name, description)
SELECT 'SUPER_ADMIN', 'Super administrador — acceso total incluyendo gestión de usuarios y permisos'
WHERE NOT EXISTS (SELECT 1 FROM crm.roles WHERE name = 'SUPER_ADMIN');

-- =============================================================================
-- Seed data — modules (idempotent)
-- =============================================================================
INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'reports', 'Reportes AML', 'Ejecución y descarga de reportes de screening', 1
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'reports');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'alerts', 'Bandeja de Alertas', 'Gestión de alertas AML pendientes de revisión', 2
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'alerts');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'cases', 'Casos CRM', 'Creación y seguimiento de casos de investigación', 3
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'cases');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'whitelist', 'Whitelist', 'Gestión de entidades en lista blanca', 4
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'whitelist');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'dashboard', 'Dashboard', 'Métricas y estadísticas operativas', 5
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'dashboard');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'queries', 'Consultas SQL', 'Catálogo de consultas SQL personalizadas', 6
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'queries');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'cluster', 'Cluster Redshift', 'Control del cluster Redshift (wake/pause)', 7
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'cluster');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'users_admin', 'Gestión de Usuarios', 'Alta, baja y modificación de usuarios del CRM', 8
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'users_admin');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'ai_analysis', 'Análisis IA', 'Narrativas y detección de patrones asistidos por IA', 9
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'ai_analysis');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'files', 'Archivos', 'Gestión de archivos adjuntos a casos', 10
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'files');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'kanban', 'Kanban', 'Vista kanban de casos por estado', 11
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'kanban');

INSERT INTO crm.modules (name, display_name, description, sort_order)
SELECT 'scheduler', 'Scheduler', 'Gestión de tareas programadas y reportes automáticos', 12
WHERE NOT EXISTS (SELECT 1 FROM crm.modules WHERE name = 'scheduler');

-- =============================================================================
-- Seed data — initial SUPER_ADMIN user (idempotent)
-- =============================================================================
INSERT INTO crm.users (email, full_name, role_id)
SELECT
    'benjamin.mackenna@global66.com',
    'Benjamin Mackenna',
    (SELECT id FROM crm.roles WHERE name = 'SUPER_ADMIN')
WHERE NOT EXISTS (
    SELECT 1 FROM crm.users WHERE email = 'benjamin.mackenna@global66.com'
);
