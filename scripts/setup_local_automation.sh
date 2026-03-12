#!/usr/bin/env bash
# ============================================================================
# BetVector — Install Local Automation (PC-15-04)
# ============================================================================
# Copies launchd plist files to ~/Library/LaunchAgents/ and loads them
# with launchctl. After running this script, the pipeline will execute
# automatically at:
#
#   07:00  Morning — scrape → features → predict → value bets → email
#   12:00  Midday  — re-fetch odds, recalculate edges
#   21:00  Evening — resolve bets, update P&L, send summary
#
# macOS launchd runs missed jobs when the Mac wakes from sleep, so
# even if the laptop is closed at 07:00, the morning pipeline will
# run when it opens.
#
# Prerequisites:
#   - Python venv set up:  make install
#   - .env file exists with API keys (THE_ODDS_API_KEY, etc.)
#
# Usage:
#   ./scripts/setup_local_automation.sh
#
# To remove automation:
#   ./scripts/teardown_local_automation.sh
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_SRC_DIR="$SCRIPT_DIR/launchd"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/data/logs"

PLISTS=(
    "com.betvector.morning.plist"
    "com.betvector.midday.plist"
    "com.betvector.evening.plist"
)

echo "============================================"
echo "  BetVector — Installing Local Automation"
echo "============================================"
echo ""

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
# Check venv exists
if [[ ! -f "$PROJECT_DIR/venv/bin/activate" ]]; then
    echo "ERROR: Python venv not found at $PROJECT_DIR/venv/"
    echo "       Run 'make install' first."
    exit 1
fi

# Check .env exists
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    echo "WARNING: .env file not found at $PROJECT_DIR/.env"
    echo "         Pipeline will run but API calls may fail without keys."
fi

# Check run_pipeline_local.sh is executable
if [[ ! -x "$SCRIPT_DIR/run_pipeline_local.sh" ]]; then
    echo "Making run_pipeline_local.sh executable..."
    chmod +x "$SCRIPT_DIR/run_pipeline_local.sh"
fi

# ---------------------------------------------------------------------------
# Create log directory
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"
echo "Log directory: $LOG_DIR"

# ---------------------------------------------------------------------------
# Create LaunchAgents directory (should already exist on macOS)
# ---------------------------------------------------------------------------
mkdir -p "$LAUNCH_AGENTS_DIR"

# ---------------------------------------------------------------------------
# Install plists
# ---------------------------------------------------------------------------
for PLIST in "${PLISTS[@]}"; do
    SRC="$PLIST_SRC_DIR/$PLIST"
    DEST="$LAUNCH_AGENTS_DIR/$PLIST"

    if [[ ! -f "$SRC" ]]; then
        echo "ERROR: Source plist not found: $SRC"
        exit 1
    fi

    # Unload existing job if already loaded (ignore errors if not loaded)
    launchctl unload "$DEST" 2>/dev/null || true

    # Copy plist to LaunchAgents
    cp "$SRC" "$DEST"
    echo "Installed: $DEST"

    # Load the job
    launchctl load "$DEST"
    echo "  Loaded:  $PLIST"
done

echo ""

# ---------------------------------------------------------------------------
# Verify installation
# ---------------------------------------------------------------------------
echo "============================================"
echo "  Verification"
echo "============================================"
echo ""

LOADED_COUNT=0
for PLIST in "${PLISTS[@]}"; do
    LABEL="${PLIST%.plist}"
    if launchctl list | grep -q "$LABEL"; then
        echo "  [OK]  $LABEL — loaded"
        LOADED_COUNT=$((LOADED_COUNT + 1))
    else
        echo "  [!!]  $LABEL — NOT loaded"
    fi
done

echo ""
if [[ $LOADED_COUNT -eq ${#PLISTS[@]} ]]; then
    echo "All $LOADED_COUNT jobs loaded successfully."
    echo ""
    echo "Schedule (local time):"
    echo "  07:00  Morning pipeline"
    echo "  12:00  Midday pipeline"
    echo "  21:00  Evening pipeline"
    echo ""
    echo "Logs: $LOG_DIR/"
    echo ""
    echo "To remove: ./scripts/teardown_local_automation.sh"
else
    echo "WARNING: Only $LOADED_COUNT/${#PLISTS[@]} jobs loaded."
    echo "Check 'launchctl list | grep betvector' for details."
fi
