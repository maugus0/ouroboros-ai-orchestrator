# Ouroboros Orchestrator Service

Central coordination service for the **Ouroboros AI** scholarship discovery platform. The Orchestrator is the single backend entry-point the frontend communicates with — starting with authentication and health monitoring, with business logic (workflows, agents, chats) to be added incrementally.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Database Schema](#database-schema)
- [API Endpoints](#api-endpoints)
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

1. **Authenticates users** via Auth0 (JWT validation with JWKS)
2. **Provisions users on first login** (JIT — Just-In-Time)
3. **Exposes a health endpoint** for monitoring and readiness checks

**Key Design Principles:**

- Single entry-point — the frontend communicates **only** with the orchestrator
- No ORM overhead — raw SQL with `aiomysql` async connection pool
- Trace propagation — `X-Trace-ID` header flows through every request for correlated debugging

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
│  │  GET  /auth/me   PATCH /auth/me             │     │
│  │  POST /auth/logout                          │     │
│  │  GET  / and /health                         │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Auth0 JWT Validation (JWKS)                │     │
│  │  JIT User Provisioning                      │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Repository Layer (Raw SQL / aiomysql)      │     │
│  │  UserRepository                             │     │
│  └─────────────────────────────────────────────┘     │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
      ┌─────────────────┐
      │   MySQL 8.0     │
      │   (aiomysql)    │
      └─────────────────┘
```

### Authentication Strategy

| Concern | Approach |
|---------|----------|
| User → Orchestrator | **Auth0** JWT RS256 (validated via JWKS) |
| Password storage | **Auth0** (passwords never stored locally) |
| Token types | Auth0 Access Token + Refresh Token |
| User provisioning | **JIT** (Just-In-Time) — users created on first login |

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Runtime |
| MySQL | 8.0+ | Database |
| Auth0 account | — | Authentication provider |
| Docker | 24.0+ | Containerised deployment (optional) |

---

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/maugus0/ouroboros-ai-orchestrator.git
cd ouroboros-ai-orchestrator

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Use python -m pip to ensure packages install into the venv
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### 2. Set Up Auth0

1. **Create an Auth0 tenant** at [auth0.com](https://auth0.com)

2. **Create an API** in Auth0 Dashboard:
   - Go to **Applications → APIs → Create API**
   - Name: `Ouroboros API`
   - Identifier (Audience): `https://api.ouroboros.ai` (or your custom identifier)
   - Signing Algorithm: `RS256`

3. **Create an Application** (for your frontend):
   - Go to **Applications → Applications → Create Application**
   - Type: **Single Page Application** (for React frontend)
   - Configure **Allowed Callback URLs**: `http://localhost:8080/callback` (use your React dev URL and path)
   - Configure **Allowed Logout URLs**: `http://localhost:8080`
   - Configure **Allowed Web Origins**: `http://localhost:8080`

4. **Note your credentials**:
   - Auth0 Domain (e.g., `your-tenant.us.auth0.com`)
   - API Audience (e.g., `https://api.ouroboros.ai`)

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Database
DB_HOST=localhost
DB_NAME=ouroboros_orchestrator_db
DB_USERNAME=root
DB_PASSWORD=your_mysql_password

# Auth0 (required)
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_API_AUDIENCE=https://api.ouroboros.ai
```

See [Configuration](#configuration) for the full reference.

### 4. Database Setup

**Option A: Docker (Recommended)**

```bash
docker compose up mysql -d
docker compose logs -f mysql   # wait for "ready for connections"
```

**Option B: Local MySQL**

```bash
mysql -u root -p -e "CREATE DATABASE ouroboros_orchestrator_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 5. Run Migrations

```bash
python scripts/run_migrations.py
```

The migration runner tracks applied migrations in a `schema_migrations` table, so it is safe to run multiple times.

### 6. (Optional) Seed Test Data

```bash
python scripts/seed_test_data.py
```

### 7. Start the Service

```bash
chmod +x start.sh
./start.sh
# or: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 8. Verify Health

```bash
curl http://localhost:8000/health
# {"status":"healthy","version":"0.1.0","database":"not_connected"}
```

Swagger docs are available at `http://localhost:8000/docs`.

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
| `DB_CONNECTION_TIMEOUT` | No | `20` | Connection timeout (seconds) |
| **Auth0 Configuration** ||||
| `AUTH0_DOMAIN` | Yes | — | Auth0 tenant domain (e.g., `your-tenant.us.auth0.com`) |
| `AUTH0_API_AUDIENCE` | Yes | — | Auth0 API identifier (e.g., `https://api.ouroboros.ai`) |
| `AUTH0_ALGORITHMS` | No | `RS256` | JWT signing algorithms (comma-separated) |
| **Application** ||||
| `LOG_LEVEL` | No | `INFO` | `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` |
| `ALLOW_DB_FAILURE` | No | `false` | Continue if DB unavailable (tests only) |
| `CORS_ORIGINS` | No | `http://localhost:8080,...` | Comma-separated allowed origins |
| **Docker** ||||
| `DOCKER_MYSQL_PORT` | No | `3307` | Host port for MySQL container |

### Docker / CI Prefix Compatibility

The service also reads `MYSQL_*` variables for Docker/CI environments:

| `DB_*` Prefix | Equivalent `MYSQL_*` |
|---------------|---------------------|
| `DB_HOST` | `MYSQL_HOST` |
| `DB_NAME` | `MYSQL_DATABASE` |
| `DB_USERNAME` | `MYSQL_USER` |
| `DB_PASSWORD` | `MYSQL_PASSWORD` |
| `DB_PORT` | `MYSQL_PORT` |

Resolution logic lives in the `settings.get_db_*()` helpers in `app/config.py`.

---

## Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `users` | User records with Auth0 identity mapping (`auth0_sub`) |
| `schema_migrations` | Tracks which SQL migrations have been applied |

### Migrations

Run via `python scripts/run_migrations.py` (idempotent — skips already-applied files):

```
migrations/
├── 001_create_users.sql
├── 002_create_chats_messages.sql
├── 003_create_workflow_tables.sql
└── 004_add_auth0_fields.sql
```

---

## API Endpoints

**Base URL**: `http://localhost:8000`

### Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/auth/me` | Bearer | Return authenticated user profile |
| PATCH | `/auth/me` | Bearer | Update authenticated user's name/email |
| POST | `/auth/logout` | Bearer | Logout (instructs client to clear tokens) |
| POST | `/auth/signup` | No | **Deprecated** — redirects to Auth0 |
| POST | `/auth/login` | No | **Deprecated** — redirects to Auth0 |
| POST | `/auth/refresh` | No | **Deprecated** — redirects to Auth0 |

> **Note**: Auth0 handles user registration, login, and token refresh. The deprecated endpoints return instructions directing clients to Auth0 Universal Login.

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Root health check |
| GET | `/health` | No | Detailed health status |

---

## Development Workflow

### Code Quality Checks

```bash
# Format code
black app/ tests/
isort app/ tests/

# Lint
flake8 app/ tests/ --max-line-length=120 --extend-ignore=E203,W503,E501
pylint app/ tests/ --max-line-length=120 --disable=C0111,R0903

# Type check
mypy app/ --ignore-missing-imports --no-strict-optional

# Run tests
ALLOW_DB_FAILURE=true pytest tests/ -v
```

### Pre-Commit Script

```bash
chmod +x pre-commit-check.sh
./pre-commit-check.sh
```

Runs Black, isort, flake8, syntax validation, tests, pylint, Bandit (same rules as CI security scan), and mypy in sequence (all must pass).

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

### Test Structure

```
tests/
├── conftest.py                  # Shared fixtures
├── unit/
│   ├── test_auth0.py            # Auth0 JWT validation tests
│   ├── test_config.py           # Configuration loading
│   ├── test_health.py           # Health check endpoints
│   ├── test_exceptions.py       # Custom exception classes
│   └── test_trace_id.py         # Trace ID generation
└── integration/
    └── (future integration tests)
```

---

## CI/CD Pipeline

**Workflow**: `.github/workflows/deploy.yml`

**Trigger**: Pull requests to `main` or `develop`

### Pipeline Stages

| Stage | Description |
|-------|-------------|
| **Format** | Black + isort validation |
| **Lint** | **flake8** + **pylint** (both blocking) |
| **Unit Tests** | pytest with JUnit XML output |
| **Type Check** | **mypy** static analysis |
| **Integration Tests** | pytest with coverage HTML + XML |
| **Security Audit** | Bandit static security analysis |
| **Docker Build** | Verify image builds — no push |
| **Summary** | Markdown table of all job results |

### Pipeline Graph

```
format ──┐
         ├──> type-check ──┐
lint   ──┤                  │
         ├──> integration ──┼──> build-docker ──> summary
         │                  │
         └──> security   ──┘
              
unit-tests (independent) ──────> build-docker
```

---

## Deployment

### Docker Compose (Full Stack)

```bash
docker compose up --build -d      # start MySQL + service
docker compose logs -f             # follow logs
docker compose down                # stop
docker compose down -v             # stop and remove volumes
```

### Docker (Service Only)

```bash
docker build -t ouroboros-orchestrator .

docker run -p 8000:8000 \
  -e DB_HOST=mysql-host \
  -e DB_PASSWORD=secret \
  -e AUTH0_DOMAIN=your-tenant.us.auth0.com \
  -e AUTH0_API_AUDIENCE=https://api.ouroboros.ai \
  ouroboros-orchestrator
```

---

## Project Structure

```
ouroboros-ai-orchestrator/
├── app/
│   ├── api/                     # Route handlers
│   │   ├── auth.py              # Auth0 endpoints (me, logout, deprecated signup/login)
│   │   └── health.py            # GET / and /health
│   ├── core/                    # Infrastructure
│   │   ├── auth0.py             # Auth0 JWT validation via JWKS
│   │   ├── database.py          # aiomysql async connection pool
│   │   └── logging.py           # structlog configuration
│   ├── models/                  # Pydantic request / response schemas
│   │   ├── common.py            # StandardResponse, PaginatedResponse
│   │   └── auth.py              # UserResponse, UserUpdateRequest
│   ├── repositories/            # Raw SQL data access (aiomysql)
│   │   └── user_repo.py         # User CRUD with Auth0 support
│   ├── middleware/
│   │   ├── auth_middleware.py   # Auth0 JWT validation + JIT provisioning
│   │   └── logging_middleware.py
│   ├── utils/
│   │   ├── exceptions.py        # Custom exception hierarchy
│   │   └── trace_id.py          # UUID-v4 trace ID generation
│   ├── config.py                # Pydantic settings (incl. Auth0)
│   └── main.py                  # FastAPI app with lifespan
├── migrations/                  # SQL migration files (001-004)
├── scripts/
│   ├── db_utils.py              # Shared DB connection helpers
│   ├── run_migrations.py        # Execute migrations in order (with tracking)
│   ├── seed_test_data.py        # Seed test users (Auth0 format)
│   └── generate_service_token.py
├── tests/
│   ├── unit/
│   │   ├── test_auth0.py        # Auth0 validation tests
│   │   ├── test_config.py
│   │   ├── test_health.py
│   │   ├── test_exceptions.py
│   │   └── test_trace_id.py
│   └── integration/             # Future integration tests
├── .github/workflows/
│   └── deploy.yml               # CI/CD pipeline
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

---

## Troubleshooting

### Database Connection Failed

**Symptom**: `RuntimeError: Database pool has not been initialised`

```bash
# Check MySQL is running
docker compose ps

# Test connection
mysql -h localhost -P 3307 -u root -p -e "SHOW DATABASES;"

# Verify credentials
grep DB_ .env
```

### Auth0: `Service not found` / `access_denied` for your audience

**Symptom**: Swagger or the SPA shows something like `[access_denied]: Service not found: https://api.ouroboros.ai`.

**Cause**: The `audience` sent to Auth0 (your `AUTH0_API_AUDIENCE` in `.env`) must **exactly match** the **Identifier** of an **API** registered in **your** Auth0 tenant. Auth0 is not checking whether your FastAPI server is deployed; it only checks whether that API resource exists in the dashboard.

**Fix (pick one)**:

1. **Register the API in Auth0** (recommended if you want to keep `https://api.ouroboros.ai`):
   - Dashboard → **Applications** → **APIs** → **Create API**
   - **Name**: e.g. `Ouroboros API`
   - **Identifier**: must be **exactly** `https://api.ouroboros.ai` (same string as `AUTH0_API_AUDIENCE`)
   - Signing algorithm: **RS256**
   - Save

2. **Or align `.env` with an API you already created**:
   - Open **APIs** in Auth0 and copy the **Identifier** of your API (e.g. `https://dev-orchestrator-api/`).
   - Set `AUTH0_API_AUDIENCE` in `.env` to that **exact** value (and restart the orchestrator).

**Also check**: Under your SPA application, **Allowed Callback URLs** must include `http://localhost:8000/docs/oauth2-redirect` if you use Swagger’s OAuth flow.

### Import Errors

**Symptom**: `ModuleNotFoundError: No module named 'app'`

```bash
source venv/bin/activate
python -m pip install -r requirements.txt
```

---

## Attribution

**Developed by**: OuroborosAI Developer Team

**Project**: Ouroboros AI Scholarship Discovery Platform

**Repository**: [github.com/maugus0/ouroboros-ai-orchestrator](https://github.com/maugus0/ouroboros-ai-orchestrator)
