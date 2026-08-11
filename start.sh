#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8501}"

uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

streamlit run cli.py --server.port "$PORT" --server.address 0.0.0.0
