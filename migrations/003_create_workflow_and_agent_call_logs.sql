-- Migration 003: Workflow state persistence and downstream call audit logs.
--
-- Provides:
-- 1) workflow_runs    : per-request workflow execution snapshots.
-- 2) workflow_context : optional key/value JSON context attached to a workflow run.
-- 3) agent_call_logs  : every downstream call attempt with retry linkage.

CREATE TABLE IF NOT EXISTS workflow_runs (
    id               VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    user_id          VARCHAR(36) NOT NULL COMMENT 'FK to users.id',
    chat_id          VARCHAR(36) DEFAULT NULL COMMENT 'FK to chats.id, nullable for user-level checks',
    workflow_type    VARCHAR(64) NOT NULL COMMENT 'Example: profile_gate_chat_turn',
    workflow_state   VARCHAR(64) NOT NULL COMMENT 'Example: RECEIVED, PROFILE_GATE, SUCCESS, FAILED_TERMINAL',
    status           ENUM('in_progress', 'success', 'failed') NOT NULL DEFAULT 'in_progress',
    context          JSON DEFAULT NULL COMMENT 'Optional workflow payload snapshot',
    error_message    TEXT DEFAULT NULL,
    started_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ended_at         DATETIME(6) DEFAULT NULL,
    created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    INDEX idx_workflow_runs_user_created (user_id, created_at DESC),
    INDEX idx_workflow_runs_chat_created (chat_id, created_at DESC),
    INDEX idx_workflow_runs_status_created (status, created_at DESC),

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS workflow_context (
    id               VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    workflow_run_id  VARCHAR(36) NOT NULL COMMENT 'FK to workflow_runs.id',
    context_key      VARCHAR(100) NOT NULL,
    context_value    JSON DEFAULT NULL,
    created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_workflow_context_key (workflow_run_id, context_key),
    INDEX idx_workflow_context_run (workflow_run_id, created_at DESC),

    FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_call_logs (
    id                  VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    workflow_run_id     VARCHAR(36) DEFAULT NULL COMMENT 'FK to workflow_runs.id',
    user_id             VARCHAR(36) NOT NULL COMMENT 'FK to users.id',
    chat_id             VARCHAR(36) DEFAULT NULL COMMENT 'FK to chats.id',
    target_service      VARCHAR(64) NOT NULL COMMENT 'Example: student-profile',
    operation           VARCHAR(100) NOT NULL COMMENT 'Example: get_profile_status, collect_from_chat',
    request_method      VARCHAR(10) DEFAULT NULL,
    request_path        VARCHAR(255) DEFAULT NULL,
    attempt_number      INT UNSIGNED NOT NULL DEFAULT 1,
    status              ENUM('success', 'failed') NOT NULL,
    http_status         INT DEFAULT NULL,
    error_code          VARCHAR(100) DEFAULT NULL,
    error_message       TEXT DEFAULT NULL,
    request_payload     JSON DEFAULT NULL,
    response_payload    JSON DEFAULT NULL,
    trace_id            VARCHAR(64) DEFAULT NULL,
    session_id          VARCHAR(64) DEFAULT NULL,
    retry_of_log_id     VARCHAR(36) DEFAULT NULL COMMENT 'Self-reference to original failed call',
    created_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    INDEX idx_agent_call_logs_run_created (workflow_run_id, created_at DESC),
    INDEX idx_agent_call_logs_chat_created (chat_id, created_at DESC),
    INDEX idx_agent_call_logs_user_created (user_id, created_at DESC),
    INDEX idx_agent_call_logs_service_created (target_service, created_at DESC),
    INDEX idx_agent_call_logs_retry_of (retry_of_log_id),

    FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE SET NULL,
    FOREIGN KEY (retry_of_log_id) REFERENCES agent_call_logs(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;