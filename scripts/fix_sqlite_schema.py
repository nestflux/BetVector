"""
BetVector — SQLite Schema Patch Script
=======================================
The backup SQLite DB (data/betvector.db) was created before E14–E22 added new
columns and tables incrementally via ALTER TABLE. The ORM models now expect
those columns, but the backup doesn't have them.

This script adds only the missing pieces (columns and tables) so the migration
script can read the SQLite file cleanly. All added columns default to NULL —
the pipeline will backfill real values on next run.

Usage:
    python scripts/fix_sqlite_schema.py

Then re-run the migration:
    DATABASE_URL="postgresql://..." python scripts/migrate_sqlite_to_postgres.py --force
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "betvector.db"


def add_column(cur: sqlite3.Cursor, table: str, column: str, col_type: str = "REAL") -> None:
    """Add a column if it doesn't already exist. SQLite has no IF NOT EXISTS for ALTER TABLE."""
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"  ✅ Added {table}.{column}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"  ⏭  {table}.{column} already exists")
        else:
            raise


def create_table(cur: sqlite3.Cursor, table_name: str, ddl: str) -> None:
    """Create a table if it doesn't exist."""
    cur.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({ddl})")
    print(f"  ✅ Table {table_name} ensured")


def main() -> None:
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}")
        raise SystemExit(1)

    print(f"Patching: {DB_PATH}\n")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ── teams ────────────────────────────────────────────────────────────────
    print("[teams]")
    add_column(cur, "teams", "api_football_name", "TEXT")
    add_column(cur, "teams", "logo_url", "TEXT")  # added E28 (Team Badges)

    # ── matches ──────────────────────────────────────────────────────────────
    print("\n[matches]")
    add_column(cur, "matches", "referee", "TEXT")

    # ── match_stats ───────────────────────────────────────────────────────────
    print("\n[match_stats]")
    for col in [
        "npxg", "npxga", "ppda_coeff", "ppda_allowed_coeff",
        "deep", "deep_allowed", "set_piece_xg", "open_play_xg",
    ]:
        add_column(cur, "match_stats", col, "REAL")

    # ── features ─────────────────────────────────────────────────────────────
    print("\n[features]")
    feature_cols = [
        # NPxG / PPDA / deep (E16)
        ("npxg_5", "REAL"), ("npxga_5", "REAL"), ("npxg_diff_5", "REAL"),
        ("ppda_5", "REAL"), ("ppda_allowed_5", "REAL"),
        ("deep_5", "REAL"), ("deep_allowed_5", "REAL"),
        ("set_piece_xg_5", "REAL"), ("open_play_xg_5", "REAL"),
        ("npxg_10", "REAL"), ("npxga_10", "REAL"), ("npxg_diff_10", "REAL"),
        ("ppda_10", "REAL"), ("ppda_allowed_10", "REAL"),
        ("deep_10", "REAL"), ("deep_allowed_10", "REAL"),
        # Venue split (E16)
        ("venue_form_5", "REAL"), ("venue_goals_scored_5", "REAL"),
        ("venue_goals_conceded_5", "REAL"), ("venue_xg_5", "REAL"), ("venue_xga_5", "REAL"),
        # Market value (E15/E16)
        ("market_value_ratio", "REAL"), ("squad_value_log", "REAL"),
        # Elo (E21)
        ("elo_rating", "REAL"), ("elo_diff", "REAL"),
        # Referee (E21)
        ("ref_avg_fouls", "REAL"), ("ref_avg_yellows", "REAL"),
        ("ref_avg_goals", "REAL"), ("ref_home_win_pct", "REAL"),
        # Congestion (E21)
        ("days_since_last_match", "INTEGER"), ("is_congested", "INTEGER"),
        # Pinnacle / AH market features (E20)
        ("pinnacle_home_prob", "REAL"), ("pinnacle_draw_prob", "REAL"),
        ("pinnacle_away_prob", "REAL"), ("pinnacle_overround", "REAL"),
        ("ah_line", "REAL"),
        # Weather (E14/E16)
        ("temperature_c", "REAL"), ("wind_speed_kmh", "REAL"),
        ("precipitation_mm", "REAL"), ("is_heavy_weather", "INTEGER"),
        # Injury (E22)
        ("injury_impact", "REAL"), ("key_player_out", "INTEGER"),
    ]
    for col, col_type in feature_cols:
        add_column(cur, "features", col, col_type)

    # ── Missing tables ────────────────────────────────────────────────────────
    print("\n[missing tables]")

    create_table(cur, "club_elo", """
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id     INTEGER NOT NULL REFERENCES teams(id),
        elo_rating  REAL,
        rank        INTEGER,
        rating_date TEXT,
        created_at  TEXT
    """)

    create_table(cur, "team_market_values", """
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id                 INTEGER NOT NULL REFERENCES teams(id),
        squad_total_value       REAL,
        avg_player_value        REAL,
        squad_size              INTEGER,
        contract_expiring_count INTEGER,
        evaluated_at            TEXT,
        source                  TEXT,
        created_at              TEXT
    """)

    create_table(cur, "team_injuries", """
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id             INTEGER NOT NULL REFERENCES teams(id),
        player_name         TEXT,
        injury_type         TEXT,
        days_out            INTEGER,
        player_market_value REAL,
        status              TEXT,
        reported_at         TEXT,
        expected_return     TEXT,
        source              TEXT,
        created_at          TEXT
    """)

    create_table(cur, "injury_flags", """
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id          INTEGER NOT NULL REFERENCES teams(id),
        player_name      TEXT,
        status           TEXT,
        estimated_return TEXT,
        impact_rating    REAL,
        created_at       TEXT,
        updated_at       TEXT
    """)

    create_table(cur, "weather", """
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id         INTEGER NOT NULL REFERENCES matches(id),
        temperature_c    REAL,
        wind_speed_kmh   REAL,
        humidity_pct     REAL,
        precipitation_mm REAL,
        weather_code     INTEGER,
        weather_category TEXT,
        source           TEXT,
        created_at       TEXT
    """)

    conn.commit()
    conn.close()

    print("""
══════════════════════════════════════════════
✅ SQLite schema patched successfully.

Next step — re-run the migration with --force:

    DATABASE_URL="postgresql://..." \\
      python scripts/migrate_sqlite_to_postgres.py --force

The --force flag truncates the partial Neon data
and re-migrates everything cleanly.
══════════════════════════════════════════════
""")


if __name__ == "__main__":
    main()
