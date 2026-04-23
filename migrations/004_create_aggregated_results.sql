-- Migration 004: Aggregated discovery result snapshots.
--
-- Stores versioned per-workflow aggregation snapshots so dashboard reads
-- can return a single composed view without re-calling all downstream agents.

CREATE TABLE IF NOT EXISTS aggregated_results (
    id                  VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    workflow_run_id     VARCHAR(36) NOT NULL COMMENT 'FK to workflow_runs.id',
    user_id             VARCHAR(36) NOT NULL COMMENT 'FK to users.id',
    result_version      INT UNSIGNED NOT NULL DEFAULT 1,
    is_latest           BOOLEAN NOT NULL DEFAULT TRUE,
    status              ENUM('in_progress', 'partial', 'success', 'failed') NOT NULL DEFAULT 'in_progress',
    current_step        VARCHAR(64) DEFAULT NULL,
    profile_output      JSON DEFAULT NULL,
    program_output      JSON DEFAULT NULL,
    scholarship_output  JSON DEFAULT NULL,
    match_output        JSON DEFAULT NULL,
    application_output  JSON DEFAULT NULL,
    dashboard_view      JSON DEFAULT NULL,
    error_message       TEXT DEFAULT NULL,
    created_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_aggregated_results_run_version (workflow_run_id, result_version),
    INDEX idx_aggregated_results_user_created (user_id, created_at DESC),
    INDEX idx_aggregated_results_user_latest (user_id, is_latest, created_at DESC),
    INDEX idx_aggregated_results_run_latest (workflow_run_id, is_latest, created_at DESC),
    INDEX idx_aggregated_results_status_created (status, created_at DESC),

    FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
