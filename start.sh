#!/bin/bash
set -e

echo "Starting Ouroboros Orchestrator Service..."

for VENV_DIR in ".venv" "venv" "env"; do
    if [ -d "${VENV_DIR}" ] && [ -f "${VENV_DIR}/bin/activate" ]; then
        source "${VENV_DIR}/bin/activate"
        break
    fi
done

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
