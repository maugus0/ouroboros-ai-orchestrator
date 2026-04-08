# Ouroboros Orchestrator Service

Central coordination service for the **Ouroboros AI** scholarship discovery platform. The Orchestrator is the single backend entry-point the frontend communicates with — handling authentication, user management, and health monitoring, with business logic (workflows, agents, chats) to be added incrementally.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
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
4. **Manages user profiles** with a completion flow (email, profession, interest)
5. **Tracks sessions** with active-device visibility and duration metrics
6. **Exposes a health endpoint** for monitoring and readiness checks

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
│  │  GET  / and /health                         │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Middleware (JWT RS256, CORS, Logging)       │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Service Layer (auth_service, twilio_service)│     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Repository Layer (raw SQL / aiomysql)       │     │
│  │  UserRepository, AuthRepository             │     │
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

### Authentication Strategy

| Concern | Approach |
|---------|----------|
| Registration | Phone number + username + first/last name + password (OTP verification required) |
| Login | Phone number **or** username + password |
| Password storage | **bcrypt** (cost factor 12) |
| Token signing | **RS256** (RSA private key signs, public key verifies) |
| Access token | 15 min TTL, claims: `{sub, token_type, username, phone, sid}` |
| Refresh token | 7 day TTL, SHA-256 hashed in DB, rotation on use |
| Phone verification | Twilio OTP (6-digit, 5 min expiry, max 3 attempts) |
| Session tracking | `auth_sessions` table with `last_active_at`, `revoked_at` for duration metrics |
| Profile completion | First login: email, about me, profession, interest (jobs/startups/research) |

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Runtime |
| MySQL | 8.0+ | Database |
| Twilio account | — | OTP delivery |
| Docker | 24.0+ | Containerised deployment (optional) |

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

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| **Database** ||||
| `DB_HOST` | No | `localhost` | MySQL host |
| `DB_PORT` | No | `3306` | MySQL port |
| `DB_NAME` | No | `ouroboros_orchestrator_db` | Database name |
| `DB_USERNAME` | No | `root` | MySQL user |
| `DB_PASSWORD` | Yes | — | MySQL password |
| `DB_POOL_SIZE` | No | `10` | Max connections in pool |
| **JWT (RS256)** ||||
| `JWT_PRIVATE_KEY` | Yes | — | RSA private key PEM (escape newlines as `\n`) |
| `JWT_PUBLIC_KEY` | Yes | — | RSA public key PEM |
| `JWT_ACCESS_TOKEN_EXP_SECONDS` | No | `900` | Access token TTL (15 min) |
| `JWT_REFRESH_TOKEN_EXP_SECONDS` | No | `604800` | Refresh token TTL (7 days) |
| `JWT_ISSUER` | No | `ouroboros.ai/auth` | Token issuer claim |
| `JWT_AUDIENCE` | No | `ouroboros-api` | Token audience claim |
| **Twilio** ||||
| `TWILIO_ACCOUNT_SID` | Yes | — | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Yes | — | Twilio Auth Token |
| `TWILIO_PHONE_NUMBER` | Yes | — | Twilio sender number (E.164) |
| `TWILIO_VERIFY_SERVICE_SID` | No | — | Twilio Verify service (optional) |
| **OTP** ||||
| `OTP_EXPIRY_SECONDS` | No | `300` | OTP validity (5 min) |
| `OTP_MAX_ATTEMPTS` | No | `3` | Max failed OTP attempts |
| `OTP_COOLDOWN_SECONDS` | No | `30` | Min seconds between sends |
| `OTP_RATE_LIMIT_MAX_REQUESTS` | No | `3` | Max OTPs per rate window |
| `OTP_RATE_LIMIT_WINDOW_SECONDS` | No | `900` | Rate limit window (15 min) |
| **Application** ||||
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `ALLOW_DB_FAILURE` | No | `false` | Skip DB on startup (tests only) |
| `CORS_ORIGINS` | No | `http://localhost:8080,...` | Allowed origins |
| `ALLOWED_COUNTRY_CODES` | No | `["SG","IN",...]` | Allowed phone countries (JSON array) |

Docker, inter-service, and agent settings are documented in `.env.example`.

---

## Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `users` | User accounts: phone-based auth, OTP fields, profile data (first/last name, email, profession, interest) |
| `auth_sessions` | JWT session tracking — one row per login. Tracks `last_active_at` and `revoked_at` for session duration |
| `otp_logs` | Audit trail for OTP send/verify/fail events (rate-limiting and compliance) |

### Users Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) | UUID v4 primary key |
| `username` | VARCHAR(50) | Unique, 3-20 chars |
| `phone_number` | VARCHAR(20) | E.164 format, unique |
| `phone_country_code` | VARCHAR(5) | ISO 3166-1 alpha-2 |
| `phone_verified` | BOOLEAN | OTP verification status |
| `password_hash` | TEXT | bcrypt hash |
| `first_name` | VARCHAR(50) | Required on signup |
| `last_name` | VARCHAR(50) | Required on signup |
| `email` | VARCHAR(255) | Optional, set during profile completion |
| `about_me` | TEXT | Short bio |
| `profession` | VARCHAR(100) | User's profession |
| `interest` | ENUM | `jobs`, `startups`, or `research` |
| `profile_completed` | BOOLEAN | Set to `true` on first profile update |

### Auth Sessions Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) | Session UUID (also used as `sid` in JWT claims) |
| `user_id` | VARCHAR(36) | FK → users.id (CASCADE delete) |
| `token_hash` | VARCHAR(255) | SHA-256 hash of current refresh token JTI |
| `expires_at` | DATETIME | Session expiry (UTC) |
| `is_revoked` | BOOLEAN | Set to `true` on logout |
| `revoked_at` | DATETIME | When the session was revoked |
| `last_active_at` | DATETIME | Updated on each token refresh |
| `user_agent` | TEXT | Client user-agent at login |
| `ip_address` | VARCHAR(50) | Client IP at session creation |

### Migrations

```
migrations/
└── 001_create_users.sql   # users + auth_sessions + otp_logs
```

---

## API Endpoints

**Base URL**: `http://localhost:8000`

### Authentication (`/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/signup` | Public | Register with phone, username, first/last name + password; sends OTP |
| POST | `/auth/verify-otp` | Public | Verify OTP; returns JWT tokens |
| POST | `/auth/resend-otp` | Public | Resend OTP (rate-limited) |
| POST | `/auth/login` | Public | Phone number **or** username + password login |
| POST | `/auth/refresh` | Public | Rotate refresh token → new token pair |
| POST | `/auth/logout` | Bearer | Revoke current session |
| GET | `/auth/me` | Bearer | Current user profile |
| PATCH | `/auth/profile` | Bearer | Update profile (email, about me, profession, interest) |
| GET | `/auth/profile-status` | Bearer | Check profile/phone verification status |
| GET | `/auth/sessions` | Bearer | List active sessions (or all with `?active_only=false`) |

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | Public | Root health check (message, version, status) |
| GET | `/health` | Public | Detailed health with database connectivity check |

### API Documentation

- **Swagger UI**: http://localhost:8000/docs — All endpoints with request/response examples
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
   → JWT tokens returned, response includes profile_completed flag

4. PATCH /auth/profile   (first login — complete profile)
   Body: { email, about_me, profession, interest }
   → Profile marked as completed
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

| Username | Name | Phone | Email |
|----------|------|-------|-------|
| Maugus | Ahan Jaiswal | +91-9818772178 | ahanjaiswal12@gmail.com |
| NPT | Phu Truong Nguyen | +65-81234501 | phu@gmail.com |
| Feri | Feri Setiawan | +65-81234502 | feri@gmail.com |
| Stella | Xingyuan Liu | +65-81234503 | xingyuan@gmail.com |
| Lantya | Lanting Zhao | +65-81234504 | lanting@gmail.com |

All share password: `Admin123@`

All seed users are pre-verified (`phone_verified = true`, `profile_completed = true`) so they can login immediately without OTP.

### Test Structure

```
tests/
├── conftest.py                     # RSA key generation, shared fixtures
├── unit/
│   ├── test_auth_service.py        # Signup, OTP, login (phone + username), logout (mocked)
│   ├── test_jwt_util.py            # Token generation and validation
│   ├── test_password_util.py       # bcrypt hash/verify
│   ├── test_phone_util.py          # Phone validation and masking
│   ├── test_otp_util.py            # OTP generation and expiry
│   └── test_config.py              # Configuration loading
└── integration/
    └── (future integration tests)
```

---

## CI/CD Pipeline

**Workflow**: `.github/workflows/deploy.yml`

**Trigger**: Pull requests to `main` or `develop`

| Stage | Description |
|-------|-------------|
| **Format** | Black + isort validation |
| **Lint** | flake8 + pylint |
| **Unit Tests** | pytest with JUnit XML output |
| **Type Check** | mypy static analysis |
| **Security Audit** | Bandit static security analysis |
| **Docker Build** | Verify image builds |
| **Summary** | Markdown table of results |

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
│   │   └── health.py               # GET / and /health
│   ├── core/                       # Infrastructure with startup/shutdown lifecycle
│   │   ├── database.py             # aiomysql async connection pool (create, close, get)
│   │   └── logging.py              # structlog configuration (setup_logging, get_logger)
│   ├── services/                   # Business logic (no SQL, no HTTP)
│   │   ├── auth_service.py         # Auth orchestration (signup → OTP → login → tokens)
│   │   └── twilio_service.py       # Twilio OTP delivery
│   ├── models/                     # Pydantic request/response schemas
│   │   ├── common.py               # StandardResponse, PaginatedResponse
│   │   └── auth.py                 # Auth models with Swagger examples
│   ├── repositories/               # Data access (raw SQL, uses pool from core)
│   │   ├── user_repo.py            # User CRUD
│   │   └── auth_repo.py            # Auth sessions & OTP audit logs
│   ├── middleware/
│   │   ├── auth_middleware.py      # JWT RS256 validation + get_current_user
│   │   └── logging_middleware.py   # X-Trace-ID propagation
│   ├── utils/                      # Stateless helper functions
│   │   ├── jwt_util.py             # RS256 JWT encode/decode
│   │   ├── password_util.py        # bcrypt hash/verify
│   │   ├── phone_util.py           # Phone validation (E.164) and masking
│   │   ├── otp_util.py             # OTP generation, expiry, cooldown
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

### Why `app/core/`?

The orchestrator uses async I/O (`aiomysql`), which means infrastructure like the database pool **must be created at startup** (via `await`) and torn down on shutdown. `app/core/` holds these lifecycle-bound resources — things that initialize before the app handles any requests and clean up when it stops. Stateless helpers live in `app/utils/`; data access lives in `app/repositories/`.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Can't connect to MySQL | Check MySQL is running. Verify `DB_*` in `.env`. Confirm the database exists. |
| JWT or auth errors | Ensure `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY` are set with `\n` for newlines. Regenerate with OpenSSL if needed. |
| Twilio OTP not sending | Verify `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` in `.env`. Check Twilio console for errors. |
| Import errors | Activate venv: `source venv/bin/activate && pip install -r requirements.txt` |
| Port 8000 in use | Use `--port 8001` or stop the existing process. |
| Tests fail locally | Run with `ALLOW_DB_FAILURE=true pytest tests/ -v` |

---

## Error Responses

| Status | Example |
|--------|---------|
| **400** | `{"detail": "Invalid OTP code"}` |
| **401** | `{"detail": "Invalid credentials"}` |
| **403** | `{"detail": "Account is disabled"}` |
| **404** | `{"detail": "User not found"}` |
| **409** | `{"detail": "Phone number already registered"}` |
| **422** | Pydantic validation errors |
| **429** | `{"detail": "Too many OTP requests. Please try again later."}` |

---

## Attribution

**Developed by**: OuroborosAI Developer Team

**Project**: Ouroboros AI Scholarship Discovery Platform

**Repository**: [github.com/maugus0/ouroboros-ai-orchestrator](https://github.com/maugus0/ouroboros-ai-orchestrator)
