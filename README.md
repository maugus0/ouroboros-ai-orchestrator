# Ouroboros Orchestrator Service

Central coordination service for the **Ouroboros AI** scholarship discovery platform. The Orchestrator is the single backend entry-point the frontend communicates with — it handles authentication, workflow coordination, agent delegation, result aggregation, and audit logging.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
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

1. **Authenticates users** via self-rolled JWT RS256 (Orchestrator owns the private key)
2. **Manages chat sessions** and message history
3. **Drives a sequential workflow** state machine: Profile → Programs → Scholarships → Eligibility → Application Support
4. **Delegates to 5 agent microservices** via HTTP (httpx + tenacity retry)
5. **Aggregates results** from all agents into self-contained JSON blobs
6. **Audit-logs every agent call** with request/response payloads, latency, and trace IDs

**Key Design Principles:**

- Single entry-point — the frontend communicates **only** with the orchestrator
- Agent isolation — microservices never call each other; the orchestrator fans out
- No ORM overhead — raw SQL with `aiomysql` async connection pool
- Retry resilience — exponential backoff on all inter-service HTTP calls
- Trace propagation — `X-Trace-ID` header flows through every agent call for correlated debugging

---

## Architecture

```
┌─────────────────────────────────────┐
│       Frontend (React + Vite)       │
│       (http://localhost:3000)       │
└──────────────┬──────────────────────┘
               │
               │ JWT Bearer Token
               ▼
┌──────────────────────────────────────────────────────┐
│          Orchestrator Service (8000)                  │
│                                                      │
│  ┌─────────────────────────────────────────────┐     │
│  │  API Layer (FastAPI)                        │     │
│  │  POST /auth/signup, /login, /refresh        │     │
│  │  GET  /auth/me                              │     │
│  │  CRUD /chats                                │     │
│  │  POST /workflows/{id}/start                 │     │
│  │  GET  /dashboard/{id}                       │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Service Layer                              │     │
│  │  AuthService        (signup, login, tokens) │     │
│  │  ChatService        (session management)    │     │
│  │  WorkflowService    (state machine)         │     │
│  │  AggregationService (combine results)       │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Client Layer (httpx + tenacity)            │     │
│  │  StudentProfileClient     → :8001           │     │
│  │  ProgramDiscoveryClient   → :8002           │     │
│  │  ScholarshipDiscovClient  → :8003           │     │
│  │  EligibilityClient        → :8004           │     │
│  │  ApplicationSupportClient → :8005           │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Repository Layer (Raw SQL / aiomysql)      │     │
│  │  UserRepository                             │     │
│  │  ChatRepository                             │     │
│  │  WorkflowRepository                         │     │
│  │  AgentCallLogRepository                     │     │
│  └─────────────────────────────────────────────┘     │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
      ┌─────────────────┐
      │   MySQL 8.0     │
      │   (aiomysql)    │
      └─────────────────┘
```

### Workflow State Machine

```
INITIATED → PROFILE_PARSING → PROFILE_COMPLETE
  → DISCOVERING_PROGRAMS → DISCOVERING_SCHOLARSHIPS
  → MATCHING → GENERATING_MATERIALS → COMPLETE
  (any state may transition to ERROR; retry resumes from last successful state)
```

### Authentication Strategy

| Concern | Approach |
|---------|----------|
| User → Orchestrator | JWT RS256 (self-rolled, Orchestrator owns private key) |
| Orchestrator → Agent | `X-Service-Token` shared secret header |
| Password storage | bcrypt via `passlib` |
| Token types | Access (1 hour) + Refresh (30 days) |

---

## Features

- **Self-rolled JWT RS256** authentication with access + refresh tokens
- **Sequential workflow** state machine with retry-from-last-success on failure
- **5 agent HTTP clients** with exponential backoff retry (tenacity)
- **Structured logging** via structlog with JSON output in production
- **Distributed tracing** via `X-Trace-ID` propagation across all agent calls
- **Audit logging** for every agent HTTP call (request, response, latency, status)
- **CORS configuration** for frontend development
- **Docker Compose** for local development with MySQL 8.0
- **Comprehensive CI/CD** pipeline with formatting, linting, tests, security, and Docker build

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Runtime |
| MySQL | 8.0+ | Database |
| OpenSSL | any | JWT RS256 key generation |
| Docker | 24.0+ | Containerised deployment (optional) |

---

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/maugus0/ouroboros-ai-orchestrator.git
cd ouroboros-ai-orchestrator

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 2. Generate JWT Keys

```bash
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
DB_HOST=localhost
DB_NAME=ouroboros_orchestrator_db
DB_USERNAME=root
DB_PASSWORD=your_mysql_password

JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
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

Expected output:

```
Running migration: 001_create_users.sql
  ✓ 001_create_users.sql applied
Running migration: 002_create_chats_messages.sql
  ✓ 002_create_chats_messages.sql applied
Running migration: 003_create_workflow_tables.sql
  ✓ 003_create_workflow_tables.sql applied

All migrations applied successfully.
```

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
| `DB_POOL_NAME` | No | `orchestrator_pool` | Connection pool name |
| `DB_CONNECTION_TIMEOUT` | No | `20` | Connection timeout (seconds) |
| **JWT Authentication** ||||
| `JWT_PRIVATE_KEY` | Yes | — | RSA private key (PEM, for issuing tokens) |
| `JWT_PUBLIC_KEY` | Yes | — | RSA public key (PEM, for validating tokens) |
| `JWT_ACCESS_TOKEN_EXP_SECONDS` | No | `3600` | Access token TTL (1 hour) |
| `JWT_REFRESH_TOKEN_EXP_SECONDS` | No | `2592000` | Refresh token TTL (30 days) |
| `JWT_ISSUER` | No | `ouroboros.ai/auth` | Token issuer claim |
| `JWT_AUDIENCE` | No | `ouroboros-api` | Token audience claim |
| **Agent Services** ||||
| `STUDENT_PROFILE_SERVICE_URL` | No | `http://localhost:8001` | Student Profile agent URL |
| `PROGRAM_DISCOVERY_SERVICE_URL` | No | `http://localhost:8002` | Program Discovery agent URL |
| `SCHOLARSHIP_DISCOVERY_SERVICE_URL` | No | `http://localhost:8003` | Scholarship Discovery agent URL |
| `ELIGIBILITY_SERVICE_URL` | No | `http://localhost:8004` | Eligibility Engine agent URL |
| `APPLICATION_SUPPORT_SERVICE_URL` | No | `http://localhost:8005` | Application Support agent URL |
| **Inter-Service Auth** ||||
| `X_SERVICE_TOKEN` | Yes | — | Shared secret for orchestrator → agent calls |
| **HTTP Client** ||||
| `AGENT_CALL_TIMEOUT` | No | `30` | Agent HTTP call timeout (seconds) |
| `AGENT_CALL_RETRIES` | No | `2` | Max retry attempts per agent call |
| `AGENT_CALL_BACKOFF_FACTOR` | No | `1.0` | Exponential backoff multiplier |
| **Application** ||||
| `LOG_LEVEL` | No | `INFO` | `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` |
| `USE_MOCK_DATA` | No | `true` | Use in-memory repos (tests only) |
| `ALLOW_DB_FAILURE` | No | `false` | Continue if DB unavailable (tests only) |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed origins |
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
| `users` | User records with bcrypt password hashes |
| `chats` | Chat sessions (one chat = one workflow run) |
| `messages` | Chat messages (user, assistant, system roles) |
| `workflow_runs` | Workflow state machine with current/last-successful state |
| `workflow_results` | Aggregated JSON blobs from all agent outputs |
| `agent_call_logs` | Audit trail — HTTP status, latency, request/response payloads |

### Relationships

```
users           (1) ──< (N) chats
users           (1) ──< (N) workflow_runs
chats           (1) ──< (N) messages
chats           (1) ──  (1) workflow_runs
workflow_runs   (1) ──< (N) workflow_results
workflow_runs   (1) ──< (N) agent_call_logs
```

### Migrations

Run in order via `python scripts/run_migrations.py`:

```
migrations/
├── 001_create_users.sql
├── 002_create_chats_messages.sql
└── 003_create_workflow_tables.sql
```

---

## API Endpoints

**Base URL**: `http://localhost:8000`

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Root health check |
| GET | `/health` | No | Detailed health status |

### Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/signup` | No | Register a new user |
| POST | `/auth/login` | No | Authenticate and receive JWT tokens |
| POST | `/auth/refresh` | No | Exchange refresh token for new access token |
| POST | `/auth/logout` | Bearer | Invalidate current session |
| GET | `/auth/me` | Bearer | Return authenticated user profile |

### Chats

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/chats/` | Bearer | Create a new chat session |
| GET | `/chats/` | Bearer | List all chats for the user |
| GET | `/chats/{chat_id}` | Bearer | Retrieve a single chat with messages |
| DELETE | `/chats/{chat_id}` | Bearer | Soft-delete a chat session |

### Workflows

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/workflows/{chat_id}/start` | Bearer | Kick off the agent workflow |
| GET | `/workflows/{chat_id}/status` | Bearer | Return current workflow state |
| POST | `/workflows/{chat_id}/retry` | Bearer | Retry from last successful state |

### Profiles (Proxy)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/profiles/parse` | Bearer | Upload CV via Student Profile agent |
| GET | `/profiles/me` | Bearer | Get current user's parsed profile |

### Dashboard

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/dashboard/{chat_id}` | Bearer | Aggregated results from all agents |

---

## Development Workflow

### Code Quality Checks

```bash
# Format code
black app/ tests/
isort app/ tests/

# Lint
flake8 app/ tests/ --max-line-length=120 --extend-ignore=E203,W503,E501

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

Runs Black, isort, flake8, syntax validation, tests, and mypy in sequence.

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
│   ├── test_config.py           # Configuration loading
│   ├── test_health.py           # Health check endpoints
│   ├── test_security.py         # JWT creation and validation
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
| **Lint** | flake8 + pylint code quality checks |
| **Unit Tests** | pytest with JUnit XML output |
| **Type Check** | mypy static type analysis (after format + lint) |
| **Integration Tests** | pytest with coverage HTML + XML (after format + lint) |
| **Security Audit** | Bandit static security analysis (after format + lint) |
| **Docker Build** | Verify image builds — no push (after all above) |
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

### Local CI Simulation

```bash
black --check app/ tests/
isort --check-only app/ tests/
flake8 app/ tests/ --max-line-length=120 --extend-ignore=E203,W503,E501
mypy app/ --ignore-missing-imports --no-strict-optional || true
ALLOW_DB_FAILURE=true pytest tests/ -v
bandit -r app/ || true
docker build -t ouroboros-orchestrator .
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
  -e JWT_PRIVATE_KEY="..." \
  -e JWT_PUBLIC_KEY="..." \
  ouroboros-orchestrator
```

---

## Project Structure

```
ouroboros-ai-orchestrator/
├── app/
│   ├── api/                     # Route handlers (thin layer)
│   │   ├── health.py            # GET / and /health
│   │   ├── auth.py              # POST /auth/signup, /login, /refresh, /logout, GET /me
│   │   ├── chats.py             # Chat session CRUD
│   │   ├── workflows.py         # Workflow orchestration
│   │   ├── profiles.py          # Proxy → Student Profile agent
│   │   └── dashboard.py         # Aggregated results view
│   ├── core/                    # Infrastructure
│   │   ├── database.py          # aiomysql async connection pool (no ORM)
│   │   ├── logging.py           # structlog configuration
│   │   └── security.py          # JWT RS256 create / decode
│   ├── models/                  # Pydantic request / response schemas
│   │   ├── common.py            # StandardResponse, PaginatedResponse
│   │   ├── auth.py              # SignupRequest, LoginRequest, TokenResponse
│   │   ├── chat.py              # ChatCreate, MessageCreate, ChatResponse
│   │   ├── workflow.py          # WorkflowState, WorkflowRunResponse
│   │   └── agent_payloads.py    # Request/response schemas for each agent
│   ├── db/repositories/         # Raw SQL data access (aiomysql)
│   │   ├── user_repo.py
│   │   ├── chat_repo.py
│   │   ├── workflow_repo.py
│   │   └── agent_log_repo.py
│   ├── services/                # Business logic
│   │   ├── auth_service.py      # Signup, login, token management
│   │   ├── chat_service.py      # Chat session orchestration
│   │   ├── workflow_service.py  # State machine logic
│   │   └── aggregation_service.py
│   ├── clients/                 # HTTP clients to agent services
│   │   ├── base_client.py       # Shared httpx client with retry
│   │   ├── student_profile_client.py
│   │   ├── program_discovery_client.py
│   │   ├── scholarship_discovery_client.py
│   │   ├── eligibility_client.py
│   │   └── application_support_client.py
│   ├── middleware/              # Middleware
│   │   ├── auth_middleware.py   # JWT validation dependency
│   │   └── logging_middleware.py
│   ├── utils/                   # Utilities
│   │   ├── exceptions.py        # Custom exception hierarchy
│   │   └── trace_id.py          # UUID-v4 trace ID generation
│   ├── config.py                # Pydantic settings
│   └── main.py                  # FastAPI app with lifespan
├── migrations/                  # SQL migration files (001-003)
├── scripts/
│   ├── run_migrations.py        # Execute migrations in order
│   ├── seed_test_data.py        # Seed test users
│   └── generate_service_token.py
├── tests/
│   ├── unit/                    # Unit tests
│   └── integration/             # Integration tests
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

### JWT Key Errors

**Symptom**: `jwt.exceptions.DecodeError` or empty token responses

```bash
# Verify keys exist
ls -la jwt_private.pem jwt_public.pem

# Regenerate if needed
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem

# Verify keys match
openssl rsa -in jwt_private.pem -pubout | diff - jwt_public.pem
```

### Import Errors

**Symptom**: `ModuleNotFoundError: No module named 'app'`

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Agent Service Unreachable

**Symptom**: `AgentCallError: [student_profile] HTTP 502`

```bash
# Check agent service is running
curl http://localhost:8001/health

# Verify URLs in .env
grep SERVICE_URL .env
```

---

## Attribution

**Developed by**: OuroborosAI Developer Team

**Project**: Ouroboros AI Scholarship Discovery Platform

**Repository**: [github.com/maugus0/ouroboros-ai-orchestrator](https://github.com/maugus0/ouroboros-ai-orchestrator)
