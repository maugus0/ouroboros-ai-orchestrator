-- Migration 003: Workflow runs, results, and agent audit log

CREATE TABLE IF NOT EXISTS workflow_runs (
    id                   VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    chat_id              VARCHAR(36) NOT NULL UNIQUE,
    user_id              VARCHAR(36) NOT NULL,
    current_state        ENUM(
        'INITIATED', 'PROFILE_PARSING', 'PROFILE_COMPLETE',
        'DISCOVERING_PROGRAMS', 'DISCOVERING_SCHOLARSHIPS',
        'MATCHING', 'GENERATING_MATERIALS', 'COMPLETE', 'ERROR'
    ) NOT NULL DEFAULT 'INITIATED',
    last_successful_state ENUM(
        'INITIATED', 'PROFILE_PARSING', 'PROFILE_COMPLETE',
        'DISCOVERING_PROGRAMS', 'DISCOVERING_SCHOLARSHIPS',
        'MATCHING', 'GENERATING_MATERIALS', 'COMPLETE', 'ERROR'
    ) NULL,
    error_message        TEXT NULL,
    started_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at         TIMESTAMP NULL,

    INDEX idx_user_state (user_id, current_state),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS workflow_results (
    id                    VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    workflow_run_id       VARCHAR(36) NOT NULL,
    student_profile       JSON NULL,
    programs              JSON NULL,
    scholarships          JSON NULL,
    eligibility_matches   JSON NULL,
    application_materials JSON NULL,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS agent_call_logs (
    id               VARCHAR(36)  PRIMARY KEY COMMENT 'UUID v4',
    workflow_run_id  VARCHAR(36)  NOT NULL,
    agent_name       VARCHAR(100) NOT NULL,
    endpoint         VARCHAR(255) NOT NULL,
    request_payload  JSON         NULL,
    response_payload JSON         NULL,
    http_status      INT          NULL,
    latency_ms       INT          NULL,
    trace_id         VARCHAR(36)  NOT NULL,
    error_message    TEXT         NULL,
    created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_workflow_agent (workflow_run_id, agent_name),
    INDEX idx_trace_id      (trace_id),
    FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
