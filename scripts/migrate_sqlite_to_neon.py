"""SQLite → Neon Postgres migration.

Strategy:
  1. Back up the single user_placed bet from Neon → JSON
  2. Drop all tables in Neon (CASCADE)
  3. Re-create schema via Base.metadata.create_all()
  4. Bulk-copy each table from local SQLite, in FK-safe order
  5. Re-sync Postgres sequences (so future INSERTs don't collide)
  6. Re-insert the user_placed bet
  7. Verify row counts

Idempotent: safe to rerun if an earlier run failed midway.

Usage:
    NEON_DSN='postgresql://...' venv/bin/python /tmp/bv_migrate_to_neon.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project imports resolve
sys.path.insert(0, "/Users/kyng/Projects/BetVector")

from sqlalchemy import (
    Boolean, Date, DateTime, Float, Integer, String, Text,
    create_engine, inspect, text,
)
from sqlalchemy.orm import sessionmaker


def _coerce_nulls_for_postgres(table, rows: list[dict]) -> list[dict]:
    """Backfill SQLite-tolerated NULLs in NOT NULL columns.

    SQLite is lenient about NOT NULL constraints — when a column has a
    server-side default that wasn't fired (e.g. inserted via raw SQL or in
    older code paths), the row may carry NULL even though the schema says
    NOT NULL. Postgres rejects these.

    Strategy:
      - For every NOT NULL column with a server_default, if the row's
        value is None, substitute a sensible default for the column type.
      - DateTime/Date → datetime.utcnow() / today
      - Numeric → 0
      - String → ""
      - Boolean → False

    This only mutates None values, never overwrites real data.
    """
    now = datetime.utcnow()
    today = now.date()
    fixable_cols = [
        c for c in table.columns
        if not c.nullable and c.server_default is not None and not c.primary_key
    ]
    if not fixable_cols:
        return rows

    for row in rows:
        for col in fixable_cols:
            if row.get(col.name) is None:
                t = col.type
                if isinstance(t, DateTime):
                    row[col.name] = now
                elif isinstance(t, Date):
                    row[col.name] = today
                elif isinstance(t, (Integer, Float)):
                    row[col.name] = 0
                elif isinstance(t, Boolean):
                    row[col.name] = False
                elif isinstance(t, (String, Text)):
                    row[col.name] = ""
    return rows

# Trigger model registration
from src.database import models  # noqa: F401  -- registers all classes on Base
from src.database.db import Base

NEON_DSN = os.environ["NEON_DSN"]
SQLITE_PATH = "/Users/kyng/Projects/BetVector/data/betvector.db"
SQLITE_DSN = f"sqlite:///{SQLITE_PATH}"
BACKUP_PATH = Path("/tmp/bv_user_placed_backup.json")

BATCH_SIZE = 1000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def step1_backup_user_placed(neon_engine) -> list[dict]:
    """Pull all user_placed bets out of Neon before we drop anything.

    Safety: if BACKUP_PATH already contains a non-empty backup from a previous
    run (i.e. an aborted migration), prefer that over the current Neon state —
    the current state may have been wiped by a partial earlier run.
    """
    log("Step 1/7: Backing up user_placed bets from Neon...")

    # Try to read existing backup first — protect against destructive overwrite.
    if BACKUP_PATH.exists():
        try:
            existing = json.loads(BACKUP_PATH.read_text())
        except Exception:
            existing = []
        if existing:
            # Re-validate by checking what's currently on Neon. If Neon has the
            # same or more user_placed bets, prefer the live snapshot. If Neon
            # has fewer (i.e. wiped), keep the existing backup.
            try:
                with neon_engine.connect() as conn:
                    n_neon = conn.execute(text(
                        "SELECT COUNT(*) FROM bet_log WHERE bet_type='user_placed'"
                    )).scalar()
            except Exception:
                n_neon = 0
            if n_neon < len(existing):
                log(
                    f"  ⚠ Existing backup has {len(existing)} bet(s) but Neon "
                    f"only has {n_neon} — keeping existing backup (likely "
                    "from an earlier aborted run)."
                )
                return existing

    with neon_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT * FROM bet_log WHERE bet_type='user_placed'"
        ))
        cols = list(result.keys())
        rows = [dict(zip(cols, r)) for r in result.fetchall()]
    # Convert datetimes to ISO strings for JSON
    for row in rows:
        for k, v in list(row.items()):
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
    BACKUP_PATH.write_text(json.dumps(rows, default=str, indent=2))
    log(f"  ✓ Backed up {len(rows)} user_placed bet(s) → {BACKUP_PATH}")
    return rows


def step2_drop_all(neon_engine) -> None:
    """Drop everything in Neon's public schema."""
    log("Step 2/7: Dropping all tables in Neon...")
    with neon_engine.begin() as conn:
        # DROP SCHEMA + recreate is the cleanest nuke
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO neondb_owner"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    log("  ✓ public schema dropped + recreated")


def step3_create_schema(neon_engine) -> None:
    """Build all tables from the SQLAlchemy models."""
    log("Step 3/7: Creating schema from SQLAlchemy models...")
    Base.metadata.create_all(neon_engine)
    inspector = inspect(neon_engine)
    table_count = len(inspector.get_table_names())
    log(f"  ✓ Created {table_count} tables")


def step4_copy_data(sqlite_engine, neon_engine) -> dict[str, int]:
    """Copy every table in FK-safe order."""
    log("Step 4/7: Copying data from SQLite to Neon...")
    counts: dict[str, int] = {}
    sorted_tables = Base.metadata.sorted_tables  # FK-safe order

    with sqlite_engine.connect() as src, neon_engine.begin() as dst:
        for table in sorted_tables:
            tname = table.name
            # Read all rows from SQLite
            rows = src.execute(table.select()).mappings().all()
            n = len(rows)
            if n == 0:
                log(f"  - {tname:30s} (empty, skipped)")
                counts[tname] = 0
                continue

            # Bulk insert in batches; coerce SQLite-tolerated NULLs first
            for i in range(0, n, BATCH_SIZE):
                batch = [dict(r) for r in rows[i : i + BATCH_SIZE]]
                batch = _coerce_nulls_for_postgres(table, batch)
                dst.execute(table.insert(), batch)

            counts[tname] = n
            log(f"  ✓ {tname:30s} {n:>8,} rows")

    return counts


def step5_resync_sequences(neon_engine) -> None:
    """Bump Postgres sequences past the max imported ID."""
    log("Step 5/7: Re-syncing Postgres sequences...")
    with neon_engine.begin() as conn:
        # Find every sequence and the table+column it backs
        seqs = conn.execute(text("""
            SELECT
                pg_get_serial_sequence(c.relname, a.attname) AS seq,
                c.relname AS table_name,
                a.attname AS column_name
            FROM pg_class c
            JOIN pg_attribute a ON a.attrelid = c.oid
            JOIN pg_attrdef d   ON d.adrelid = c.oid AND d.adnum = a.attnum
            WHERE c.relkind='r'
              AND c.relnamespace = 'public'::regnamespace
              AND pg_get_expr(d.adbin, d.adrelid) LIKE 'nextval%'
        """)).fetchall()

        bumped = 0
        for seq, tbl, col in seqs:
            if not seq:
                continue
            max_id = conn.execute(
                text(f"SELECT COALESCE(MAX({col}), 0) FROM {tbl}")
            ).scalar()
            # setval(seq, n, true) = next nextval() returns n+1
            conn.execute(text(f"SELECT setval(:seq, :n, true)"),
                         {"seq": seq, "n": max(max_id, 1)})
            bumped += 1
        log(f"  ✓ Bumped {bumped} sequences")


def step6_restore_user_placed(neon_engine, backup_rows: list[dict]) -> None:
    """Re-insert user_placed bets after migration."""
    log(f"Step 6/7: Restoring {len(backup_rows)} user_placed bet(s)...")
    if not backup_rows:
        log("  (nothing to restore)")
        return

    # The migrated bet_log already includes system_picks. The user_placed
    # bets need to come back. ID conflicts are likely (the user_placed bet
    # id=1330 may collide with a migrated system_pick id) — so let the DB
    # auto-assign new IDs by stripping 'id' from each row.
    with neon_engine.begin() as conn:
        for row in backup_rows:
            row_copy = {k: v for k, v in row.items() if k != "id"}
            cols = ", ".join(row_copy.keys())
            placeholders = ", ".join(f":{k}" for k in row_copy.keys())
            conn.execute(
                text(f"INSERT INTO bet_log ({cols}) VALUES ({placeholders})"),
                row_copy,
            )
    log(f"  ✓ Restored {len(backup_rows)} bet(s)")


def step7_verify(sqlite_engine, neon_engine) -> bool:
    """Compare row counts table by table."""
    log("Step 7/7: Verifying row counts...")
    inspector = inspect(neon_engine)
    neon_tables = set(inspector.get_table_names())

    all_match = True
    with sqlite_engine.connect() as src, neon_engine.connect() as dst:
        for table in Base.metadata.sorted_tables:
            if table.name not in neon_tables:
                log(f"  ✗ {table.name} missing on Neon!")
                all_match = False
                continue
            src_n = src.execute(text(f"SELECT COUNT(*) FROM {table.name}")).scalar()
            dst_n = dst.execute(text(f"SELECT COUNT(*) FROM {table.name}")).scalar()
            tag = "✓" if src_n == dst_n else "✗"
            extra = ""
            # bet_log will have +N rows where N = restored user_placed count
            if table.name == "bet_log" and dst_n >= src_n:
                tag = "✓"
                extra = f"  (+{dst_n - src_n} restored user_placed)"
            elif src_n != dst_n:
                all_match = False
            log(f"  {tag} {table.name:30s} sqlite={src_n:>8,} neon={dst_n:>8,}{extra}")

    return all_match


def main() -> int:
    sqlite_engine = create_engine(SQLITE_DSN)
    neon_engine = create_engine(NEON_DSN, pool_pre_ping=True)

    t0 = time.time()
    backup = step1_backup_user_placed(neon_engine)
    step2_drop_all(neon_engine)
    step3_create_schema(neon_engine)
    step4_copy_data(sqlite_engine, neon_engine)
    step5_resync_sequences(neon_engine)
    step6_restore_user_placed(neon_engine, backup)
    ok = step7_verify(sqlite_engine, neon_engine)

    dt = time.time() - t0
    log(f"\n{'✓ MIGRATION COMPLETE' if ok else '✗ MIGRATION COMPLETE WITH MISMATCHES'} in {dt:.0f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
