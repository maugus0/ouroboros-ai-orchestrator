-- Migration 005: user-tracked applications started from discovery results.

CREATE TABLE IF NOT EXISTS tracked_applications (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    entity_type ENUM('program', 'scholarship') NOT NULL DEFAULT 'program',
    entity_id VARCHAR(128) NOT NULL,
    title VARCHAR(255) NOT NULL,
    provider VARCHAR(255) NULL,
    status ENUM('not_started', 'in_progress', 'applied', 'accepted', 'rejected') NOT NULL DEFAULT 'not_started',
    match_score DECIMAL(5,2) NULL,
    deadline DATE NULL,
    source_data JSON NULL,
    checklist_output JSON NULL,
    deadline_output JSON NULL,
    sop_output JSON NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uniq_tracked_applications_user_entity (user_id, entity_type, entity_id),
    INDEX idx_tracked_applications_user_updated (user_id, updated_at DESC),
    INDEX idx_tracked_applications_status (user_id, status),
    CONSTRAINT fk_tracked_applications_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @add_cover_letter_output = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE tracked_applications ADD COLUMN cover_letter_output JSON NULL AFTER sop_output',
        'DO 0'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tracked_applications'
      AND COLUMN_NAME = 'cover_letter_output'
);
PREPARE add_cover_letter_output_stmt FROM @add_cover_letter_output;
EXECUTE add_cover_letter_output_stmt;
DEALLOCATE PREPARE add_cover_letter_output_stmt;
