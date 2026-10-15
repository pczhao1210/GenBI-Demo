#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

PYTHON="$PWD/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "Create the environment first: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
    exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
    trap - EXIT INT TERM
    if [[ -n "$FRONTEND_PID" ]]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
    if [[ -n "$BACKEND_PID" ]]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
    wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_ready() {
    local pid="$1" url="$2"
    for ((attempt=0; attempt<60; attempt++)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "Service exited before becoming ready: $url"
            return 1
        fi
        if curl --silent --fail --connect-timeout 1 --max-time 2 "$url" >/dev/null; then
            kill -0 "$pid" 2>/dev/null && return 0
        fi
        sleep 1
    done
    echo "Service readiness timed out: $url"
    return 1
}

BACKEND_PORT="${GENBI_BACKEND_PORT:-8000}"
FRONTEND_PORT="${GENBI_FRONTEND_PORT:-8501}"
"$PYTHON" -m uvicorn backend.main:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
wait_ready "$BACKEND_PID" "http://127.0.0.1:$BACKEND_PORT/health"
"$PYTHON" -m streamlit run app.py --server.address 127.0.0.1 --server.port "$FRONTEND_PORT" -- "$@" &
FRONTEND_PID=$!
wait_ready "$FRONTEND_PID" "http://127.0.0.1:$FRONTEND_PORT/_stcore/health"
echo "Frontend: http://localhost:$FRONTEND_PORT"
echo "API docs: http://localhost:$BACKEND_PORT/docs"
echo "Press Ctrl+C to stop both services."
wait -n "$BACKEND_PID" "$FRONTEND_PID"
