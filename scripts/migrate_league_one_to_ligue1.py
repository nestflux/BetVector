"""
PC-08-02 — Migrate English League One → French Ligue 1
=======================================================
One-time migration script that:
  1. Finds the "LeagueOne" league in the DB
  2. Deletes ALL associated data (matches, odds, features, predictions,
     value_bets, match_stats, club_elo, bet_log system_picks)
  3. Updates the league record to "Ligue 1" (French)
  4. Seeds new season records for Ligue 1

This script is idempotent — if "LeagueOne" doesn't exist but "Ligue1" does,
it skips the migration and just ensures seasons are seeded.

Run ONCE against the cloud DB before running the backfill.

Usage:
    python scripts/migrate_league_one_to_ligue1.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from src.config import config
from src.database.db import get_session, init_db
from src.database.models import (
    BetLog,
    ClubElo,
    Feature,
    League,
    Match,
    MatchStat,
    Odds,
    Prediction,
    Season,
    Team,
    ValueBet,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def migrate_league_one_to_ligue1() -> None:
    """Replace English League One with French Ligue 1 in the database."""
    init_db()

    with get_session() as session:
        # Step 1: Find existing LeagueOne
        league_one = session.query(League).filter_by(short_name="LeagueOne").first()
        ligue_1 = session.query(League).filter_by(short_name="Ligue1").first()

        if ligue_1 and not league_one:
            logger.info(
                "Ligue 1 already exists (id=%d) and LeagueOne is gone. "
                "Migration already complete — just ensuring seasons.",
                ligue_1.id,
            )
            _seed_ligue1_seasons(session, ligue_1.id)
            return

        if not league_one and not ligue_1:
            logger.info("Neither LeagueOne nor Ligue1 found. Seeding fresh Ligue 1.")
            _create_ligue1_fresh(session)
            return

        # league_one exists — proceed with migration
        league_id = league_one.id
        logger.info(
            "Found LeagueOne (id=%d, name='%s'). Starting migration...",
            league_id, league_one.name,
        )

        # Step 2: Delete all associated data in dependency order
        # (child tables first to avoid FK violations)

        # 2a. Delete ValueBets (depends on predictions)
        # ValueBet has match_id FK — delete by match
        match_ids = [
            m.id for m in session.query(Match.id).filter_by(league_id=league_id).all()
        ]
        if match_ids:
            vb_count = session.query(ValueBet).filter(
                ValueBet.match_id.in_(match_ids)
            ).delete(synchronize_session=False)
            logger.info("Deleted %d ValueBet rows.", vb_count)

            # 2b. Delete Predictions
            pred_count = session.query(Prediction).filter(
                Prediction.match_id.in_(match_ids)
            ).delete(synchronize_session=False)
            logger.info("Deleted %d Prediction rows.", pred_count)

            # 2c. Delete BetLog system_picks for these matches
            bl_count = session.query(BetLog).filter(
                BetLog.match_id.in_(match_ids)
            ).delete(synchronize_session=False)
            logger.info("Deleted %d BetLog rows.", bl_count)

            # 2d. Delete Features
            feat_count = session.query(Feature).filter(
                Feature.match_id.in_(match_ids)
            ).delete(synchronize_session=False)
            logger.info("Deleted %d Feature rows.", feat_count)

            # 2e. Delete MatchStats
            ms_count = session.query(MatchStat).filter(
                MatchStat.match_id.in_(match_ids)
            ).delete(synchronize_session=False)
            logger.info("Deleted %d MatchStat rows.", ms_count)

            # 2f. Delete Odds
            odds_count = session.query(Odds).filter(
                Odds.match_id.in_(match_ids)
            ).delete(synchronize_session=False)
            logger.info("Deleted %d Odds rows.", odds_count)

            # 2g. Delete Matches
            match_count = session.query(Match).filter_by(
                league_id=league_id,
            ).delete(synchronize_session=False)
            logger.info("Deleted %d Match rows.", match_count)
        else:
            logger.info("No matches found for LeagueOne — skipping data deletion.")

        # 2h. Delete ClubElo for teams in this league
        # ClubElo is stored by team_id; find all team_ids for this league
        team_ids = [
            t.id for t in session.query(Team.id).filter_by(league_id=league_id).all()
        ]
        if team_ids:
            elo_count = session.query(ClubElo).filter(
                ClubElo.team_id.in_(team_ids)
            ).delete(synchronize_session=False)
            logger.info("Deleted %d ClubElo rows.", elo_count)

            # Delete teams themselves
            team_count = session.query(Team).filter_by(
                league_id=league_id,
            ).delete(synchronize_session=False)
            logger.info("Deleted %d Team rows.", team_count)
        else:
            logger.info("No teams found for LeagueOne — skipping team deletion.")

        # 2i. Delete Seasons
        season_count = session.query(Season).filter_by(
            league_id=league_id,
        ).delete(synchronize_session=False)
        logger.info("Deleted %d Season rows.", season_count)

        # Step 3: Update the league record to Ligue 1
        league_one.name = "Ligue 1"
        league_one.short_name = "Ligue1"
        league_one.country = "France"
        league_one.football_data_code = "F1"
        league_one.fbref_league_id = "FRA-Ligue-1"
        league_one.api_football_id = 61
        league_one.is_active = 1
        logger.info(
            "Updated league id=%d: LeagueOne → Ligue1 (France, F1).",
            league_id,
        )

        # Step 4: Seed new seasons for Ligue 1
        _seed_ligue1_seasons(session, league_id)

        # Commit everything
        session.commit()
        logger.info("Migration complete. League id=%d is now Ligue 1.", league_id)


def _seed_ligue1_seasons(session, league_id: int) -> None:
    """Create season records for Ligue 1 if they don't exist."""
    # Get Ligue 1 config from leagues.yaml
    ligue1_cfg = None
    for lc in config.get_active_leagues():
        if lc.short_name == "Ligue1":
            ligue1_cfg = lc
            break

    if not ligue1_cfg:
        logger.error("Ligue1 not found in leagues.yaml config!")
        return

    for season_name in ligue1_cfg.seasons:
        existing = session.query(Season).filter_by(
            league_id=league_id,
            season=season_name,
        ).first()
        if existing:
            logger.info("Season %s already exists for Ligue1, skipping.", season_name)
            continue

        season = Season(
            league_id=league_id,
            season=season_name,
            is_loaded=0,
        )
        session.add(season)
        logger.info("Created season: Ligue1 %s.", season_name)


def _create_ligue1_fresh(session) -> None:
    """Create Ligue 1 league and seasons from scratch."""
    ligue1_cfg = None
    for lc in config.get_active_leagues():
        if lc.short_name == "Ligue1":
            ligue1_cfg = lc
            break

    if not ligue1_cfg:
        logger.error("Ligue1 not found in leagues.yaml config!")
        return

    league = League(
        name=ligue1_cfg.name,
        short_name=ligue1_cfg.short_name,
        country=ligue1_cfg.country,
        football_data_code=ligue1_cfg.football_data_code,
        fbref_league_id=ligue1_cfg.fbref_league_id,
        api_football_id=ligue1_cfg.api_football_id,
        is_active=1,
    )
    session.add(league)
    session.flush()  # Get the league.id

    for season_name in ligue1_cfg.seasons:
        season = Season(
            league_id=league.id,
            season=season_name,
            is_loaded=0,
        )
        session.add(season)
        logger.info("Created season: Ligue1 %s.", season_name)

    session.commit()
    logger.info("Created fresh Ligue 1 league (id=%d) with %d seasons.",
                league.id, len(ligue1_cfg.seasons))


if __name__ == "__main__":
    migrate_league_one_to_ligue1()
