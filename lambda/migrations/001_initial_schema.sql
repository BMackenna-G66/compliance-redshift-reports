-- =============================================================================
-- WatchTower CRM V2 — Phase 0 initial schema
-- Run once against the RDS MySQL `watchtower` database after provisioning.
--
-- Usage:
--   mysql -h <RDS_HOST> -u watchtower_admin -p watchtower < 001_initial_schema.sql
--
-- Tables created:
--   roles             — ANALYST, ADMIN, SUPER_ADMIN
--   modules           — available app modules
--   users             — internal user records (email = Firebase identity)
--   user_permissions  — per-user, per-module access grants
--   audit_log         — structured audit trail for all CRM actions
-- =============================================================================

SET NAMES utf8mb4;
SET time_zone = '+00:00';
SET foreign_key_checks = 0;

-- ---------------------------------------------------------------------------
-- roles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    id          INT UNSIGNED    NOT NULL AUTO_INCREMENT,
    name        VARCHAR(50)     NOT NULL,
    description VARCHAR(255)    DEFAULT NULL,
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO roles (name, description) VALUES
    ('ANALYST',     'Analista de cumplimiento — acceso a módulos asignados'),
    ('ADMIN',       'Administrador — gestión de usuarios y configuración'),
    ('SUPER_ADMIN', 'Super administrador — acceso total');

-- ---------------------------------------------------------------------------
-- modules
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS modules (
    id           INT UNSIGNED    NOT NULL AUTO_INCREMENT,
    name         VARCHAR(50)     NOT NULL,
    display_name VARCHAR(100)    NOT NULL,
    description  VARCHAR(255)    DEFAULT NULL,
    is_active    TINYINT(1)      NOT NULL DEFAULT 1,
    sort_order   INT             NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO modules (name, display_name, sort_order) VALUES
    ('dashboard',       'Dashboard',            1),
    ('alertas',         'Alertas',              2),
    ('bandeja_alertas', 'Bandeja de Alertas',   3),  -- CRM V2
    ('alertados',       'Alertados',            4),
    ('casos',           'Casos',                5),  -- CRM V2
    ('kanban',          'Kanban',               6),  -- CRM V2
    ('historial',       'Historial',            7),
    ('whitelist',       'Whitelist',            8),
    ('pendientes',      'Pendientes',           9),
    ('queries',         'Queries',             10),
    ('aml_individual',  'Análisis Individual', 11),
    ('admin',           'Administración',      12);

-- ---------------------------------------------------------------------------
-- users
-- email is the Firebase identity (Google SSO @global66.com)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INT UNSIGNED    NOT NULL AUTO_INCREMENT,
    email         VARCHAR(255)    NOT NULL,
    full_name     VARCHAR(255)    DEFAULT NULL,
    role_id       INT UNSIGNED    NOT NULL,
    is_active     TINYINT(1)      NOT NULL DEFAULT 1,
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at DATETIME        DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_email (email),
    KEY idx_role (role_id),
    CONSTRAINT fk_users_role FOREIGN KEY (role_id) REFERENCES roles (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Seed the super admin from the existing Firebase config
INSERT IGNORE INTO users (email, full_name, role_id)
SELECT 'benjamin.mackenna@global66.com', 'Benjamin MacKenna', id
FROM roles WHERE name = 'SUPER_ADMIN';

-- ---------------------------------------------------------------------------
-- user_permissions
-- Mirrors the wt_roles.modules[] array in Firestore, but at module granularity
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_permissions (
    id         INT UNSIGNED    NOT NULL AUTO_INCREMENT,
    user_id    INT UNSIGNED    NOT NULL,
    module_id  INT UNSIGNED    NOT NULL,
    can_read   TINYINT(1)      NOT NULL DEFAULT 1,
    can_write  TINYINT(1)      NOT NULL DEFAULT 0,
    granted_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INT UNSIGNED    DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_user_module (user_id, module_id),
    KEY idx_user (user_id),
    CONSTRAINT fk_perm_user   FOREIGN KEY (user_id)   REFERENCES users   (id) ON DELETE CASCADE,
    CONSTRAINT fk_perm_module FOREIGN KEY (module_id) REFERENCES modules (id),
    CONSTRAINT fk_perm_by     FOREIGN KEY (granted_by) REFERENCES users  (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Grant super admin access to all modules
INSERT IGNORE INTO user_permissions (user_id, module_id, can_read, can_write)
SELECT u.id, m.id, 1, 1
FROM users u
JOIN roles r ON u.role_id = r.id AND r.name = 'SUPER_ADMIN'
CROSS JOIN modules m;

-- ---------------------------------------------------------------------------
-- audit_log
-- Structured record of every CRM action (create/update/delete/review/assign)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_email  VARCHAR(255)    DEFAULT NULL,
    action      VARCHAR(100)    NOT NULL,
    entity_type VARCHAR(50)     DEFAULT NULL,
    entity_id   VARCHAR(100)    DEFAULT NULL,
    old_value   JSON            DEFAULT NULL,
    new_value   JSON            DEFAULT NULL,
    ip_address  VARCHAR(45)     DEFAULT NULL,
    user_agent  VARCHAR(500)    DEFAULT NULL,
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_user_email  (user_email),
    KEY idx_entity      (entity_type, entity_id),
    KEY idx_created_at  (created_at),
    KEY idx_action      (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET foreign_key_checks = 1;
