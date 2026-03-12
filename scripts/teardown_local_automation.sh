#!/usr/bin/env bash
# ============================================================================
# BetVector — Remove Local Automation (PC-15-04)
# ============================================================================
# Unloads launchd jobs and removes plist files from ~/Library/LaunchAgents/.
# Does NOT delete pipeline logs — those remain in data/logs/ for review.
#
# Usage:
#   ./scripts/teardown_local_automation.sh
#
# To reinstall:
#   ./scripts/setup_local_automation.sh
# ============================================================================

set -euo pipefail

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

PLISTS=(
    "com.betvector.morning.plist"
    "com.betvector.midday.plist"
    "com.betvector.evening.plist"
)

echo "============================================"
echo "  BetVector — Removing Local Automation"
echo "============================================"
echo ""

REMOVED_COUNT=0
for PLIST in "${PLISTS[@]}"; do
    DEST="$LAUNCH_AGENTS_DIR/$PLIST"
    LABEL="${PLIST%.plist}"

    if [[ -f "$DEST" ]]; then
        # Unload the job (ignore errors if already unloaded)
        launchctl unload "$DEST" 2>/dev/null || true
        echo "  Unloaded: $LABEL"

        # Remove the plist file
        rm "$DEST"
        echo "  Removed:  $DEST"
        REMOVED_COUNT=$((REMOVED_COUNT + 1))
    else
        echo "  Skipped:  $PLIST — not found in $LAUNCH_AGENTS_DIR/"
    fi
done

echo ""

# ---------------------------------------------------------------------------
# Verify removal
# ---------------------------------------------------------------------------
REMAINING=$(launchctl list 2>/dev/null | grep -c "betvector" || true)
if [[ $REMAINING -eq 0 ]]; then
    echo "All BetVector jobs removed successfully."
else
    echo "WARNING: $REMAINING BetVector job(s) still loaded."
    echo "Run 'launchctl list | grep betvector' to investigate."
fi

echo ""
echo "Note: Pipeline logs in data/logs/ were NOT deleted."
echo "To reinstall: ./scripts/setup_local_automation.sh"
