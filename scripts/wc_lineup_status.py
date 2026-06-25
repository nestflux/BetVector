"""Show WC lineup-capture status for a date (default today), per match.

Runs against whatever DB is configured: Neon when .env is loaded (default),
or local SQLite when BETVECTOR_FORCE_LOCAL_DB=1. Each match needs 22 starters
(both XIs): ✓ captured, ⚠ partial, ✗ missing. Read-only.

Usage:
    source venv/bin/activate && python scripts/wc_lineup_status.py [YYYY-MM-DD]
"""
import sys
from datetime import date as _date

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv("/Users/kyng/Projects/BetVector/.env")
from src.database.db import get_engine  # noqa: E402

day = sys.argv[1] if len(sys.argv) > 1 else _date.today().isoformat()
eng = get_engine()

SQL = text(
    "SELECT m.id, m.kickoff_time, h.name AS home, a.name AS away, "
    "COUNT(l.id) AS n, COALESCE(SUM(l.is_starter), 0) AS starters "
    "FROM wc_matches m "
    "JOIN wc_teams h ON h.id = m.home_team_id "
    "JOIN wc_teams a ON a.id = m.away_team_id "
    "LEFT JOIN wc_lineups l ON l.match_id = m.id "
    "WHERE m.date = :day "
    "GROUP BY m.id, m.kickoff_time, h.name, a.name "
    "ORDER BY m.kickoff_time, m.id"
)
with eng.connect() as c:
    rows = c.execute(SQL, {"day": day}).fetchall()

print(f"WC lineup status for {day}  (backend={eng.url.get_backend_name()})")
print("-" * 64)
if not rows:
    print("  No WC matches scheduled on this date.")
for mid, ko, home, away, n, starters in rows:
    starters = int(starters or 0)
    mark = "OK " if starters >= 22 else ("warn" if starters > 0 else "MISS")
    print(f"  [{mark}] match {mid}  {ko or '--:--'}  {home} v {away} "
          f"-- {starters}/22 starters ({n} players)")
