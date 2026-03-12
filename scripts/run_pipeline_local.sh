#!/usr/bin/env bash
# ============================================================================
# BetVector — Local Pipeline Runner (PC-15-04)
# ============================================================================
# Wrapper script for launchd-scheduled pipeline runs.
#
# launchd does NOT inherit shell environment variables (no .bashrc, no .zshrc),
# so this script explicitly sources .env, activates the Python venv, and
# routes stdout/stderr to timestamped log files.
#
# Usage:
#   ./scripts/run_pipeline_local.sh morning
#   ./scripts/run_pipeline_local.sh midday
#   ./scripts/run_pipeline_local.sh evening
#
# Log rotation: keeps the last 30 days of logs, auto-deletes older ones.
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths — all relative to project root
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"
LOG_DIR="$PROJECT_DIR/data/logs"
LOG_RETENTION_DAYS=30

# ---------------------------------------------------------------------------
# Validate arguments
# ---------------------------------------------------------------------------
MODE="${1:-}"
if [[ -z "$MODE" ]]; then
    echo "Usage: $0 <morning|midday|evening>"
    exit 1
fi

if [[ "$MODE" != "morning" && "$MODE" != "midday" && "$MODE" != "evening" ]]; then
    echo "Error: Invalid mode '$MODE'. Must be one of: morning, midday, evening"
    exit 1
fi

# ---------------------------------------------------------------------------
# Ensure log directory exists
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------------
# Timestamped log file: e.g. data/logs/morning_2026-03-12.log
# ---------------------------------------------------------------------------
DATE_STAMP="$(date +%Y-%m-%d)"
TIME_STAMP="$(date +%H:%M:%S)"
LOG_FILE="$LOG_DIR/${MODE}_${DATE_STAMP}.log"

# ---------------------------------------------------------------------------
# Source .env (launchd doesn't inherit shell env vars)
# ---------------------------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
    # Export all variables from .env, skipping comments and empty lines
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
else
    echo "[$TIME_STAMP] WARNING: .env file not found at $ENV_FILE" | tee -a "$LOG_FILE"
fi

# ---------------------------------------------------------------------------
# Activate Python virtual environment
# ---------------------------------------------------------------------------
if [[ -f "$VENV_DIR/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
else
    echo "[$TIME_STAMP] ERROR: venv not found at $VENV_DIR/bin/activate" | tee -a "$LOG_FILE"
    exit 1
fi

# ---------------------------------------------------------------------------
# Run the pipeline
# ---------------------------------------------------------------------------
echo "========================================" >> "$LOG_FILE"
echo "[$TIME_STAMP] BetVector $MODE pipeline starting" >> "$LOG_FILE"
echo "Working directory: $PROJECT_DIR" >> "$LOG_FILE"
echo "Python: $(which python)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

cd "$PROJECT_DIR"

# Run pipeline, capturing both stdout and stderr to the log file.
# Temporarily disable set -e so a pipeline failure doesn't skip the
# end-of-run log entry and log rotation below.
set +e
python run_pipeline.py "$MODE" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
set -e

END_TIME="$(date +%H:%M:%S)"
echo "========================================" >> "$LOG_FILE"
echo "[$END_TIME] Pipeline $MODE finished with exit code $EXIT_CODE" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# ---------------------------------------------------------------------------
# Log rotation — delete logs older than LOG_RETENTION_DAYS
# ---------------------------------------------------------------------------
find "$LOG_DIR" -name "*.log" -type f -mtime +$LOG_RETENTION_DAYS -delete 2>/dev/null || true

exit $EXIT_CODE
