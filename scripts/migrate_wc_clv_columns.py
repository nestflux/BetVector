"""WC-09-01 migration — add closing_odds + clv columns to wc_value_bets.

init_db() creates fresh tables with these columns from the model, but existing
databases (Neon, local SQLite) need an ALTER. Idempotent: skips columns that
already exist. Run once:  python scripts/migrate_wc_clv_columns.py
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
        if "wc_value_bets" not in insp.get_table_names():
            print(f"{label}: wc_value_bets table missing — skip")
            continue
        cols = {c["name"] for c in insp.get_columns("wc_value_bets")}
        coltype = "DOUBLE PRECISION" if str(eng.url).startswith("postgresql") else "REAL"
        with eng.begin() as c:
            for col in ("closing_odds", "clv"):
                if col in cols:
                    print(f"{label}: {col} already present")
                else:
                    c.execute(text(f"ALTER TABLE wc_value_bets ADD COLUMN {col} {coltype}"))
                    print(f"{label}: added {col}")


if __name__ == "__main__":
    main()
