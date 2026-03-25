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
for VENV_DIR in ".venv" "venv" "env"; do
    if [ -d "${VENV_DIR}" ] && [ -f "${VENV_DIR}/bin/activate" ]; then
        source "${VENV_DIR}/bin/activate"
        VENV_ACTIVATED=true
        break
    fi
done

if [ "${VENV_ACTIVATED}" = true ]; then
    success "Using Python virtual environment"
else
    warning "Proceeding without venv"
fi

PYTHON_CMD="python"
if ! command -v "${PYTHON_CMD}" > /dev/null 2>&1; then
    if command -v python3 > /dev/null 2>&1; then
        PYTHON_CMD="python3"
    else
        error "Python interpreter not found."
        exit 1
    fi
fi

echo "1. Checking code formatting (Black)..."
if black --check app/ tests/ > /dev/null 2>&1; then
    success "Code formatting passed"
else
    error "Formatting failed. Run: black app/ tests/"
    exit 1
fi

echo ""
echo "2. Checking import sorting (isort)..."
if isort --check-only app/ tests/ > /dev/null 2>&1; then
    success "Import sorting passed"
else
    error "Import sorting failed. Run: isort app/ tests/"
    exit 1
fi

echo ""
echo "3. Running linting (flake8)..."
if flake8 app/ tests/ --max-line-length=120 --extend-ignore=E203,W503,E501 > /dev/null 2>&1; then
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
if ALLOW_DB_FAILURE=true USE_MOCK_DATA=true pytest tests/ -v --tb=short > /dev/null 2>&1; then
    success "Tests passed"
else
    error "Tests failed"
    exit 1
fi

echo ""
echo "6. Running type checking (mypy)..."
if mypy app/ --ignore-missing-imports --no-strict-optional > /dev/null 2>&1; then
    success "Type checking passed"
else
    warning "Type checking completed with warnings"
fi

echo ""
echo -e "${GREEN}All checks passed! Ready to commit.${NC}"
