"""
BetVector — SQLite → PostgreSQL Data Migration Script (E33-03)
===============================================================
One-time migration that exports all data from the local SQLite database
and imports it into a Neon PostgreSQL instance (or any PostgreSQL).

Usage::

    # Set the target PostgreSQL connection string
    export DATABASE_URL="postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require"

    # Run migration (skips non-empty tables)
    python scripts/migrate_sqlite_to_postgres.py

    # Force mode (truncates target tables and re-migrates)
    python scripts/migrate_sqlite_to_postgres.py --force

Architecture notes:
- Source: SQLite DB from config/settings.yaml (local file)
- Target: DATABASE_URL environment variable (PostgreSQL)
- Uses pure SQLAlchemy — no raw SQL except setval() for PG sequence resets
- Tables migrated in FK-dependency order to avoid constraint violations
- Batch inserts (500 rows per commit) to limit memory usage
- Idempotent: re-running on populated target skips existing data

Master Plan refs: MP §5 Architecture (Database), MP §6 Schema
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from src.database.db import Base
from src.database.models import (
    User,
    League,
    Season,
    Team,
    Match,
    MatchStat,
    Odds,
    ClubElo,
    Feature,
    Prediction,
    ValueBet,
    BetLog,
    ModelPerformance,
    PipelineRun,
    CalibrationHistory,
    FeatureImportanceLog,
    EnsembleWeightHistory,
    MarketPerformance,
    RetrainHistory,
    Weather,
    TeamMarketValue,
    TeamInjury,
    InjuryFlag,
)
from src.config import config, PROJECT_ROOT as PROJ_ROOT


# ============================================================================
# Migration order — respects foreign key dependencies
# ============================================================================
# Tables with no FK dependencies come first, then tables that depend on them.
# This ordering ensures we never insert a row that references a non-existent
# parent record.

MIGRATION_ORDER = [
    # Tier 0: No foreign key dependencies
    User,
    League,
    ModelPerformance,
    PipelineRun,
    CalibrationHistory,
    FeatureImportanceLog,
    EnsembleWeightHistory,
    MarketPerformance,
    RetrainHistory,
    # Tier 1: Depends on leagues
    Season,
    Team,
    # Tier 2: Depends on teams and/or leagues
    ClubElo,           # FK: teams
    TeamMarketValue,   # FK: teams
    TeamInjury,        # FK: teams
    InjuryFlag,        # FK: teams
    # Tier 3: Depends on teams + leagues
    Match,             # FK: leagues, teams
    # Tier 4: Depends on matches
    MatchStat,         # FK: matches, teams
    Odds,              # FK: matches
    Weather,           # FK: matches
    Feature,           # FK: matches, teams
    Prediction,        # FK: matches
    # Tier 5: Depends on matches + predictions/users
    ValueBet,          # FK: matches, predictions
    BetLog,            # FK: users, matches
]

BATCH_SIZE = 500


# ============================================================================
# Helpers
# ============================================================================

def _get_sqlite_url() -> str:
    """Build the SQLite connection URL from config."""
    db_path = config.settings.database.path
    full_path = (PROJ_ROOT / db_path).resolve()
    if not full_path.exists():
        print(f"ERROR: SQLite database not found at {full_path}")
        sys.exit(1)
    return f"sqlite:///{full_path}"


def _get_postgres_url() -> str:
    """Get the PostgreSQL URL from DATABASE_URL env var."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.")
        print("Set it to your Neon PostgreSQL connection string:")
        print('  export DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require"')
        sys.exit(1)
    if not url.startswith("postgresql"):
        print(f"ERROR: DATABASE_URL must start with 'postgresql', got: {url[:30]}...")
        sys.exit(1)
    return url


def _reset_sequence(pg_session: Session, table_name: str) -> None:
    """Reset PostgreSQL auto-increment sequence to max(id) + 1.

    PostgreSQL sequences don't auto-advance when rows are inserted with
    explicit ID values (as we do during migration).  Without this reset,
    the next INSERT without an explicit ID would get a conflicting value.
    """
    try:
        result = pg_session.execute(
            text(f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                 f"COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1, false)")
        )
        pg_session.commit()
    except Exception:
        # Some tables might not have an 'id' serial column — that's OK
        pg_session.rollback()


def _row_to_dict(obj) -> dict:
    """Convert a SQLAlchemy ORM object to a plain dict of column values."""
    mapper = type(obj).__mapper__
    return {col.key: getattr(obj, col.key) for col in mapper.column_attrs}


# ============================================================================
# Main migration
# ============================================================================

def migrate(force: bool = False) -> None:
    """Run the SQLite → PostgreSQL migration."""
    start = time.time()

    sqlite_url = _get_sqlite_url()
    pg_url = _get_postgres_url()

    # Mask password in output
    pg_display = pg_url.split("@")[0].rsplit(":", 1)[0] + ":***@" + pg_url.split("@", 1)[1] if "@" in pg_url else pg_url

    print("=" * 70)
    print("BetVector — SQLite → PostgreSQL Migration")
    print("=" * 70)
    print(f"Source:  {sqlite_url}")
    print(f"Target:  {pg_display}")
    print(f"Mode:    {'FORCE (truncate + re-migrate)' if force else 'Normal (skip non-empty tables)'}")
    print("=" * 70)
    print()

    # Create engines
    sqlite_engine = create_engine(sqlite_url, echo=False)
    pg_engine = create_engine(
        pg_url, echo=False,
        pool_pre_ping=True, pool_size=3, max_overflow=2, pool_recycle=300,
    )

    # Create all tables on PostgreSQL (if they don't exist)
    print("[Step 1/3] Creating tables on PostgreSQL...")
    Base.metadata.create_all(pg_engine)
    pg_inspector = inspect(pg_engine)
    pg_tables = pg_inspector.get_table_names()
    print(f"  → {len(pg_tables)} tables ready on PostgreSQL\n")

    # Create sessions
    SqliteSession = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    PgSession = sessionmaker(bind=pg_engine, expire_on_commit=False)

    # Migrate each table
    print("[Step 2/3] Migrating data...\n")
    results = []  # (table_name, sqlite_count, pg_count, status)

    for model in MIGRATION_ORDER:
        table_name = model.__tablename__
        sqlite_sess = SqliteSession()
        pg_sess = PgSession()

        try:
            # Count source rows
            sqlite_count = sqlite_sess.query(model).count()

            # Check if target already has data
            pg_count_before = pg_sess.query(model).count()

            if pg_count_before > 0 and not force:
                print(f"  {table_name:30s}  SKIP ({pg_count_before} rows already exist)")
                results.append((table_name, sqlite_count, pg_count_before, "SKIP"))
                continue

            if pg_count_before > 0 and force:
                # Truncate target table (CASCADE to handle FKs)
                pg_sess.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
                pg_sess.commit()

            if sqlite_count == 0:
                print(f"  {table_name:30s}  EMPTY (0 rows in source)")
                results.append((table_name, 0, 0, "EMPTY"))
                continue

            # Read all rows from SQLite
            rows = sqlite_sess.query(model).all()

            # Batch-insert into PostgreSQL
            migrated = 0
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                row_dicts = [_row_to_dict(r) for r in batch]

                # Insert using bulk_insert_mappings for efficiency
                pg_sess.bulk_insert_mappings(model, row_dicts)
                pg_sess.commit()
                migrated += len(batch)

            # Reset sequence
            _reset_sequence(pg_sess, table_name)

            # Verify count
            pg_count_after = pg_sess.query(model).count()
            match = "✅" if pg_count_after == sqlite_count else "❌ MISMATCH"
            print(f"  {table_name:30s}  {sqlite_count:>6,} rows  {match}")
            results.append((table_name, sqlite_count, pg_count_after,
                            "OK" if pg_count_after == sqlite_count else "MISMATCH"))

        except Exception as e:
            print(f"  {table_name:30s}  ERROR: {e}")
            results.append((table_name, -1, -1, f"ERROR: {e}"))
            pg_sess.rollback()
        finally:
            sqlite_sess.close()
            pg_sess.close()

    # Validation report
    print()
    print("[Step 3/3] Validation Report")
    print("=" * 70)
    print(f"{'Table':30s}  {'SQLite':>8s}  {'PostgreSQL':>10s}  {'Status':>10s}")
    print("-" * 70)

    total_sqlite = 0
    total_pg = 0
    all_ok = True

    for table_name, s_count, p_count, status in results:
        if s_count >= 0:
            total_sqlite += s_count
        if p_count >= 0:
            total_pg += p_count
        icon = "✅" if status in ("OK", "SKIP", "EMPTY") else "❌"
        print(f"  {table_name:30s}  {s_count:>8,}  {p_count:>10,}  {icon} {status}")
        if status not in ("OK", "SKIP", "EMPTY"):
            all_ok = False

    print("-" * 70)
    print(f"  {'TOTAL':30s}  {total_sqlite:>8,}  {total_pg:>10,}")
    print("=" * 70)

    elapsed = time.time() - start
    if all_ok:
        print(f"\n✅ Migration completed successfully in {elapsed:.1f}s")
    else:
        print(f"\n❌ Migration completed with errors in {elapsed:.1f}s")
        sys.exit(1)


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate BetVector data from SQLite to PostgreSQL"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Truncate target tables and re-migrate all data"
    )
    args = parser.parse_args()
    migrate(force=args.force)
