# Ouroboros Orchestrator Service

Central coordination service for the **Ouroboros AI** scholarship platform.
The frontend talks only to this service; the orchestrator handles user auth, profile gating, workflow visibility, and downstream service orchestration.

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
- [Testing](#testing)
- [CI/CD Pipeline](#cicd-pipeline)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

---

## Overview

The orchestrator currently provides:

1. Phone/username authentication with RS256 JWT.
2. OTP verification with Twilio.
3. Session tracking and profile management.
4. Chat and project management endpoints.
5. Workflow endpoints for profile readiness and orchestration status.
6. Profile gate enforcement before non-profile downstream calls.
7. Orchestrator-issued internal JWT for service-to-service calls.
8. Internal JWKS endpoint for downstream verification and key rotation support.
9. Workflow and agent call audit logging (`workflow_runs`, `workflow_context`, `agent_call_logs`).

Key principles:

- Single backend entry point.
- Deterministic, cost-aware routing before expensive model paths.
- Strict profile-readiness gate for non-profile workflows.
- Short-lived audience-bound internal identity propagation.
- Structured logging with trace context.

---

## Architecture

```mermaid
flowchart LR
    FE[Frontend] -->|Bearer user token| ORCH[Orchestrator]

    ORCH --> AUTH[Auth APIs]
    ORCH --> CHAT[Chat APIs]
    ORCH --> WF[Workflow APIs]
    ORCH --> INT[Internal JWKS API]

    ORCH -->|Internal bearer token| SP[Student Profile Service]
    ORCH -->|Internal bearer token| PD[Program Discovery]
    ORCH -->|Internal bearer token| SD[Scholarship Discovery]
    ORCH -->|Internal bearer token| EE[Eligibility Engine]
    ORCH -->|Internal bearer token| AS[Application Support]

    ORCH --> DB[(MySQL)]
    ORCH --> TW[Twilio]
```

---

## Why Internal Bearer Tokens (Not X_SERVICE_TOKEN)

`X_SERVICE_TOKEN` is a shared secret model. It authenticates only the caller service, not the end-user context.

The internal bearer-token model is better because it is:

1. **Identity-preserving**: includes `sub` (user id), `sid`, and `trace_id`, so downstream services can enforce user-scoped logic directly.
2. **Audience-bound**: `aud` is specific per target service; a token for one service cannot be reused against another.
3. **Short-lived**: small TTL reduces replay window and blast radius.
4. **Rotation-friendly**: `kid` + JWKS supports overlap and safe cutover.
5. **Auditable**: claims and `jti` pair naturally with `agent_call_logs` for traceable call chains.
6. **Zero shared static secret at runtime path**: avoids one leaked header unlocking all internal services.

In short: this design moves from static shared-secret trust to scoped, verifiable, and time-bounded trust.

---

## Prerequisites

| Tool           | Version | Purpose              |
| -------------- | ------- | -------------------- |
| Python         | 3.11+   | Runtime              |
| MySQL          | 8.0+    | Primary DB           |
| Twilio account | -       | OTP delivery         |
| Docker         | 24.0+   | Optional local infra |

---

## Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/maugus0/ouroboros-ai-orchestrator.git
cd ouroboros-ai-orchestrator

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### 2. Create `.env`

```bash
cp .env.example .env
```

### 3. Generate Signing Keys

Generate user JWT keys (auth tokens):

```bash
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

Generate internal service-token key (recommended separate key):

```bash
openssl genrsa -out internal_private.pem 2048
openssl rsa -in internal_private.pem -pubout -out internal_public.pem
```

Put keys into `.env` as single-line values using escaped newlines (`\\n`):

```env
JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"

INTERNAL_TOKEN_ENABLED=true
INTERNAL_TOKEN_SIGNING_ALGORITHM=RS256
INTERNAL_TOKEN_ACTIVE_KID=internal-v1
INTERNAL_TOKEN_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
INTERNAL_TOKEN_ISSUER=ouroboros-orchestrator-internal
INTERNAL_TOKEN_TTL_SECONDS=120
INTERNAL_TOKEN_AUDIENCE_MAP={"student-profile":"ouroboros.student-profile","program-discovery":"ouroboros.program-discovery","scholarship-discovery":"ouroboros.scholarship-discovery","eligibility-engine":"ouroboros.eligibility-engine","application-support":"ouroboros.application-support"}
```

After loading into `.env`, remove raw PEM files:

```bash
rm -f jwt_private.pem jwt_public.pem internal_private.pem internal_public.pem
```

### 4. Start Database and Run Migrations

```bash
docker compose up -d mysql
python scripts/run_migrations.py
```

### 5. Start Service

```bash
./start.sh
# or
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Verify

```bash
curl http://localhost:8000/health
```

Swagger UI: `http://localhost:8000/docs`

---

## Token Generation and API Testing

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

Key environment variables (see `.env.example` for full list):

### Database

- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USERNAME`, `DB_PASSWORD`
- `DB_POOL_SIZE`, `DB_CONNECTION_TIMEOUT`

### Auth JWT (user-facing)

- `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`
- `JWT_ACCESS_TOKEN_EXP_SECONDS`, `JWT_REFRESH_TOKEN_EXP_SECONDS`
- `JWT_ISSUER`, `JWT_AUDIENCE`

### Internal Service JWT (orchestrator -> downstream)

- `INTERNAL_TOKEN_ENABLED`
- `INTERNAL_TOKEN_ISSUER`
- `INTERNAL_TOKEN_TTL_SECONDS`
- `INTERNAL_TOKEN_SIGNING_ALGORITHM`
- `INTERNAL_TOKEN_ACTIVE_KID`
- `INTERNAL_TOKEN_PRIVATE_KEY`
- `INTERNAL_TOKEN_PUBLIC_KEYS`
- `INTERNAL_TOKEN_AUDIENCE_MAP`
- `INTERNAL_TOKEN_JWKS_CACHE_MAX_AGE_SECONDS`

### Downstream Service URLs

- `STUDENT_PROFILE_SERVICE_URL`
- `PROGRAM_DISCOVERY_SERVICE_URL`
- `SCHOLARSHIP_DISCOVERY_SERVICE_URL`
- `ELIGIBILITY_SERVICE_URL`
- `APPLICATION_SUPPORT_SERVICE_URL`

### OTP/Twilio and App Settings

- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `TWILIO_VERIFY_SERVICE_SID`
- `OTP_*`, `MFA_OTP_DAILY_LIMIT`
- `LOG_LEVEL`, `CORS_ORIGINS`, `ALLOW_DB_FAILURE`, `USE_MOCK_DATA`

> Note: `X_SERVICE_TOKEN` exists only for backward compatibility toggles and should not be used as the primary trust mechanism.

---

## Database Schema

### Core Tables

- `users`
- `auth_sessions`
- `otp_logs`
- `projects`
- `chats`
- `messages`

### Workflow and Audit Tables

- `workflow_runs`
- `workflow_context`
- `agent_call_logs`

### Migrations

```text
migrations/
├── 001_create_users.sql
├── 002_create_chats.sql
└── 003_create_workflow_and_agent_call_logs.sql
```

All migrations are idempotent (`CREATE TABLE IF NOT EXISTS`).

---

## API Endpoints

Base URL: `http://localhost:8000`

### Authentication (`/auth`)

- `POST /auth/signup`
- `POST /auth/verify-otp`
- `POST /auth/resend-otp`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`
- `PATCH /auth/profile`
- `GET /auth/profile-status`
- `GET /auth/sessions`
- `POST /auth/mfa/toggle`
- `POST /auth/mfa/verify`
- `POST /auth/forgot-password`
- `POST /auth/forgot-password/verify`
- `POST /auth/reset-password`

### Chats (`/api/v1/chats`)

- `POST /api/v1/chats`
- `GET /api/v1/chats`
- `GET /api/v1/chats/{id}`
- `PATCH /api/v1/chats/{id}`
- `DELETE /api/v1/chats/{id}`
- `POST /api/v1/chats/{id}/messages`
- `POST /api/v1/chats/{id}/assistant-notice`
- `GET /api/v1/chats/{id}/messages`

### Projects (`/api/v1/projects`)

- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{id}`
- `PATCH /api/v1/projects/{id}`
- `DELETE /api/v1/projects/{id}`

### Workflows (`/api/v1/workflows`)

- `GET /api/v1/workflows/users/me/profile-readiness`
- `GET /api/v1/workflows/chats/{chat_id}/status`
- `POST /api/v1/workflows/chats/{chat_id}/retry-last-agent-call`
- `POST /api/v1/workflows/profile-upload`

### Internal

- `GET /internal/.well-known/jwks.json`

### Health

- `GET /`
- `GET /health`

---

## Testing

Run all tests:

```bash
ALLOW_DB_FAILURE=true pytest tests/ -v
```

Run coverage:

```bash
ALLOW_DB_FAILURE=true pytest tests/ --cov=app --cov-report=html -v
open htmlcov/index.html
```

Seed local users for quick auth testing:

```bash
python scripts/seed_users.py
```

Seeded users share password `Admin123@`.

Current integration-test status for this repo:

- `tests/integration/` exists as scaffold only (`__init__.py`), no full suite yet.

---

## CI/CD Pipeline

Workflow file: `.github/workflows/deploy.yml`

Typical stages:

- Format (black, isort)
- Lint (flake8, pylint)
- Unit tests (pytest)
- Type check (mypy)
- Security audit (bandit)
- Docker build

---

## Deployment

### Docker Compose

```bash
docker compose up --build -d
docker compose logs -f
docker compose down
```

### Docker (service only)

```bash
docker build -t ouroboros-orchestrator .

docker run -p 8000:8000 \
  --env-file .env \
  -e DB_HOST=mysql-host \
  -e DB_PASSWORD=secret \
  ouroboros-orchestrator
```

---

## Project Structure

```text
ouroboros-ai-orchestrator/
├── app/
│   ├── api/
│   │   ├── auth.py
│   │   ├── chats.py
│   │   ├── projects.py
│   │   ├── workflows.py
│   │   ├── internal.py
│   │   └── health.py
│   ├── clients/                  # Downstream HTTP clients
│   ├── configs/                  # Intent registry and policy configs
│   ├── core/                     # DB pool and logging setup
│   ├── middleware/               # Auth/logging middleware
│   ├── models/                   # Pydantic schemas
│   ├── repositories/             # Raw SQL repositories
│   ├── security/                 # Internal token issuer/JWKS helpers
│   ├── services/                 # Orchestration and business services
│   ├── utils/
│   ├── config.py
│   └── main.py
├── migrations/
│   ├── 001_create_users.sql
│   ├── 002_create_chats.sql
│   └── 003_create_workflow_and_agent_call_logs.sql
├── scripts/
│   ├── run_migrations.py
│   └── seed_users.py
├── tests/
│   ├── unit/
│   └── integration/
└── README.md
```

---

## Troubleshooting

| Issue                          | Fix                                                                                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| MySQL connection fails         | Verify DB is running and `DB_*` or `MYSQL_*` env vars are correct.                                          |
| JWT validation errors          | Ensure `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY` are correctly escaped with `\\n`.                             |
| Internal downstream 401 errors | Verify `INTERNAL_TOKEN_ENABLED=true`, `aud` mapping, `iss`, `kid`, and downstream JWKS URL/audience config. |
| JWKS endpoint returns 503      | Configure `INTERNAL_TOKEN_PRIVATE_KEY` and/or `INTERNAL_TOKEN_PUBLIC_KEYS`.                                 |
| Twilio OTP not sent            | Re-check Twilio SID/token/number and account limits in Twilio console.                                      |
| Imports fail                   | Activate env with `source .venv/bin/activate` and reinstall dependencies.                                   |
