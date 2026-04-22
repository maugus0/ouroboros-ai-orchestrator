#!/bin/bash
set -e

echo "Starting Ouroboros Orchestrator Service..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN=""

for VENV_DIR in "${SCRIPT_DIR}/.venv" "${SCRIPT_DIR}/venv" "${SCRIPT_DIR}/env"; do
    if [ -d "${VENV_DIR}" ] && [ -f "${VENV_DIR}/bin/activate" ] && [ -x "${VENV_DIR}/bin/python" ]; then
        source "${VENV_DIR}/bin/activate"
        PYTHON_BIN="${VENV_DIR}/bin/python"
        break
    fi
done

if [ -z "${PYTHON_BIN}" ]; then
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi

if [ -z "${PYTHON_BIN}" ]; then
    echo "Python interpreter not found. Activate a virtual environment or install Python 3."
    exit 1
fi

cd "${SCRIPT_DIR}"

if [ "${RUN_STARTUP_SCRIPTS:-true}" = "true" ]; then
    "${PYTHON_BIN}" scripts/run_migrations.py
fi

"${PYTHON_BIN}" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
