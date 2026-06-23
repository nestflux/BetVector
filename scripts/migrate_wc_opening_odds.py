"""WC-09-03 migration — add wc_odds.opening_odds + backfill.

Adds the opening_odds column (the frozen first-seen price, for line movement)
and backfills it to the current odds_decimal for existing rows (movement = 0 for
already-stored odds — the best we can do without prior history). Idempotent.
Run once:  python scripts/migrate_wc_opening_odds.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

from src.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")


def main() -> None:
    targets = []
    neon = os.environ.get("DATABASE_URL")
    if neon:
        targets.append(("NEON", neon))
    targets.append(("SQLITE", f"sqlite:///{(PROJECT_ROOT / 'data' / 'betvector.db').resolve()}"))

    for label, url in targets:
        eng = create_engine(url)
        insp = inspect(eng)
        if "wc_odds" not in insp.get_table_names():
            print(f"{label}: wc_odds table missing — skip")
            continue
        cols = {c["name"] for c in insp.get_columns("wc_odds")}
        coltype = "DOUBLE PRECISION" if str(eng.url).startswith("postgresql") else "REAL"
        with eng.begin() as c:
            if "opening_odds" in cols:
                print(f"{label}: opening_odds already present")
            else:
                c.execute(text(f"ALTER TABLE wc_odds ADD COLUMN opening_odds {coltype}"))
                print(f"{label}: added opening_odds")
            res = c.execute(text(
                "UPDATE wc_odds SET opening_odds = odds_decimal WHERE opening_odds IS NULL"
            ))
            print(f"{label}: backfilled {res.rowcount} rows (opening = current)")


if __name__ == "__main__":
    main()
