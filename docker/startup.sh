#!/bin/bash
set -euo pipefail

# Runtime directories (also created in Dockerfile, but safe to re-create)
mkdir -p log data

# Trap SIGTERM/SIGINT for graceful shutdown
trap 'echo "Shutting down..."; exit 0' SIGTERM SIGINT

echo "Starting goal-keepr..."
exec python main.py >> log/main.log 2>&1
