#!/usr/bin/env python3
"""
BetVector — Fix Season is_loaded Flags (PC-14-07)
===================================================
One-time script that audits all Season rows and fixes their is_loaded
flag, start_date, and end_date based on actual match data in the DB.

Logic:
  - If a season has > 0 matches: is_loaded=1, start_date=MIN(match.date),
    end_date=MAX(match.date)
  - If a season has 0 matches: is_loaded=0, clear start/end dates

This is idempotent — running it twice produces the same result.

Usage::

    python scripts/fix_season_flags.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import func  # noqa: E402

from src.database.db import get_session  # noqa: E402
from src.database.models import League, Match, Season  # noqa: E402


def main() -> None:
    print("=" * 70)
    print("BetVector — Fix Season is_loaded Flags (PC-14-07)")
    print("=" * 70)
    print()

    updated = 0
    unchanged = 0

    with get_session() as session:
        seasons = (
            session.query(Season)
            .join(League)
            .order_by(League.id, Season.season)
            .all()
        )

        for s in seasons:
            # Count matches for this league-season
            match_count = (
                session.query(func.count(Match.id))
                .filter(
                    Match.league_id == s.league_id,
                    Match.season == s.season,
                )
                .scalar()
            ) or 0

            # Get date range
            date_range = (
                session.query(
                    func.min(Match.date),
                    func.max(Match.date),
                )
                .filter(
                    Match.league_id == s.league_id,
                    Match.season == s.season,
                )
                .first()
            )
            min_date = date_range[0] if date_range else None
            max_date = date_range[1] if date_range else None

            # Determine correct state
            should_be_loaded = 1 if match_count > 0 else 0

            # Check if update needed
            needs_update = (
                s.is_loaded != should_be_loaded
                or (should_be_loaded and s.start_date != min_date)
                or (should_be_loaded and s.end_date != max_date)
            )

            league = session.query(League).filter_by(id=s.league_id).first()
            league_name = league.short_name if league else f"L{s.league_id}"

            if needs_update:
                old_loaded = s.is_loaded
                s.is_loaded = should_be_loaded
                if should_be_loaded:
                    s.start_date = min_date
                    s.end_date = max_date
                else:
                    s.start_date = None
                    s.end_date = None

                status = "FIXED" if old_loaded != should_be_loaded else "DATES"
                print(
                    f"  [{status}] {league_name} {s.season}: "
                    f"is_loaded={old_loaded}->{should_be_loaded}, "
                    f"{match_count} matches, "
                    f"dates={min_date} to {max_date}"
                )
                updated += 1
            else:
                print(
                    f"  [  OK  ] {league_name} {s.season}: "
                    f"is_loaded={s.is_loaded}, "
                    f"{match_count} matches"
                )
                unchanged += 1

        session.commit()

    print()
    print(f"Done: {updated} updated, {unchanged} unchanged")


if __name__ == "__main__":
    main()
