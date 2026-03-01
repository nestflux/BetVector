#!/usr/bin/env bash
# ============================================================================
# BetVector — Database Backup Script (E13-03)
# ============================================================================
# Creates a timestamped copy of the SQLite database.
#
# Usage:
#   ./scripts/backup_db.sh                      # Default backup directory
#   ./scripts/backup_db.sh /path/to/backups     # Custom backup directory
#
# The backup file is named: betvector_YYYY-MM-DD_HHMMSS.db
# ============================================================================

set -euo pipefail

# Project root is the parent of the scripts/ directory
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_FILE="${PROJECT_ROOT}/data/betvector.db"

# Backup destination (default: data/backups/)
BACKUP_DIR="${1:-${PROJECT_ROOT}/data/backups}"

# Timestamp for the backup filename
TIMESTAMP="$(date -u +%Y-%m-%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/betvector_${TIMESTAMP}.db"

# --- Pre-flight checks ---
if [ ! -f "$DB_FILE" ]; then
    echo "ERROR: Database file not found: ${DB_FILE}"
    echo "Run 'python run_pipeline.py setup' first."
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# --- Create backup ---
# Use SQLite's .backup command for a safe, consistent copy.
# This is better than a plain 'cp' because it handles WAL mode correctly
# and ensures the backup is a valid, self-contained database.
if command -v sqlite3 &> /dev/null; then
    sqlite3 "$DB_FILE" ".backup '${BACKUP_FILE}'"
else
    # Fallback to cp if sqlite3 is not available
    cp "$DB_FILE" "$BACKUP_FILE"
fi

# --- Report ---
BACKUP_SIZE="$(du -h "$BACKUP_FILE" | cut -f1)"
echo "Backup created: ${BACKUP_FILE} (${BACKUP_SIZE})"

# --- Cleanup old backups (keep last 10) ---
BACKUP_COUNT=$(ls -1 "${BACKUP_DIR}"/betvector_*.db 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt 10 ]; then
    REMOVE_COUNT=$((BACKUP_COUNT - 10))
    ls -1t "${BACKUP_DIR}"/betvector_*.db | tail -n "$REMOVE_COUNT" | while read -r old; do
        echo "Removing old backup: ${old}"
        rm -f "$old"
    done
fi
