-- Migration 002: Chat sessions, messages, and projects for user conversations.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS only — safe to re-run.
--
-- Timezone: The application sets `time_zone = '+00:00'` on every MySQL connection,
-- so CURRENT_TIMESTAMP and UTC_TIMESTAMP() both return UTC. All DATETIME columns
-- store UTC; the frontend converts to the user's local timezone for display.
--
-- Soft delete: chats and projects use deleted_at column; messages are retained for recovery.

-- ============================================================================
-- PROJECTS TABLE (must be created before chats due to FK reference)
-- ============================================================================
-- User-defined folders/workspaces for organizing chats.
-- Each project belongs to one user. Chats can optionally belong to one project.

CREATE TABLE IF NOT EXISTS projects (
    id              VARCHAR(36)  PRIMARY KEY COMMENT 'UUID v4',
    user_id         VARCHAR(36)  NOT NULL COMMENT 'FK to users.id',
    name            VARCHAR(100) NOT NULL COMMENT 'Project name',
    description     TEXT         DEFAULT NULL COMMENT 'Optional project description',
    color           VARCHAR(7)   DEFAULT NULL COMMENT 'Hex color code for UI (e.g., #3B82F6)',
    icon            VARCHAR(50)  DEFAULT NULL COMMENT 'Icon identifier for UI (e.g., folder, briefcase)',
    chat_count      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Denormalized for list view',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at      DATETIME     DEFAULT NULL COMMENT 'Soft delete marker',

    INDEX idx_projects_user_active (user_id, deleted_at, updated_at DESC),
    INDEX idx_projects_name (user_id, name),
    INDEX idx_projects_user_id (user_id),

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- CHATS TABLE
-- ============================================================================
-- Each chat belongs to one user and contains multiple messages.
-- Soft delete via deleted_at; message_count denormalized for list performance.
-- is_starred marks favorite chats; project_id groups chats into folders.

CREATE TABLE IF NOT EXISTS chats (
    id              VARCHAR(36)  PRIMARY KEY COMMENT 'UUID v4',
    user_id         VARCHAR(36)  NOT NULL COMMENT 'FK to users.id',
    title           VARCHAR(255) DEFAULT NULL COMMENT 'Auto-generated from first message or user-set',
    status          ENUM('active', 'archived') NOT NULL DEFAULT 'active',
    is_starred      BOOLEAN      NOT NULL DEFAULT FALSE COMMENT 'User-marked as favorite',
    project_id      VARCHAR(36)  DEFAULT NULL COMMENT 'FK to projects.id (optional)',
    message_count   INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Denormalized for list view',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at      DATETIME     DEFAULT NULL COMMENT 'Soft delete marker',

    INDEX idx_chats_user_active  (user_id, deleted_at, updated_at DESC),
    INDEX idx_chats_updated      (updated_at DESC),
    INDEX idx_chats_user_id      (user_id),
    INDEX idx_chats_starred      (user_id, is_starred, deleted_at, updated_at DESC),
    INDEX idx_chats_project      (project_id, deleted_at, updated_at DESC),

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- MESSAGES TABLE
-- ============================================================================
-- Messages within a chat. Role indicates sender (user, assistant, system).
-- metadata JSON stores future agent routing info, token counts, latency.

CREATE TABLE IF NOT EXISTS messages (
    id          VARCHAR(36)  PRIMARY KEY COMMENT 'UUID v4',
    chat_id     VARCHAR(36)  NOT NULL COMMENT 'FK to chats.id',
    role        ENUM('user', 'assistant', 'system') NOT NULL,
    content     TEXT         NOT NULL,
    metadata    JSON         DEFAULT NULL COMMENT 'Future: agent_ids, routing_decision, token_count, latency_ms',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_messages_chat_created (chat_id, created_at ASC),
    INDEX idx_messages_chat_id      (chat_id),

    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
