# Ouroboros Orchestrator Service

Central coordination service for the **Ouroboros AI** scholarship discovery platform. The Orchestrator is the single backend entry-point the frontend communicates with — handling authentication, user management, and health monitoring, with business logic (workflows, agents, chats) to be added incrementally.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Why Internal Bearer Tokens (Not X_SERVICE_TOKEN)](#why-internal-bearer-tokens-not-x_service_token)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Token Generation and API Testing](#token-generation-and-api-testing)
- [Workflow State Machines](#workflow-state-machines)
- [Configuration](#configuration)
- [Database Schema](#database-schema)
- [API Endpoints](#api-endpoints)
- [Auth Flow](#auth-flow)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [CI/CD Pipeline](#cicd-pipeline)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Attribution](#attribution)

---

## Overview

The Orchestrator Service is the **central nervous system** of the Ouroboros AI platform:

1. **Authenticates users** via self-rolled JWT (RS256) with phone-based registration
2. **Verifies phone numbers** using Twilio OTP (SMS or Verify API)
3. **Supports login** by phone number or username + password
4. **Manages user profiles** with a completion flow (gender, email, about me, profession, interest)
5. **Tracks sessions** with active-device visibility and duration metrics
6. **Manages chat sessions** for scholarship discovery conversations with message history
7. **Organizes chats into projects** — user-defined folders for grouping related conversations
8. **Supports starred chats** — mark important conversations for quick access
9. **Exposes a health endpoint** for monitoring and readiness checks

**Key Design Principles:**

- Single entry-point — the frontend communicates **only** with the orchestrator
- Async-first — `aiomysql` connection pool for non-blocking I/O (the orchestrator coordinates external microservices over HTTP, so async is essential)
- Self-rolled authentication — no third-party auth providers; full control over JWT lifecycle
- No ORM overhead — raw SQL with repository pattern
- Trace propagation — `X-Trace-ID` header flows through every request for correlated debugging
- UTC everywhere — all timestamps stored and serialized as UTC ISO 8601

---

## Architecture

```
┌─────────────────────────────────────┐
│       Frontend (React + Vite)       │
│       (http://localhost:8080)       │
└──────────────┬──────────────────────┘
               │
               │ JWT Bearer Token
               ▼
┌──────────────────────────────────────────────────────┐
│          Orchestrator Service (8000)                  │
│                                                      │
│  ┌─────────────────────────────────────────────┐     │
│  │  API Layer (FastAPI)                        │     │
│  │  POST /auth/signup, /auth/verify-otp        │     │
│  │  POST /auth/login, /auth/refresh            │     │
│  │  POST /auth/logout, /auth/resend-otp        │     │
│  │  GET  /auth/me, /auth/profile-status        │     │
│  │  PATCH /auth/profile                        │     │
│  │  GET  /auth/sessions                        │     │
│  │  POST /auth/mfa/toggle, /auth/mfa/verify   │     │
│  │  POST /api/v1/chats, GET /api/v1/chats     │     │
│  │  POST /api/v1/chats/{id}/messages          │     │
│  │  GET  / and /health                         │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Middleware (JWT RS256, CORS, Logging)       │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Service Layer (auth, twilio, chat, project) │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Repository Layer (raw SQL / aiomysql)       │     │
│  │  UserRepo, AuthRepo, ChatRepo, MessageRepo  │     │
│  │  ProjectRepo                                 │     │
│  └─────────────────────────────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Core (async DB pool, structured logging)    │     │
│  └─────────────────────────────────────────────┘     │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
      ┌─────────────────┐       ┌─────────────────┐
      │   MySQL 8.0     │       │   Twilio API    │
      │   (aiomysql)    │       │   (SMS / OTP)   │
      └─────────────────┘       └─────────────────┘
```

### Why Internal Bearer Tokens (Not X_SERVICE_TOKEN)

`X_SERVICE_TOKEN` is a shared secret model. It authenticates only the caller service, not the end-user context.

The internal bearer-token model is better because it is:

1. **Identity-preserving**: includes `sub` (user id), `sid`, and `trace_id`, so downstream services can enforce user-scoped logic directly.
2. **Audience-bound**: `aud` is specific per target service; a token for one service cannot be reused against another.
3. **Short-lived**: small TTL reduces replay window and blast radius.
4. **Rotation-friendly**: `kid` + JWKS supports overlap and safe cutover.
5. **Auditable**: claims and `jti` pair naturally with `agent_call_logs` for traceable call chains.
6. **Zero shared static secret at runtime path**: avoids one leaked header unlocking all internal services.

In short: this design moves from static shared-secret trust to scoped, verifiable, and time-bounded trust.

### Authentication Strategy

| Concern            | Approach                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------ |
| Registration       | Phone number + username + first/last name + password (OTP verification required)           |
| Login              | Phone number **or** username + password                                                    |
| Password storage   | **bcrypt** (cost factor 12)                                                                |
| Token signing      | **RS256** (RSA private key signs, public key verifies)                                     |
| Access token       | 15 min TTL, claims: `{sub, token_type, username, phone, sid}`                              |
| Refresh token      | 7 day TTL, SHA-256 hashed in DB, rotation on use                                           |
| Phone verification | Twilio OTP (6-digit, 5 min expiry, max 3 attempts)                                         |
| Session tracking   | `auth_sessions` table with `last_active_at`, `revoked_at` for duration metrics             |
| Profile completion | First login: gender, email, about me, profession, interest (jobs/startups/research/degree) |
| MFA (optional)     | When enabled, login requires a second SMS OTP step (max 10/day) before tokens are issued   |
| Forgot password    | OTP to phone → verify → new password. Limited to once per week                             |
| Reset password     | Authenticated change (current + new password). Limited to once per month                   |

---

## Prerequisites

| Tool           | Version | Purpose                             |
| -------------- | ------- | ----------------------------------- |
| Python         | 3.11+   | Runtime                             |
| MySQL          | 8.0+    | Database                            |
| Twilio account | —       | OTP delivery                        |
| Docker         | 24.0+   | Containerised deployment (optional) |

---

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/maugus0/ouroboros-ai-orchestrator.git
cd ouroboros-ai-orchestrator

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### 2. Generate RS256 Key Pair

```bash
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

Copy each PEM file’s full text into `.env` as a single-line value: replace real line breaks with the two characters `\` and `n` inside the double-quoted string. Then **delete** `jwt_private.pem` and `jwt_public.pem` locally — `*.pem` is gitignored so keys never land in the repo.

```
JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
```

### 2b. Generate Internal Service Token Keys

```bash
openssl genrsa -out internal_private.pem 2048
openssl rsa -in internal_private.pem -pubout -out internal_public.pem
```

Copy the internal PEM files into `.env` as single-line escaped values, just like the user JWT keys. Keep the internal private key separate from the user auth keys.

```
INTERNAL_TOKEN_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
INTERNAL_TOKEN_ACTIVE_KID="internal-v1"
INTERNAL_TOKEN_ENABLED=true
INTERNAL_TOKEN_ISSUER="ouroboros-orchestrator-internal"
INTERNAL_TOKEN_TTL_SECONDS=120
```

Then delete `internal_private.pem` and `internal_public.pem` locally.

### 3. Set Up Twilio

1. Sign up at [twilio.com](https://www.twilio.com)
2. Get your **Account SID** and **Auth Token** from the console
3. Get a Twilio phone number (for sending SMS)
4. Optionally create a **Verify Service** for production

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials (DB password, JWT keys, Twilio creds). See `.env.example` for all available settings with descriptions.

### 5. Database Setup

**Option A: Docker (Recommended)**

```bash
docker compose up mysql -d
docker compose logs -f mysql   # wait for "ready for connections"
```

**Option B: Local MySQL**

```bash
mysql -u root -p -e "CREATE DATABASE ouroboros_orchestrator_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 6. Run Migrations

```bash
python scripts/run_migrations.py
```

### 7. (Optional) Seed Test Data

```bash
python scripts/seed_users.py
```

### 8. Start the Service

```bash
chmod +x start.sh
./start.sh
# or: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 9. Verify

```bash
curl http://localhost:8000/health
```

**Swagger UI**: http://localhost:8000/docs (click **Authorize** and paste a JWT access token to test protected endpoints).

### Token Generation and API Testing

### A. Get User Access Token (normal flow)

Recommended for Swagger/Postman testing:

1. Sign up and verify OTP (or use seeded user).
2. Login and copy `access_token`.
3. Click **Authorize** in Swagger and paste token value only.

Example login call:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"Feri","password":"Admin123@"}'
```

### B. Generate Internal Service Token (debug only)

Normally the orchestrator mints this automatically for downstream calls.
For debugging only:

```bash
python - <<'PY'
from app.security.internal_token_issuer import InternalTokenIssuer

issuer = InternalTokenIssuer()
token = issuer.issue_service_token(
  sub="debug-user-id",
  sid="debug-session-id",
  trace_id="debug-trace-id",
  aud=issuer.resolve_audience("student-profile"),
)
print(token)
PY
```

Internal JWKS endpoint (for downstream verifiers):

- `GET /internal/.well-known/jwks.json`

---

## Workflow State Machines

### Chat State

```mermaid
stateDiagram-v2
  [*] --> OPEN
  OPEN --> ARCHIVED: user archive action
  ARCHIVED --> OPEN: user restore action
  OPEN --> DELETED: soft delete
  ARCHIVED --> DELETED: soft delete
  DELETED --> [*]
```

Explanation:

- `OPEN`: active chat lifecycle.
- `ARCHIVED`: hidden from active list, still recoverable.
- `DELETED`: soft-deleted lifecycle state.

### Agent Execution State

```mermaid
stateDiagram-v2
  [*] --> RECEIVED
  RECEIVED --> PROFILE_GATE
  PROFILE_GATE --> ROUTE_PROFILE_AGENT: profile incomplete
  PROFILE_GATE --> ROUTE_TARGET_AGENT: profile complete
  ROUTE_PROFILE_AGENT --> EXECUTING
  ROUTE_TARGET_AGENT --> EXECUTING
  EXECUTING --> SUCCESS
  EXECUTING --> FAILED_RETRYABLE
  FAILED_RETRYABLE --> EXECUTING: bounded retry
  FAILED_RETRYABLE --> FAILED_TERMINAL: retries exhausted
  FAILED_TERMINAL --> [*]
  SUCCESS --> [*]
```

Explanation:

- `PROFILE_GATE` enforces readiness before non-profile targets.
- `ROUTE_PROFILE_AGENT` is selected when missing required profile fields.
- `ROUTE_TARGET_AGENT` is selected only after readiness passes.
- Retries are explicit and bounded, with failure terminal states persisted for audit.

---

## Configuration

### Environment Variables

| Variable                                    | Required | Default                           | Description                                     |
| ------------------------------------------- | -------- | --------------------------------- | ----------------------------------------------- |
| **Database**                                |          |                                   |                                                 |
| `DB_HOST`                                   | No       | `localhost`                       | MySQL host                                      |
| `DB_PORT`                                   | No       | `3306`                            | MySQL port                                      |
| `DB_NAME`                                   | No       | `ouroboros_orchestrator_db`       | Database name                                   |
| `DB_USERNAME`                               | No       | `root`                            | MySQL user                                      |
| `DB_PASSWORD`                               | Yes      | —                                 | MySQL password                                  |
| `DB_POOL_SIZE`                              | No       | `10`                              | Max connections in pool                         |
| **JWT (RS256)**                             |          |                                   |                                                 |
| `JWT_PRIVATE_KEY`                           | Yes      | —                                 | RSA private key PEM (escape newlines as `\n`)   |
| `JWT_PUBLIC_KEY`                            | Yes      | —                                 | RSA public key PEM                              |
| `JWT_ACCESS_TOKEN_EXP_SECONDS`              | No       | `900`                             | Access token TTL (15 min)                       |
| `JWT_REFRESH_TOKEN_EXP_SECONDS`             | No       | `604800`                          | Refresh token TTL (7 days)                      |
| `JWT_ISSUER`                                | No       | `ouroboros.ai/auth`               | Token issuer claim                              |
| `JWT_AUDIENCE`                              | No       | `ouroboros-api`                   | Token audience claim                            |
| **Twilio**                                  |          |                                   |                                                 |
| `TWILIO_ACCOUNT_SID`                        | Yes      | —                                 | Twilio Account SID                              |
| `TWILIO_AUTH_TOKEN`                         | Yes      | —                                 | Twilio Auth Token                               |
| `TWILIO_PHONE_NUMBER`                       | Yes      | —                                 | Twilio sender number (E.164)                    |
| `TWILIO_VERIFY_SERVICE_SID`                 | No       | —                                 | Twilio Verify service (optional)                |
| **OTP**                                     |          |                                   |                                                 |
| `OTP_EXPIRY_SECONDS`                        | No       | `300`                             | OTP validity (5 min)                            |
| `OTP_MAX_ATTEMPTS`                          | No       | `3`                               | Max failed OTP attempts                         |
| `OTP_COOLDOWN_SECONDS`                      | No       | `30`                              | Min seconds between sends                       |
| `OTP_RATE_LIMIT_MAX_REQUESTS`               | No       | `3`                               | Max OTPs per rate window                        |
| `OTP_RATE_LIMIT_WINDOW_SECONDS`             | No       | `900`                             | Rate limit window (15 min)                      |
| `MFA_OTP_DAILY_LIMIT`                       | No       | `10`                              | Max MFA OTPs per user per day                   |
| **Internal Service JWT**                    |          |                                   |                                                 |
| `INTERNAL_TOKEN_ENABLED`                    | No       | `false`                           | Enable internal bearer token issuance           |
| `INTERNAL_TOKEN_ISSUER`                     | No       | `ouroboros-orchestrator-internal` | Issuer claim for downstream services            |
| `INTERNAL_TOKEN_TTL_SECONDS`                | No       | `120`                             | Short-lived internal token TTL                  |
| `INTERNAL_TOKEN_SIGNING_ALGORITHM`          | No       | `RS256`                           | Signing algorithm for internal JWTs             |
| `INTERNAL_TOKEN_ACTIVE_KID`                 | No       | `internal-v1`                     | Active key id for rotation                      |
| `INTERNAL_TOKEN_PRIVATE_KEY`                | Yes      | —                                 | Private key PEM for internal JWTs               |
| `INTERNAL_TOKEN_PUBLIC_KEYS`                | No       | —                                 | Public keys for JWKS publication/verification   |
| `INTERNAL_TOKEN_AUDIENCE_MAP`               | No       | `{...}`                           | Target-service audience mapping                 |
| `INTERNAL_TOKEN_JWKS_CACHE_MAX_AGE_SECONDS` | No       | `60`                              | JWKS cache TTL for downstream verifiers         |
| **Downstream Service URLs**                 |          |                                   |                                                 |
| `STUDENT_PROFILE_SERVICE_URL`               | No       | —                                 | Student profile service base URL                |
| `PROGRAM_DISCOVERY_SERVICE_URL`             | No       | —                                 | Program discovery service base URL              |
| `SCHOLARSHIP_DISCOVERY_SERVICE_URL`         | No       | —                                 | Scholarship discovery service base URL          |
| `ELIGIBILITY_SERVICE_URL`                   | No       | —                                 | Eligibility engine base URL                     |
| `APPLICATION_SUPPORT_SERVICE_URL`           | No       | —                                 | Application support service base URL            |
| **Password Reset**                          |          |                                   |                                                 |
| `FORGOT_PASSWORD_COOLDOWN_DAYS`             | No       | `7`                               | Min days between forgot-password resets         |
| `RESET_PASSWORD_COOLDOWN_DAYS`              | No       | `30`                              | Min days between authenticated password changes |
| **Application**                             |          |                                   |                                                 |
| `LOG_LEVEL`                                 | No       | `INFO`                            | Logging level                                   |
| `ALLOW_DB_FAILURE`                          | No       | `false`                           | Skip DB on startup (tests only)                 |
| `CORS_ORIGINS`                              | No       | `http://localhost:8080,...`       | Allowed origins                                 |
| `ALLOWED_COUNTRY_CODES`                     | No       | `["SG","IN",...]`                 | Allowed phone countries (JSON array)            |

Docker, inter-service, and agent settings are documented in `.env.example`.

---

## Database Schema

### Tables

| Table           | Purpose                                                                                                                 |
| --------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `users`         | User accounts: phone-based auth, OTP fields, profile data (first/last name, gender, email, profession, interest)        |
| `auth_sessions` | JWT session tracking — one row per login. Tracks `last_active_at` and `revoked_at` for session duration                 |
| `otp_logs`      | Audit trail for OTP events with context (signup/mfa/forgot_password) for per-flow rate limits                           |
| `projects`      | User-defined folders for organizing chats. Has name, description, color, icon, and chat_count                           |
| `chats`         | Chat sessions — one per conversation. Tracks title, is_starred, project_id, message_count, soft-delete via `deleted_at` |
| `messages`      | Messages within chats. Role: `user`, `assistant`, or `system`. JSON metadata for future agent routing                   |

### Users Table

| Column                | Type         | Description                                                                    |
| --------------------- | ------------ | ------------------------------------------------------------------------------ |
| `id`                  | VARCHAR(36)  | UUID v4 primary key                                                            |
| `username`            | VARCHAR(50)  | Unique, 3-20 chars                                                             |
| `phone_number`        | VARCHAR(20)  | E.164 format, unique                                                           |
| `phone_country_code`  | VARCHAR(5)   | ISO 3166-1 alpha-2                                                             |
| `phone_verified`      | BOOLEAN      | OTP verification status                                                        |
| `password_hash`       | TEXT         | bcrypt hash                                                                    |
| `first_name`          | VARCHAR(50)  | Required on signup                                                             |
| `last_name`           | VARCHAR(50)  | Required on signup                                                             |
| `email`               | VARCHAR(255) | Optional, set during profile completion                                        |
| `gender`              | ENUM         | `male`, `female`, `other`, or `prefer_not_to_say`                              |
| `about_me`            | TEXT         | Short bio                                                                      |
| `profession`          | VARCHAR(100) | User's profession                                                              |
| `interest`            | ENUM         | `jobs`, `startups`, `research`, or `degree`                                    |
| `profile_completed`   | BOOLEAN      | `true` only when gender, email, about_me, profession, and interest are all set |
| `mfa_enabled`         | BOOLEAN      | When `true`, login requires additional SMS OTP verification                    |
| `password_changed_at` | DATETIME     | Last password change (enforces cooldown limits)                                |

### Auth Sessions Table

| Column           | Type         | Description                                     |
| ---------------- | ------------ | ----------------------------------------------- |
| `id`             | VARCHAR(36)  | Session UUID (also used as `sid` in JWT claims) |
| `user_id`        | VARCHAR(36)  | FK → users.id (CASCADE delete)                  |
| `token_hash`     | VARCHAR(255) | SHA-256 hash of current refresh token JTI       |
| `expires_at`     | DATETIME     | Session expiry (UTC)                            |
| `is_revoked`     | BOOLEAN      | Set to `true` on logout                         |
| `revoked_at`     | DATETIME     | When the session was revoked                    |
| `last_active_at` | DATETIME     | Updated on each token refresh                   |
| `user_agent`     | TEXT         | Client user-agent at login                      |
| `ip_address`     | VARCHAR(50)  | Client IP at session creation                   |

### Projects Table

| Column        | Type         | Description                                          |
| ------------- | ------------ | ---------------------------------------------------- |
| `id`          | VARCHAR(36)  | UUID v4 primary key                                  |
| `user_id`     | VARCHAR(36)  | FK → users.id (CASCADE delete)                       |
| `name`        | VARCHAR(100) | Project name (required)                              |
| `description` | TEXT         | Optional project description                         |
| `color`       | VARCHAR(7)   | Hex color code for UI (e.g., `#3B82F6`)              |
| `icon`        | VARCHAR(50)  | Icon identifier for UI (e.g., `folder`, `briefcase`) |
| `chat_count`  | INT          | Denormalized count of chats in this project          |
| `created_at`  | DATETIME     | Project creation time (UTC)                          |
| `updated_at`  | DATETIME     | Last activity (UTC)                                  |
| `deleted_at`  | DATETIME     | Soft delete marker                                   |

### Chats Table

| Column          | Type         | Description                                   |
| --------------- | ------------ | --------------------------------------------- |
| `id`            | VARCHAR(36)  | UUID v4 primary key                           |
| `user_id`       | VARCHAR(36)  | FK → users.id (CASCADE delete)                |
| `title`         | VARCHAR(255) | Auto-generated from first message or user-set |
| `status`        | ENUM         | `active` or `archived`                        |
| `is_starred`    | BOOLEAN      | User-marked as favorite (default `false`)     |
| `project_id`    | VARCHAR(36)  | FK → projects.id (SET NULL on project delete) |
| `message_count` | INT          | Denormalized count for list view performance  |
| `created_at`    | DATETIME     | Chat creation time (UTC)                      |
| `updated_at`    | DATETIME     | Last activity (UTC)                           |
| `deleted_at`    | DATETIME     | Soft delete marker                            |

### Messages Table

| Column       | Type        | Description                                                  |
| ------------ | ----------- | ------------------------------------------------------------ |
| `id`         | VARCHAR(36) | UUID v4 primary key                                          |
| `chat_id`    | VARCHAR(36) | FK → chats.id (CASCADE delete)                               |
| `role`       | ENUM        | `user`, `assistant`, or `system`                             |
| `content`    | TEXT        | Message content                                              |
| `metadata`   | JSON        | Future: agent_ids, routing_decision, token_count, latency_ms |
| `created_at` | DATETIME    | Message timestamp (UTC)                                      |

### Workflow and Audit Tables

| Table              | Purpose                                                                                |
| ------------------ | -------------------------------------------------------------------------------------- |
| `workflow_runs`    | Per-run orchestration metadata for profile-readiness and agent execution               |
| `workflow_context` | Optional per-chat or per-request cached workflow state                                 |
| `agent_call_logs`  | Downstream call attempts, responses, errors, trace ids, session ids, and retry linkage |

### Migrations

```
migrations/
├── 001_create_users.sql   # users + auth_sessions + otp_logs
└── 002_create_chats.sql   # projects + chats + messages
```

All migrations are **idempotent** using `CREATE TABLE IF NOT EXISTS` — safe to re-run.

---

## API Endpoints

**Base URL**: `http://localhost:8000`

### Authentication (`/auth`)

| Method | Path                           | Auth   | Description                                                               |
| ------ | ------------------------------ | ------ | ------------------------------------------------------------------------- |
| POST   | `/auth/signup`                 | Public | Register with phone, username, first/last name + password; sends OTP      |
| POST   | `/auth/verify-otp`             | Public | Verify OTP; returns JWT tokens                                            |
| POST   | `/auth/resend-otp`             | Public | Resend OTP (rate-limited)                                                 |
| POST   | `/auth/login`                  | Public | Phone or username + password; returns tokens (200) or MFA challenge (202) |
| POST   | `/auth/refresh`                | Public | Rotate refresh token → new token pair                                     |
| POST   | `/auth/logout`                 | Bearer | Revoke current session                                                    |
| GET    | `/auth/me`                     | Bearer | Current user profile                                                      |
| PATCH  | `/auth/profile`                | Bearer | Update profile (gender, email, about me, profession, interest)            |
| GET    | `/auth/profile-status`         | Bearer | Check profile/phone verification status                                   |
| GET    | `/auth/sessions`               | Bearer | List active sessions (or all with `?active_only=false`)                   |
| POST   | `/auth/mfa/toggle`             | Bearer | Enable or disable MFA for the current user                                |
| POST   | `/auth/mfa/verify`             | Public | Verify MFA OTP to complete login (after 202 challenge)                    |
| POST   | `/auth/forgot-password`        | Public | Request OTP for password reset (1/week limit)                             |
| POST   | `/auth/forgot-password/verify` | Public | Verify OTP and set new password                                           |
| POST   | `/auth/reset-password`         | Bearer | Change password with current password (1/month limit)                     |

### Chat Sessions (`/api/v1/chats`)

| Method | Path                          | Auth   | Description                                                  |
| ------ | ----------------------------- | ------ | ------------------------------------------------------------ |
| POST   | `/api/v1/chats`               | Bearer | Create new chat (optionally with message and/or project)     |
| GET    | `/api/v1/chats`               | Bearer | List user's chats (paginated, filterable by starred/project) |
| GET    | `/api/v1/chats/{id}`          | Bearer | Get single chat by ID                                        |
| PATCH  | `/api/v1/chats/{id}`          | Bearer | Update chat (title, is_starred, project_id)                  |
| DELETE | `/api/v1/chats/{id}`          | Bearer | Soft-delete chat                                             |
| POST   | `/api/v1/chats/{id}/messages` | Bearer | Send message and get assistant response                      |
| GET    | `/api/v1/chats/{id}/messages` | Bearer | Get message history (paginated)                              |

### Projects (`/api/v1/projects`)

| Method | Path                    | Auth   | Description                                     |
| ------ | ----------------------- | ------ | ----------------------------------------------- |
| POST   | `/api/v1/projects`      | Bearer | Create new project                              |
| GET    | `/api/v1/projects`      | Bearer | List user's projects (paginated)                |
| GET    | `/api/v1/projects/{id}` | Bearer | Get single project by ID                        |
| PATCH  | `/api/v1/projects/{id}` | Bearer | Update project (name, description, color, icon) |
| DELETE | `/api/v1/projects/{id}` | Bearer | Soft-delete project (chats remain, unassigned)  |

### Health

| Method | Path      | Auth   | Description                                      |
| ------ | --------- | ------ | ------------------------------------------------ |
| GET    | `/`       | Public | Root health check (message, version, status)     |
| GET    | `/health` | Public | Detailed health with database connectivity check |

### Workflows

| Method | Path                                                      | Auth   | Description                           |
| ------ | --------------------------------------------------------- | ------ | ------------------------------------- |
| GET    | `/api/v1/workflows/users/me/profile-readiness`            | Bearer | Read current profile readiness state  |
| GET    | `/api/v1/workflows/chats/{chat_id}/status`                | Bearer | Read orchestration status for a chat  |
| POST   | `/api/v1/workflows/chats/{chat_id}/retry-last-agent-call` | Bearer | Retry the last failed downstream call |

### Internal

| Method | Path                              | Auth   | Description                                  |
| ------ | --------------------------------- | ------ | -------------------------------------------- |
| GET    | `/internal/.well-known/jwks.json` | Public | Public keys for internal bearer verification |

### API Documentation

- **Swagger UI**: http://localhost:8000/docs — All `/auth` routes include **named request examples** (e.g. phone-only vs username-only login, profile completion, MFA, password flows) plus documented status codes (including SMS failures and rate limits).
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

Use **Authorize** in Swagger and paste the JWT access token (no "Bearer " prefix).

---

## Auth Flow

### Signup → OTP → Login → Profile Completion

```
1. POST /auth/signup
   Body: { username, phone_number, password, first_name, last_name }
   → User created (unverified), OTP sent via Twilio

2. POST /auth/verify-otp
   Body: { phone_number, otp_code }
   → Phone verified, JWT tokens returned

3. POST /auth/login
   Body: { phone_number, password }  OR  { username, password }
   → 200: JWT tokens returned (MFA off)
   → 202: { mfa_required: true, user_id, phone_number } (MFA on)

3b. POST /auth/mfa/verify   (only when login returns 202)
    Body: { user_id, otp_code }
    → JWT tokens returned after OTP verification

4. PATCH /auth/profile   (first login — complete profile)
   Body: { gender, email, about_me, profession, interest }
   → `profile_completed` is set to **true** only when **all five** fields are present
```

### MFA (Multi-Factor Authentication)

Users can enable MFA from their settings. When enabled, every login triggers an additional SMS OTP challenge (max **10 per day**):

1. `POST /auth/mfa/toggle` — `{ "enabled": true }` (requires verified phone)
2. On next login, the server returns `202` with `mfa_required: true`
3. Client calls `POST /auth/mfa/verify` with the OTP to get JWT tokens
4. `POST /auth/mfa/toggle` — `{ "enabled": false }` to disable

### Forgot Password

```
1. POST /auth/forgot-password
   Body: { phone_number }
   → OTP sent to verified phone (limited to 1/week since last password change)

2. POST /auth/forgot-password/verify
   Body: { user_id, otp_code, new_password }
   → Password updated, all sessions revoked, user must login again
```

### Reset Password (Authenticated)

```
POST /auth/reset-password   (requires Bearer token)
Body: { current_password, new_password }
→ Password updated, all sessions revoked (limited to 1/month)
```

### Token Lifecycle

```
Access Token  (15 min)  ──→  Protected endpoints via Authorization: Bearer <token>
Refresh Token (7 days)  ──→  POST /auth/refresh → new token pair (old rotated)
Logout                  ──→  POST /auth/logout → session revoked (revoked_at stamped)
```

### Session Tracking

Each login creates a row in `auth_sessions`. The `last_active_at` column is updated on every token refresh, and `revoked_at` is stamped on logout. This enables:

- **Active devices** — `GET /auth/sessions` shows where the user is logged in
- **Session duration** — `revoked_at - created_at` (or `last_active_at - created_at` for active sessions)
- **Security audit** — see IP address and user-agent for every session

---

## Chat Flow

### Create Chat → Send Messages → Get History

```
1. POST /api/v1/chats
   Body: {}
   Body: { "message": "Help me find scholarships" }
   Body: { "message": "...", "project_id": "proj-uuid" }
   → Returns ChatResponse (if message provided, also creates user + assistant messages)

2. POST /api/v1/chats/{id}/messages
   Body: { "content": "What scholarships are available for international students?" }
   → Returns SendMessageResponse with user_message, assistant_message, and updated chat

3. GET /api/v1/chats/{id}/messages?limit=50&order=asc
   → Returns PaginatedMessagesResponse with messages array and next_cursor
```

### Chat Filters

List chats with optional filters:

```
GET /api/v1/chats                           # All chats
GET /api/v1/chats?starred=true              # Only starred chats
GET /api/v1/chats?starred=false             # Only non-starred chats
GET /api/v1/chats?project_id=proj-uuid      # Chats in specific project
GET /api/v1/chats?no_project=true           # Chats not in any project
```

### Star and Organize Chats

```
PATCH /api/v1/chats/{id}
Body: { "is_starred": true }                # Star a chat
Body: { "is_starred": false }               # Unstar a chat
Body: { "project_id": "proj-uuid" }         # Move to project
Body: { "project_id": "" }                  # Remove from project
Body: { "title": "New Title", "is_starred": true, "project_id": "proj-uuid" }  # Update multiple
```

### Chat Response Types

**ChatResponse** (returned by create, get, update):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Scholarship Search for CS Programs",
  "status": "active",
  "is_starred": true,
  "project_id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message_count": 4,
  "created_at": "2026-04-10T12:00:00Z",
  "updated_at": "2026-04-10T12:05:00Z"
}
```

**SendMessageResponse** (returned by send message):

```json
{
  "user_message": {
    "id": "msg-user-123",
    "chat_id": "550e8400-e29b-41d4-a716-446655440000",
    "role": "user",
    "content": "What scholarships are available?",
    "metadata": null,
    "created_at": "2026-04-10T12:05:00Z"
  },
  "assistant_message": {
    "id": "msg-asst-456",
    "chat_id": "550e8400-e29b-41d4-a716-446655440000",
    "role": "assistant",
    "content": "Thanks for your message! I'm Ouroboros...",
    "metadata": null,
    "created_at": "2026-04-10T12:05:01Z"
  },
  "chat": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "What scholarships are available?",
    "status": "active",
    "is_starred": false,
    "project_id": null,
    "message_count": 2,
    "created_at": "2026-04-10T12:00:00Z",
    "updated_at": "2026-04-10T12:05:01Z"
  }
}
```

**PaginatedChatsResponse** (returned by list chats):

```json
{
  "chats": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Singapore Scholarship Search",
      "status": "active",
      "is_starred": true,
      "project_id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "message_count": 8,
      "created_at": "2026-04-10T12:00:00Z",
      "updated_at": "2026-04-10T14:30:00Z"
    }
  ],
  "next_cursor": "MjAyNi0wNC0xMFQxMjowMDowMFo=",
  "total_count": 15
}
```

---

## Project Flow

### Create Project → Organize Chats

```
1. POST /api/v1/projects
   Body: { "name": "Singapore Scholarships" }
   Body: { "name": "...", "description": "...", "color": "#3B82F6", "icon": "folder" }
   → Returns ProjectResponse

2. PATCH /api/v1/chats/{chat_id}
   Body: { "project_id": "proj-uuid" }
   → Moves chat to project, updates chat_count

3. GET /api/v1/chats?project_id=proj-uuid
   → Lists all chats in the project
```

### Project Response Types

**ProjectResponse** (returned by create, get, update):

```json
{
  "id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Singapore Scholarships",
  "description": "Research on scholarship opportunities in Singapore",
  "color": "#3B82F6",
  "icon": "graduation-cap",
  "chat_count": 5,
  "created_at": "2026-04-10T12:00:00Z",
  "updated_at": "2026-04-10T14:30:00Z"
}
```

**PaginatedProjectsResponse** (returned by list projects):

```json
{
  "projects": [
    {
      "id": "proj-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "name": "Singapore Scholarships",
      "description": "Research on Singapore opportunities",
      "color": "#3B82F6",
      "icon": "graduation-cap",
      "chat_count": 5,
      "created_at": "2026-04-10T12:00:00Z",
      "updated_at": "2026-04-10T14:30:00Z"
    }
  ],
  "next_cursor": "MjAyNi0wNC0wOVQxMTowMDowMFo=",
  "total_count": 8
}
```

### Project Deletion

`DELETE /api/v1/projects/{id}` soft-deletes the project. **Chats remain** but lose their project assignment (project_id set to NULL). Chat counts are automatically maintained.

---

## Pagination

All list endpoints use **cursor-based pagination**:

- `limit`: Number of items to return (1-100, default 20 for chats, 50 for messages/projects)
- `cursor`: Pass `next_cursor` from previous response to get next page
- `order`: For messages only — `asc` (oldest first, default) or `desc` (newest first)

**Cursor Format:**

- **Chats/Projects**: Base64-encoded ISO timestamp of last item's `updated_at`
- **Messages**: Base64-encoded JSON with `{"t": "<ISO timestamp>", "id": "<message-uuid>"}` for stable ordering

**Timestamp Precision:**

The database uses `DATETIME(6)` (microsecond precision) to prevent duplicate timestamps when creating multiple records in quick succession. Message ordering uses `(created_at, id)` as a composite key to guarantee deterministic pagination even when timestamps collide.

### Auto-Generated Titles

When sending the first message to a chat, the title is automatically set from the message content (first 50 characters, truncated at word boundary with "...").

### Soft Delete

`DELETE /api/v1/chats/{id}` and `DELETE /api/v1/projects/{id}` set `deleted_at` timestamp. Deleted items are excluded from list results but retained for potential recovery.

### Ownership Validation

All chat and project endpoints validate that the authenticated user owns the resource. Returns **404** (not 403) for both not-found and not-owned to prevent user enumeration.

---

## Development Workflow

### Code Quality Checks

```bash
black app/ tests/ scripts/
isort app/ tests/ scripts/
flake8 app/ tests/ scripts/ --max-line-length=120 --extend-ignore=E203,W503,E501
mypy app/ --ignore-missing-imports --no-strict-optional
```

### Pre-Commit Script

```bash
chmod +x pre-commit-check.sh
./pre-commit-check.sh
```

Runs: Black, isort, flake8, syntax validation, pytest, pylint, Bandit, and mypy.

---

## Testing

### Run All Tests

```bash
ALLOW_DB_FAILURE=true pytest tests/ -v
```

### Run with Coverage

```bash
ALLOW_DB_FAILURE=true pytest tests/ --cov=app --cov-report=html -v
open htmlcov/index.html
```

### Seed Data

The seed script creates five OuroborosAI team members for local testing:

| Username | Name              | Phone          | Email                   |
| -------- | ----------------- | -------------- | ----------------------- |
| Maugus   | Ahan Jaiswal      | +91-9818772178 | ahanjaiswal12@gmail.com |
| NPT      | Phu Truong Nguyen | +65-81234501   | phu@gmail.com           |
| Feri     | Feri Setiawan     | +65-81234502   | feri@gmail.com          |
| Stella   | Xingyuan Liu      | +65-81234503   | xingyuan@gmail.com      |
| Lantya   | Lanting Zhao      | +65-81234504   | lanting@gmail.com       |

All share password: `Admin123@`

### Test Structure

```
tests/
├── conftest.py                     # RSA key generation, shared fixtures
├── unit/
│   ├── test_auth_service.py        # Signup, OTP, login, MFA, logout (mocked)
│   ├── test_chat_service.py        # Chat CRUD, messages, starred, project (mocked)
│   ├── test_chat_models.py         # Chat/message Pydantic model validation
│   ├── test_project_service.py     # Project CRUD (mocked)
│   ├── test_project_models.py      # Project Pydantic model validation
│   ├── test_jwt_util.py            # Token generation and validation
│   ├── test_password_util.py       # bcrypt hash/verify
│   ├── test_phone_util.py          # Phone validation and masking
│   ├── test_otp_util.py            # OTP generation and expiry
│   ├── test_profile_completion.py  # profile_completed field rules
│   └── test_config.py              # Configuration loading
└── integration/
    └── (future integration tests)
```

---

## CI/CD Pipeline

**Workflow**: `.github/workflows/deploy.yml`

**Trigger**: Pull requests to `main` or `develop`

| Stage              | Description                     |
| ------------------ | ------------------------------- |
| **Format**         | Black + isort validation        |
| **Lint**           | flake8 + pylint                 |
| **Unit Tests**     | pytest with JUnit XML output    |
| **Type Check**     | mypy static analysis            |
| **Security Audit** | Bandit static security analysis |
| **Docker Build**   | Verify image builds             |
| **Summary**        | Markdown table of results       |

---

## Deployment

### Docker Compose (Full Stack)

```bash
docker compose up --build -d
docker compose logs -f
docker compose down
docker compose down -v
```

Backend on port **8000**, MySQL on `DOCKER_MYSQL_PORT` (default **3307**).

### Docker (Service Only)

```bash
docker build -t ouroboros-orchestrator .

docker run -p 8000:8000 \
  --env-file .env \
  -e DB_HOST=mysql-host \
  -e DB_PASSWORD=secret \
  ouroboros-orchestrator
```

Ensure `.env` contains `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, and Twilio variables (same escaped-PEM format as local dev). Alternatively pass `-e JWT_PRIVATE_KEY='...'` with a properly escaped single-line PEM string.

---

## Project Structure

```
ouroboros-ai-orchestrator/
├── app/
│   ├── api/                        # HTTP route handlers (thin — delegate to services)
│   │   ├── auth.py                 # Auth endpoints (signup, OTP, login, profile, sessions)
│   │   ├── chats.py                # Chat endpoints (CRUD, messages, starred, project)
│   │   ├── projects.py             # Project endpoints (CRUD)
│   │   └── health.py               # GET / and /health
│   ├── core/                       # Infrastructure with startup/shutdown lifecycle
│   │   ├── database.py             # aiomysql async connection pool (create, close, get)
│   │   └── logging.py              # structlog configuration (setup_logging, get_logger)
│   ├── services/                   # Business logic (no SQL, no HTTP)
│   │   ├── auth_service.py         # Auth orchestration (signup → OTP → login → tokens)
│   │   ├── chat_service.py         # Chat CRUD, message handling, starred, project assignment
│   │   ├── project_service.py      # Project CRUD, chat count management
│   │   └── twilio_service.py       # Twilio OTP delivery
│   ├── models/                     # Pydantic request/response schemas
│   │   ├── common.py               # StandardResponse, PaginatedResponse
│   │   ├── auth.py                 # Auth models with Swagger examples
│   │   ├── chat.py                 # Chat/message models with Swagger examples
│   │   └── project.py              # Project models with Swagger examples
│   ├── repositories/               # Data access (raw SQL, uses pool from core)
│   │   ├── user_repo.py            # User CRUD
│   │   ├── auth_repo.py            # Auth sessions & OTP audit logs
│   │   ├── chat_repo.py            # Chat CRUD (soft delete, starred, project, pagination)
│   │   ├── message_repo.py         # Message CRUD (pagination by chat)
│   │   └── project_repo.py         # Project CRUD (soft delete, pagination)
│   ├── middleware/
│   │   ├── auth_middleware.py      # JWT RS256 validation + get_current_user
│   │   └── logging_middleware.py   # X-Trace-ID propagation
│   ├── utils/                      # Stateless helper functions
│   │   ├── jwt_util.py             # RS256 JWT encode/decode
│   │   ├── password_util.py        # bcrypt hash/verify
│   │   ├── phone_util.py           # Phone validation (E.164) and masking
│   │   ├── otp_util.py             # OTP generation, expiry, cooldown
│   │   ├── profile_completion.py   # When profile_completed should be true
│   │   ├── timezone.py             # UTC normalization and ISO serialization
│   │   ├── helpers.py              # generate_uuid, utc_now, get_current_time
│   │   ├── utc_json_response.py    # UTC-aware JSON response class
│   │   ├── exceptions.py           # Custom exception hierarchy
│   │   └── trace_id.py             # UUID-v4 trace ID generation
│   ├── config.py                   # Pydantic settings from .env
│   └── main.py                     # FastAPI app, lifespan, middleware, OpenAPI
├── migrations/
│   └── 001_create_users.sql        # users + auth_sessions + otp_logs
├── scripts/
│   ├── run_migrations.py           # Execute migrations in order
│   └── seed_users.py               # Seed OuroborosAI team members
├── tests/
│   ├── conftest.py                 # RSA key fixtures
│   ├── unit/                       # Unit tests (mocked DB & Twilio)
│   └── integration/                # Future integration tests
├── .github/workflows/deploy.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── pytest.ini
├── .flake8
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── start.sh
├── pre-commit-check.sh
└── README.md
```

Additional workflow and token modules live in `app/clients/`, `app/security/`, and the workflow docs at the repo root.

### Why `app/core/`?

The orchestrator uses async I/O (`aiomysql`), which means infrastructure like the database pool **must be created at startup** (via `await`) and torn down on shutdown. `app/core/` holds these lifecycle-bound resources — things that initialize before the app handles any requests and clean up when it stops. Stateless helpers live in `app/utils/`; data access lives in `app/repositories/`.

---

## Troubleshooting

| Issue                          | Fix                                                                                                                 |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| Can't connect to MySQL         | Check MySQL is running. Verify `DB_*` in `.env`. Confirm the database exists.                                       |
| JWT or auth errors             | Ensure `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY` are set with `\n` for newlines. Regenerate with OpenSSL if needed.    |
| Internal downstream 401 errors | Verify internal token env vars, `aud` mapping, `iss`, `kid`, and JWKS cache/public key config.                      |
| JWKS endpoint returns 503      | Configure `INTERNAL_TOKEN_PRIVATE_KEY` and/or `INTERNAL_TOKEN_PUBLIC_KEYS`.                                         |
| Twilio OTP not sending         | Verify `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` in `.env`. Check Twilio console for errors. |
| Import errors                  | Activate venv: `source venv/bin/activate && pip install -r requirements.txt`                                        |
| Port 8000 in use               | Use `--port 8001` or stop the existing process.                                                                     |
| Tests fail locally             | Run with `ALLOW_DB_FAILURE=true pytest tests/ -v`                                                                   |

---

## Error Responses

| Status  | Example                                                                                                                            |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **400** | `{"detail": "Invalid OTP code"}`                                                                                                   |
| **401** | `{"detail": "Invalid credentials"}`                                                                                                |
| **403** | `{"detail": "Account is disabled"}`                                                                                                |
| **404** | `{"detail": "User not found"}`                                                                                                     |
| **409** | `{"detail": "Phone number already registered"}`                                                                                    |
| **422** | Pydantic validation errors                                                                                                         |
| **429** | `{"detail": "Too many OTP requests. Please try again later."}` (also MFA daily limit, password cooldowns)                          |
| **500** | `{"detail": "Failed to send OTP. Please try again."}` when Twilio SMS fails (signup, resend, forgot-password, MFA login challenge) |

**Note:** If signup returns **500** after Twilio fails, the user row may already exist; use **resend-otp** once SMS is working, or remove the row and sign up again during development.

---

## Attribution

**Developed by**: OuroborosAI Developer Team

**Project**: Ouroboros AI Scholarship Discovery Platform

**Repository**: [github.com/maugus0/ouroboros-ai-orchestrator](https://github.com/maugus0/ouroboros-ai-orchestrator)
