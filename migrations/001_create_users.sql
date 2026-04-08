-- Migration 001: Create Users, Auth Sessions, and OTP Logs tables
-- Idempotent: CREATE TABLE IF NOT EXISTS.
-- Description: Phone-based authentication with OTP verification, session tracking,
--              and profile completion flow.

CREATE TABLE IF NOT EXISTS users (
    id                  VARCHAR(36)  PRIMARY KEY COMMENT 'UUID v4',
    username            VARCHAR(50)  UNIQUE NOT NULL,
    phone_number        VARCHAR(20)  UNIQUE NOT NULL COMMENT 'E.164 format',
    phone_country_code  VARCHAR(5)   NOT NULL COMMENT 'ISO 3166-1 alpha-2',
    phone_verified      BOOLEAN      DEFAULT FALSE,
    password_hash       TEXT         NOT NULL,

    first_name          VARCHAR(50)  NOT NULL,
    last_name           VARCHAR(50)  NOT NULL,
    email               VARCHAR(255) NULL UNIQUE,
    about_me            TEXT         NULL,
    profession          VARCHAR(100) NULL,
    interest            ENUM('jobs', 'startups', 'research') NULL,
    profile_completed   BOOLEAN      DEFAULT FALSE,

    -- OTP fields (transient, cleared after verification)
    otp_code            VARCHAR(6)   NULL COMMENT 'Current OTP code',
    otp_expires_at      DATETIME     NULL COMMENT 'OTP expiry (UTC)',
    otp_attempts        INT          DEFAULT 0 COMMENT 'Failed OTP attempts since last send',
    otp_last_sent_at    DATETIME     NULL COMMENT 'Last OTP send time (for cooldown)',

    is_active           BOOLEAN      DEFAULT TRUE COMMENT 'Soft-delete flag',
    last_login          DATETIME     NULL COMMENT 'Last successful login',
    last_active         DATETIME     NULL COMMENT 'Last API activity',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_username          (username),
    INDEX idx_phone_number      (phone_number),
    INDEX idx_email             (email),
    INDEX idx_phone_verified    (phone_verified),
    INDEX idx_profile_completed (profile_completed),
    INDEX idx_is_active         (is_active),
    INDEX idx_created_at        (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Auth sessions (JWT refresh token management with session tracking)
-- Each login creates a session; refresh rotates the token hash; logout revokes.
-- last_active_at and revoked_at enable session duration tracking.
CREATE TABLE IF NOT EXISTS auth_sessions (
    id              VARCHAR(36)  PRIMARY KEY COMMENT 'Session UUID v4',
    user_id         VARCHAR(36)  NOT NULL,
    token_hash      VARCHAR(255) NOT NULL COMMENT 'SHA-256 hash of refresh token JTI',
    expires_at      DATETIME     NOT NULL,
    is_revoked      BOOLEAN      DEFAULT FALSE,
    revoked_at      DATETIME     NULL COMMENT 'When this session was revoked (logout/rotation)',
    last_active_at  DATETIME     NULL COMMENT 'Last token refresh or API activity on this session',
    user_agent      TEXT         NULL COMMENT 'Client user-agent at login',
    ip_address      VARCHAR(50)  NULL COMMENT 'Client IP at session creation',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_user_id       (user_id),
    INDEX idx_expires_at    (expires_at),
    INDEX idx_is_revoked    (is_revoked),
    INDEX idx_session_lookup (user_id, is_revoked, expires_at),

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- OTP audit log (for rate-limiting and compliance)
CREATE TABLE IF NOT EXISTS otp_logs (
    id            INT          AUTO_INCREMENT PRIMARY KEY,
    phone_number  VARCHAR(20)  NOT NULL,
    action        ENUM('sent', 'verified', 'failed', 'expired') NOT NULL,
    ip_address    VARCHAR(50)  NULL,
    user_agent    TEXT         NULL,
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_phone_number (phone_number),
    INDEX idx_action       (action),
    INDEX idx_created_at   (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
