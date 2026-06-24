#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# BetVector — WC Pre-Kickoff Dispatcher runner (WC-10-03)
# ---------------------------------------------------------------------------
# Invoked every ~15 min by launchd (com.betvector.wc_dispatcher). Reads the
# LOCAL fixture cache and fires a focused prematch run only when a match is
# ~40 min from kickoff. .env is sourced so that WHEN a prematch fires it reaches
# Neon (DATABASE_URL); idle ticks open no DB connection.
# ---------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"
DATE_STAMP="$(date +%Y-%m-%d)"
LOG_FILE="$LOG_DIR/wc_dispatcher_${DATE_STAMP}.log"
TIME_STAMP="$(date '+%H:%M:%S')"

cd "$PROJECT_DIR"

# Source .env (launchd doesn't inherit shell env vars) — needed only when a
# prematch run actually fires (hits Neon); harmless on idle ticks.
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

if [[ -f "$VENV_DIR/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
else
    echo "[$TIME_STAMP] ERROR: venv not found at $VENV_DIR/bin/activate" >> "$LOG_FILE"
    exit 1
fi

# One quick tick. The ~15-min cadence is launchd's StartInterval, not a loop here.
python -m src.world_cup.dispatcher >> "$LOG_FILE" 2>&1
