"""
BetVector — Internal Elo Calculator (PC-08-04)
===============================================
Computes Elo ratings from historical match results for leagues where
the ClubElo API has incomplete coverage (e.g., Championship has 61%
null Elo data because ClubElo only covers ~28 of 42 unique teams).

Algorithm: Standard Elo rating system
  - K-factor: 32 (configurable in settings.yaml)
  - Initial rating: 1500 (configurable)
  - Home advantage: +65 Elo points (configurable)
  - Expected score: E = 1 / (1 + 10^((R_opp - R_team) / 400))
  - Update: R_new = R_old + K * (S_actual - E_expected)
  - S_actual: 1.0 (win), 0.5 (draw), 0.0 (loss)

The computed ratings are stored in the existing ``club_elo`` table
(same schema as ClubElo API data), so downstream code (feature engineer,
predictions) works without any changes.

Temporal integrity: Matches are processed in chronological order.
Each team's Elo on match day reflects ONLY results from previous matches.

Usage::

    from src.features.elo_calculator import compute_internal_elo

    # Compute Elo for Championship
    compute_internal_elo(league_short_name="Championship")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_

from src.config import config
from src.database.db import get_session
from src.database.models import ClubElo, League, Match, Team

logger = logging.getLogger(__name__)


def compute_internal_elo(
    league_short_name: str = "Championship",
    k_factor: Optional[float] = None,
    initial_rating: Optional[float] = None,
    home_advantage: Optional[float] = None,
    dry_run: bool = False,
) -> Dict[str, float]:
    """Compute Elo ratings from match results and store in club_elo table.

    Processes all finished matches for the specified league in chronological
    order, computing a running Elo rating for each team.  Stores one rating
    per team per match date in the ``club_elo`` table.

    Parameters
    ----------
    league_short_name : str
        Short name of the league (e.g., "Championship").
    k_factor : float, optional
        Elo K-factor.  Higher = more reactive to recent results.
        Defaults to ``config.settings.internal_elo.k_factor`` (32).
    initial_rating : float, optional
        Starting Elo for a team with no history.
        Defaults to ``config.settings.internal_elo.initial_rating`` (1500).
    home_advantage : float, optional
        Elo points added to home team for expected score calculation.
        Defaults to ``config.settings.internal_elo.home_advantage`` (65).
    dry_run : bool
        If True, compute ratings but don't write to DB.

    Returns
    -------
    dict
        Final Elo ratings by team name (e.g., {"Leeds": 1623.4, ...}).
    """
    # Load config defaults
    elo_cfg = getattr(config.settings, "internal_elo", None)
    if k_factor is None:
        k_factor = float(getattr(elo_cfg, "k_factor", 32)) if elo_cfg else 32.0
    if initial_rating is None:
        initial_rating = float(getattr(elo_cfg, "initial_rating", 1500)) if elo_cfg else 1500.0
    if home_advantage is None:
        home_advantage = float(getattr(elo_cfg, "home_advantage", 65)) if elo_cfg else 65.0

    logger.info(
        "Computing internal Elo for %s (K=%.0f, init=%.0f, home_adv=%.0f)",
        league_short_name, k_factor, initial_rating, home_advantage,
    )

    with get_session() as session:
        # Find the league
        league = session.query(League).filter_by(
            short_name=league_short_name,
        ).first()
        if not league:
            logger.error("League '%s' not found in DB.", league_short_name)
            return {}

        # Load all finished matches in chronological order
        # Temporal integrity: process oldest first so each match only uses
        # Elo from previous matches.
        matches = (
            session.query(Match)
            .filter(
                Match.league_id == league.id,
                Match.status == "finished",
                Match.home_goals.isnot(None),
                Match.away_goals.isnot(None),
            )
            .order_by(Match.date.asc(), Match.id.asc())
            .all()
        )

        if not matches:
            logger.warning("No finished matches found for %s.", league_short_name)
            return {}

        logger.info(
            "Processing %d finished matches for %s (%s to %s).",
            len(matches), league_short_name,
            matches[0].date, matches[-1].date,
        )

        # Build team_id → team_name lookup
        teams = session.query(Team).filter_by(league_id=league.id).all()
        team_names: Dict[int, str] = {t.id: t.name for t in teams}

        # Running Elo ratings: team_id → current Elo
        ratings: Dict[int, float] = defaultdict(lambda: initial_rating)

        # Collect all (team_id, rating, date) tuples to batch-insert
        elo_records: List[Tuple[int, float, str]] = []

        for match in matches:
            home_id = match.home_team_id
            away_id = match.away_team_id
            home_score = match.home_goals
            away_score = match.away_goals
            match_date = match.date

            # Current ratings (before this match)
            home_elo = ratings[home_id]
            away_elo = ratings[away_id]

            # Store the pre-match rating for both teams on this date
            # This is what the feature engineer will look up — the Elo
            # BEFORE the match, which is temporally safe.
            elo_records.append((home_id, round(home_elo, 1), match_date))
            elo_records.append((away_id, round(away_elo, 1), match_date))

            # Expected scores (home team gets home advantage bonus)
            home_expected = _expected_score(
                home_elo + home_advantage, away_elo,
            )
            away_expected = 1.0 - home_expected

            # Actual scores
            if home_score > away_score:
                home_actual, away_actual = 1.0, 0.0
            elif home_score < away_score:
                home_actual, away_actual = 0.0, 1.0
            else:
                home_actual, away_actual = 0.5, 0.5

            # Update ratings
            ratings[home_id] = home_elo + k_factor * (home_actual - home_expected)
            ratings[away_id] = away_elo + k_factor * (away_actual - away_expected)

        logger.info(
            "Computed Elo for %d teams across %d matches → %d rating records.",
            len(ratings), len(matches), len(elo_records),
        )

        if dry_run:
            logger.info("Dry run — not writing to DB.")
        else:
            # Write to club_elo table (idempotent: skip existing records)
            inserted = _store_elo_records(session, elo_records)
            logger.info("Stored %d new ClubElo records.", inserted)

    # Return final ratings by team name
    final_ratings = {}
    for team_id, elo in sorted(ratings.items(), key=lambda x: -x[1]):
        name = team_names.get(team_id, f"team_{team_id}")
        final_ratings[name] = round(elo, 1)

    # Log top 5 and bottom 5
    sorted_teams = sorted(final_ratings.items(), key=lambda x: -x[1])
    if len(sorted_teams) >= 5:
        top5 = ", ".join(f"{n}: {e:.0f}" for n, e in sorted_teams[:5])
        bot5 = ", ".join(f"{n}: {e:.0f}" for n, e in sorted_teams[-5:])
        logger.info("Top 5: %s", top5)
        logger.info("Bottom 5: %s", bot5)

    return final_ratings


def _expected_score(elo_a: float, elo_b: float) -> float:
    """Calculate expected score for team A against team B.

    Uses the standard Elo formula:
        E_A = 1 / (1 + 10^((R_B - R_A) / 400))

    Parameters
    ----------
    elo_a : float
        Elo rating of team A (may include home advantage).
    elo_b : float
        Elo rating of team B.

    Returns
    -------
    float
        Expected score for team A (0.0 to 1.0).
    """
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def _store_elo_records(
    session,
    records: List[Tuple[int, float, str]],
) -> int:
    """Store Elo records in the club_elo table, skipping duplicates.

    Uses INSERT ... ON CONFLICT DO NOTHING (PostgreSQL) or
    INSERT OR IGNORE (SQLite) to avoid duplicates via the
    (team_id, rating_date) unique constraint.

    Parameters
    ----------
    session : SQLAlchemy session
        Active DB session.
    records : list of (team_id, elo_rating, rating_date)
        Elo records to insert.

    Returns
    -------
    int
        Number of new records inserted.
    """
    inserted = 0
    batch_size = 500

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        for team_id, elo_rating, rating_date in batch:
            # Check for existing record (idempotent)
            existing = (
                session.query(ClubElo)
                .filter(
                    ClubElo.team_id == team_id,
                    ClubElo.rating_date == rating_date,
                )
                .first()
            )
            if existing:
                # Update if the existing record differs significantly
                # (allows re-running with different parameters)
                if abs(existing.elo_rating - elo_rating) > 0.5:
                    existing.elo_rating = elo_rating
                    inserted += 1
                continue

            elo = ClubElo(
                team_id=team_id,
                elo_rating=elo_rating,
                rank=None,  # Internal Elo has no global rank
                rating_date=rating_date,
            )
            session.add(elo)
            inserted += 1

        # Flush each batch to avoid memory buildup
        session.flush()

    return inserted


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    league = sys.argv[1] if len(sys.argv) > 1 else "Championship"
    dry = "--dry-run" in sys.argv

    final = compute_internal_elo(league_short_name=league, dry_run=dry)
    print(f"\nFinal ratings ({len(final)} teams):")
    for name, elo in sorted(final.items(), key=lambda x: -x[1]):
        print(f"  {name:30s} {elo:7.1f}")
