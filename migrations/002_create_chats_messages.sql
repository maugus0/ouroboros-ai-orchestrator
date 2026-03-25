-- Migration 002: Create Chats and Messages tables

CREATE TABLE IF NOT EXISTS chats (
    id         VARCHAR(36)  PRIMARY KEY COMMENT 'UUID v4',
    user_id    VARCHAR(36)  NOT NULL,
    title      VARCHAR(255) NULL,
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_user_created (user_id, created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS messages (
    id         VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    chat_id    VARCHAR(36) NOT NULL,
    role       ENUM('user', 'assistant', 'system') NOT NULL,
    content    TEXT        NOT NULL,
    metadata   JSON        NULL,
    created_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_chat_created (chat_id, created_at),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
