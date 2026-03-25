-- Migration 001: Create Users table
-- Idempotent: uses IF NOT EXISTS and ON DUPLICATE KEY UPDATE.
-- Orchestrator owns user records synced from the auth layer.

CREATE TABLE IF NOT EXISTS users (
    id           VARCHAR(36)  PRIMARY KEY COMMENT 'UUID v4',
    name         VARCHAR(100) NOT NULL,
    email        VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    is_active    BOOLEAN      DEFAULT TRUE COMMENT 'Soft-delete flag',
    last_login   TIMESTAMP    NULL        COMMENT 'Last successful login',
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_email      (email),
    INDEX idx_is_active  (is_active),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
