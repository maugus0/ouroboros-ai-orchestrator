#!/bin/bash
# Pre-commit check script for Orchestrator Service
set -e

echo "Running pre-commit checks..."
echo ""

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

success() { echo -e "${GREEN}  $1${NC}"; }
error()   { echo -e "${RED}  $1${NC}"; }
warning() { echo -e "${YELLOW}  $1${NC}"; }

VENV_ACTIVATED=false
PYTHON_CMD=""
for VENV_DIR in ".venv" "venv" "env"; do
    if [ -d "${VENV_DIR}" ] && [ -f "${VENV_DIR}/bin/activate" ]; then
        source "${VENV_DIR}/bin/activate"
        PYTHON_CMD="${VENV_DIR}/bin/python"
        VENV_ACTIVATED=true
        break
    fi
done

if [ "${VENV_ACTIVATED}" = true ]; then
    success "Using Python virtual environment"
else
    warning "Proceeding without venv"
fi

if [ -z "${PYTHON_CMD}" ]; then
    PYTHON_CMD="python"
    if ! command -v "${PYTHON_CMD}" > /dev/null 2>&1; then
        if command -v python3 > /dev/null 2>&1; then
            PYTHON_CMD="python3"
        else
            error "Python interpreter not found."
            exit 1
        fi
    fi
fi

if [ ! -x "${PYTHON_CMD}" ]; then
    if ! command -v "${PYTHON_CMD}" > /dev/null 2>&1; then
        error "Python interpreter not found."
        exit 1
    fi
fi

echo "1. Checking code formatting (Black)..."
if "${PYTHON_CMD}" -m black --check app/ tests/ > /dev/null 2>&1; then
    success "Code formatting passed"
else
    error "Formatting failed. Run: black app/ tests/"
    exit 1
fi

echo ""
echo "2. Checking import sorting (isort)..."
if "${PYTHON_CMD}" -m isort --check-only app/ tests/ > /dev/null 2>&1; then
    success "Import sorting passed"
else
    error "Import sorting failed. Run: isort app/ tests/"
    exit 1
fi

echo ""
echo "3. Running linting (flake8)..."
if "${PYTHON_CMD}" -m flake8 app/ tests/ --max-line-length=120 --extend-ignore=E203,W503,E501 > /dev/null 2>&1; then
    success "Linting passed"
else
    error "Linting failed"
    exit 1
fi

echo ""
echo "4. Validating Python syntax..."
if "${PYTHON_CMD}" -m py_compile app/main.py app/config.py > /dev/null 2>&1; then
    success "Syntax validation passed"
else
    error "Syntax validation failed"
    exit 1
fi

echo ""
echo "5. Running tests..."
if ALLOW_DB_FAILURE=true USE_MOCK_DATA=true "${PYTHON_CMD}" -m pytest tests/ -v --tb=short > /dev/null 2>&1; then
    success "Tests passed"
else
    error "Tests failed"
    exit 1
fi

echo ""
echo "6. Running pylint..."
if "${PYTHON_CMD}" -m pylint app/ tests/ --max-line-length=120 --disable=C0111,R0903,R0801 > /dev/null 2>&1; then
    success "Pylint passed"
else
    error "Pylint failed. Run: pylint app/ tests/ --max-line-length=120 --disable=C0111,R0903,R0801"
    exit 1
fi

echo ""
echo "7. Running security scan (Bandit)..."
if ! "${PYTHON_CMD}" -m bandit --version > /dev/null 2>&1; then
    error "bandit not found. Install dev deps: pip install -r requirements-dev.txt"
    exit 1
fi
# Same scope as CI: .github/workflows/deploy.yml \"Run Bandit (JSON; fails on findings)\"
set +e
BANDIT_OUTPUT=$("${PYTHON_CMD}" -m bandit -r app/ -f txt 2>&1)
BANDIT_EC=$?
set -e
if [ "${BANDIT_EC}" -eq 0 ]; then
    success "Bandit passed (no issues)"
else
    error "Bandit failed — this is the same check as CI \"Security Scan (Bandit)\""
    echo "${BANDIT_OUTPUT}"
    echo ""
    error "Fix issues above, or run: bandit -r app/ -f txt"
    exit 1
fi

echo ""
echo "8. Running type checking (mypy)..."
if "${PYTHON_CMD}" -m mypy app/ --ignore-missing-imports --no-strict-optional > /dev/null 2>&1; then
    success "Type checking passed"
else
    error "Type checking failed. Run: mypy app/ --ignore-missing-imports --no-strict-optional"
    exit 1
fi

echo ""
echo -e "${GREEN}All checks passed! Ready to commit.${NC}"
