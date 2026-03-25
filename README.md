# Ouroboros Orchestrator Service

Central coordination service for the **Ouroboros AI** scholarship discovery platform. The Orchestrator is the single backend entry-point the frontend communicates with — it handles authentication, workflow coordination, and agent delegation.

## Architecture

```
┌─────────────┐
│   Frontend   │  (React + Vite + TS)
└──────┬──────┘
       │ JWT Bearer Token
       ▼
┌─────────────────────────────────────────────────────┐
│             ORCHESTRATOR SERVICE                    │
│  ● Self-rolled JWT RS256 authentication             │
│  ● Chat / session management                        │
│  ● Sequential workflow state machine                │
│  ● Agent HTTP calls (httpx + tenacity retry)        │
│  ● Result aggregation & audit logging               │
└──┬────┬────┬────┬────┬──────────────────────────────┘
   │    │    │    │    │  X-Service-Token header
   ▼    ▼    ▼    ▼    ▼
┌──────┬──────┬──────┬──────┬──────┐
│Student│ Prog │Schol │Elig  │ App  │  Agent microservices
│Profile│ Disc │ Disc │Engine│ Supp │  (never call each other)
└──────┴──────┴──────┴──────┴──────┘
```

### Workflow State Machine

```
INITIATED → PROFILE_PARSING → PROFILE_COMPLETE
  → DISCOVERING_PROGRAMS → DISCOVERING_SCHOLARSHIPS
  → MATCHING → GENERATING_MATERIALS → COMPLETE
  (any state may transition to ERROR; retry resumes from last success)
```

## Prerequisites

| Tool       | Version |
|------------|---------|
| Python     | 3.12+   |
| MySQL      | 8.0+    |
| OpenSSL    | any     |
| Docker     | 24+     |

## Quick Start

### 1. Clone & create virtual environment

```bash
git clone <repo-url>
cd ouroboros-ai-orchestrator
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 2. Generate JWT keys

```bash
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in DB credentials and paste JWT key contents
```

### 4. Run database migrations

```bash
python scripts/run_migrations.py
```

### 5. (Optional) Seed test data

```bash
python scripts/seed_test_data.py
```

### 6. Start the service

```bash
chmod +x start.sh
./start.sh
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Docker

```bash
docker-compose up --build
```

This starts MySQL 8.0 and the Orchestrator service together.

## Project Structure

```
ouroboros-ai-orchestrator/
├── app/
│   ├── api/                  # Route handlers (thin layer)
│   │   ├── health.py         # GET / and /health
│   │   ├── auth.py           # Signup / login / refresh / logout / me
│   │   ├── chats.py          # Chat session CRUD
│   │   ├── workflows.py      # Workflow orchestration
│   │   ├── profiles.py       # Proxy → Student Profile agent
│   │   └── dashboard.py      # Aggregated results view
│   ├── core/                 # Infrastructure
│   │   ├── config.py         # → see app/config.py (project root for settings)
│   │   ├── database.py       # aiomysql async connection pool (no ORM)
│   │   ├── logging.py        # structlog configuration
│   │   └── security.py       # JWT RS256 create / decode
│   ├── models/               # Pydantic request / response schemas
│   ├── db/repositories/      # Raw-SQL data-access layer
│   ├── services/             # Business logic
│   ├── clients/              # httpx clients to each agent service
│   ├── middleware/            # Auth & logging middleware
│   └── utils/                # Exceptions, trace ID, helpers
├── migrations/               # Numbered SQL migration files
├── tests/
│   ├── unit/
│   └── integration/
├── scripts/                  # CLI utilities (migrations, seeding, tokens)
├── .github/workflows/ci.yml  # GitHub Actions CI/CD
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml
```

## Development Workflow

### Run tests

```bash
pytest tests/ -v
```

### Run tests with coverage

```bash
pytest tests/ --cov=app --cov-report=html -v
```

### Pre-commit checks

```bash
chmod +x pre-commit-check.sh
./pre-commit-check.sh
```

Runs: Black → isort → flake8 → syntax check → pytest → mypy

### Format code

```bash
black app/ tests/
isort app/ tests/
```

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every PR to `main` or `develop`:

| Stage              | What it does                              |
|--------------------|-------------------------------------------|
| **Format**         | Black + isort checks                      |
| **Lint**           | flake8 + pylint                           |
| **Unit Tests**     | pytest on `tests/unit/`                   |
| **Type Check**     | mypy (warnings only)                      |
| **Integration**    | pytest with coverage report               |
| **Security Audit** | Bandit static analysis                    |
| **Docker Build**   | Verify the image builds successfully      |
| **Summary**        | Markdown table of all job results         |

## Authentication Strategy

| Concern              | Approach                                       |
|----------------------|------------------------------------------------|
| User → Orchestrator  | JWT RS256 (self-rolled, Orchestrator owns keys) |
| Orchestrator → Agent | `X-Service-Token` shared secret header          |
| Password storage     | bcrypt via `passlib`                            |
| Token types          | Access (1h) + Refresh (30d)                     |

## Environment Variables

See `.env.example` for the full list with descriptions.

## License

Proprietary — Team 17
