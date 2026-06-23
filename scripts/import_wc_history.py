"""
BetVector World Cup 2026 — Historical International Results Import (WC-01-03)
==============================================================================
Downloads martj42/international_results CSV from GitHub and loads matches from
2018 onward into wc_historical_matches. Also imports completed WC 2026 matches.

Match weights by tournament type:
    1.0  — FIFA World Cup
    0.75 — Continental championships (Copa América, Euro, AFCON, Asian Cup, Gold Cup)
    0.50 — World Cup qualifiers, Nations League
    0.25 — Friendlies and other matches

Usage:
    python scripts/import_wc_history.py
"""

from __future__ import annotations

import csv
import io
import logging
import sys
from pathlib import Path

import requests
from sqlalchemy import select

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database.db import get_session, init_db
from src.world_cup.models import WCHistoricalMatch

logger = logging.getLogger(__name__)

DATASET_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)

TOURNAMENT_WEIGHTS = {
    "FIFA World Cup": 1.0,
    "FIFA World Cup qualification": 0.5,
    "Copa América": 0.75,
    "UEFA Euro": 0.75,
    "UEFA Euro qualification": 0.5,
    "Africa Cup of Nations": 0.75,
    "Africa Cup of Nations qualification": 0.5,
    "AFC Asian Cup": 0.75,
    "AFC Asian Cup qualification": 0.5,
    "CONCACAF Gold Cup": 0.75,
    "CONCACAF Nations League": 0.5,
    "UEFA Nations League": 0.5,
    "Confederations Cup": 0.75,
    "Finalissima": 0.75,
}
DEFAULT_WEIGHT = 0.25


def _get_weight(tournament: str) -> float:
    t = tournament.lower()
    # Check longer (more specific) keys first by sorting descending by length
    for key in sorted(TOURNAMENT_WEIGHTS, key=len, reverse=True):
        if key.lower() in t:
            return TOURNAMENT_WEIGHTS[key]
    # Catch remaining continental tournaments
    if "qualification" in t or "qualif" in t:
        return 0.5
    if "gold cup" in t or "nations league" in t:
        return 0.5
    if "cup of nations" in t or "asian cup" in t or "copa" in t:
        return 0.75
    return DEFAULT_WEIGHT


def download_and_import(min_year: int = 2018) -> int:
    logger.info("Downloading international results from GitHub...")
    resp = requests.get(DATASET_URL, timeout=60)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    rows = []
    for row in reader:
        if row["date"] < f"{min_year}-01-01":
            continue
        if row["home_score"] == "NA" or row["away_score"] == "NA":
            continue
        rows.append(row)

    logger.info("Filtered %d matches from %d onward", len(rows), min_year)

    inserted = 0
    skipped = 0

    with get_session() as session:
        for row in rows:
            exists = session.execute(
                select(WCHistoricalMatch).where(
                    WCHistoricalMatch.date == row["date"],
                    WCHistoricalMatch.home_team == row["home_team"],
                    WCHistoricalMatch.away_team == row["away_team"],
                )
            ).scalar_one_or_none()

            if exists:
                skipped += 1
                continue

            match = WCHistoricalMatch(
                date=row["date"],
                home_team=row["home_team"],
                away_team=row["away_team"],
                home_goals=int(row["home_score"]),
                away_goals=int(row["away_score"]),
                tournament=row["tournament"],
                match_weight=_get_weight(row["tournament"]),
                neutral_venue=1 if row.get("neutral", "").upper() == "TRUE" else 0,
            )
            session.add(match)
            inserted += 1

    logger.info("Imported %d matches, skipped %d duplicates", inserted, skipped)
    return inserted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    init_db()
    n = download_and_import()
    print(f"Done. Imported {n} international matches.")
