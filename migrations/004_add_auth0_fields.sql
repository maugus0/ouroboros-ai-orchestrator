-- Migration 004: Add Auth0 integration fields
-- Auth0 owns password authentication. Local DB stores user identity mapping.
-- Existing FKs (chats.user_id, workflow_runs.user_id) remain unchanged.

-- Add auth0_sub column for Auth0 user identifier mapping
ALTER TABLE users
    ADD COLUMN auth0_sub VARCHAR(255) NULL UNIQUE AFTER id,
    ADD INDEX idx_auth0_sub (auth0_sub);

-- Make password_hash nullable (Auth0 now owns passwords)
ALTER TABLE users
    MODIFY COLUMN password_hash TEXT NULL COMMENT 'Deprecated - Auth0 manages authentication';

-- Add column to track authentication provider
ALTER TABLE users
    ADD COLUMN auth_provider ENUM('auth0', 'legacy') DEFAULT 'auth0' AFTER auth0_sub;
