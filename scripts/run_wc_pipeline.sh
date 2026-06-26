#!/usr/bin/env bash
# ============================================================================
# BetVector — World Cup Pipeline Runner (WC-07-02)
# ============================================================================
# Wrapper for launchd-scheduled WC pipeline runs. Same structure as
# run_pipeline_local.sh but calls the WC pipeline module.
#
# Usage:
#   ./scripts/run_wc_pipeline.sh morning
#   ./scripts/run_wc_pipeline.sh evening
#
# Log rotation: keeps the last 30 days of logs, auto-deletes older ones.
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"
LOG_DIR="$PROJECT_DIR/data/logs"
LOG_RETENTION_DAYS=30
TIMEOUT_SECONDS=1800  # 30 min (WC pipeline is lighter than league)

# ---------------------------------------------------------------------------
# Validate arguments
# ---------------------------------------------------------------------------
MODE="${1:-}"
if [[ -z "$MODE" ]]; then
    echo "Usage: $0 <morning|evening>"
    exit 1
fi

if [[ "$MODE" != "morning" && "$MODE" != "evening" ]]; then
    echo "Error: Invalid mode '$MODE'. Must be one of: morning, evening"
    exit 1
fi

# ---------------------------------------------------------------------------
# Ensure log directory exists
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------------
# Timestamped log file
# ---------------------------------------------------------------------------
DATE_STAMP="$(date +%Y-%m-%d)"
TIME_STAMP="$(date +%H:%M:%S)"
LOG_FILE="$LOG_DIR/wc_${MODE}_${DATE_STAMP}.log"

# ---------------------------------------------------------------------------
# Source .env (launchd doesn't inherit shell env vars)
# ---------------------------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
    # Non-fatal source: a single malformed .env line (e.g. a stray space after
    # '=', which bash mis-parses as `KEY= ` + a command) must NOT abort the
    # whole results run under `set -e`. The pipeline's Python entrypoint also
    # calls load_dotenv(), which parses such quirks correctly and is the real
    # loader, so this shell source is best-effort. stderr -> /dev/null so a bad
    # line can never echo a secret value into the logs.
    set +e
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE" 2>/dev/null
    set +a
    set -e
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
# Run the WC pipeline
# ---------------------------------------------------------------------------
echo "========================================" >> "$LOG_FILE"
echo "[$TIME_STAMP] BetVector WC $MODE pipeline starting" >> "$LOG_FILE"
echo "Working directory: $PROJECT_DIR" >> "$LOG_FILE"
echo "Python: $(which python)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

cd "$PROJECT_DIR"

# Kill any leftover WC pipeline process from a previous run
pkill -f "python -m src.world_cup.pipeline --mode $MODE" 2>/dev/null || true
sleep 1

# Run with timeout to prevent zombie processes
set +e
python -m src.world_cup.pipeline --mode "$MODE" >> "$LOG_FILE" 2>&1 &
PID=$!
ELAPSED=0
while kill -0 "$PID" 2>/dev/null; do
    if (( ELAPSED >= TIMEOUT_SECONDS )); then
        echo "[$TIME_STAMP] WC Pipeline $MODE TIMED OUT after ${TIMEOUT_SECONDS}s — killing PID $PID" >> "$LOG_FILE"
        kill "$PID" 2>/dev/null
        wait "$PID" 2>/dev/null
        EXIT_CODE=124
        break
    fi
    sleep 10
    (( ELAPSED += 10 ))
done
if (( ELAPSED < TIMEOUT_SECONDS )); then
    wait "$PID"
    EXIT_CODE=$?
fi
set -e

END_TIME="$(date +%H:%M:%S)"
echo "========================================" >> "$LOG_FILE"
echo "[$END_TIME] WC Pipeline $MODE finished with exit code $EXIT_CODE" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# ---------------------------------------------------------------------------
# Log rotation
# ---------------------------------------------------------------------------
find "$LOG_DIR" -name "wc_*.log" -type f -mtime +$LOG_RETENTION_DAYS -delete 2>/dev/null || true

exit $EXIT_CODE
