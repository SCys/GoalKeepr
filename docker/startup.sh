#!/bin/bash
set -euo pipefail

# Support separated layout via env (matches systemd / GOALKEEPR_* usage).
# Defaults keep Docker behavior unchanged.
DATA_DIR=${GOALKEEPR_DATA_DIR:-data}
LOG_DIR=${GOALKEEPR_LOG_DIR:-log}

mkdir -p "$DATA_DIR" "$LOG_DIR"

# Trap SIGTERM/SIGINT for graceful shutdown
trap 'echo "Shutting down..."; exit 0' SIGTERM SIGINT

echo "Starting goal-keepr... (config=${GOALKEEPR_CONFIG:-main.ini}, data=${DATA_DIR})"
exec python main.py >> "$LOG_DIR/main.log" 2>&1
