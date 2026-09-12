#!/usr/bin/env bash
# HeliosDB local dev runner — DEV ONLY, never for production traffic.
# Usage: ./server.sh [--port 8765]   (or PORT=8765 ./server.sh)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

exec python3 server.py --port "$PORT"
