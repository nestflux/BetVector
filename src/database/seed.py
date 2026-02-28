"""
BetVector Database Seeder
==========================
Seeds the database with initial configuration data:
  - Owner user (from config defaults)
  - EPL league (from config/leagues.yaml)
  - Season entries for all configured seasons

**Idempotent** — safe to run multiple times.  Uses INSERT OR IGNORE
semantics so duplicate records are silently skipped.

Usage::

    # As a script
    python -m src.database.seed

    # From code
    from src.database.seed import seed_all
    seed_all()
"""

from __future__ import annotations

import logging

from src.config import config
from src.database.db import get_session, init_db
from src.database.models import League, Season, User

logger = logging.getLogger(__name__)


def seed_owner() -> None:
    """Create the owner user if they don't already exist.

    Uses config defaults for bankroll, staking method, and edge threshold.
    The owner is the primary user — they receive emails, place bets, and
    see the full dashboard.
    """
    with get_session() as session:
        existing = session.query(User).filter_by(role="owner").first()
        if existing:
            logger.info("Owner user already exists (id=%d), skipping.", existing.id)
            return

        owner = User(
            name="Owner",
            role="owner",
            starting_bankroll=config.settings.starting_bankroll,
            current_bankroll=config.settings.starting_bankroll,
            staking_method=config.settings.staking_method,
            stake_percentage=config.settings.stake_percentage,
            kelly_fraction=config.settings.kelly_fraction,
            edge_threshold=config.settings.edge_threshold,
            is_active=1,
        )
        session.add(owner)
        logger.info("Created owner user with bankroll=%.2f.", owner.starting_bankroll)


def seed_leagues() -> None:
    """Create league entries from config/leagues.yaml.

    Only seeds leagues marked as ``is_active: true`` in config.
    Skips leagues that already exist (matched by short_name).
    """
    for league_cfg in config.get_active_leagues():
        with get_session() as session:
            existing = session.query(League).filter_by(
                short_name=league_cfg.short_name,
            ).first()
            if existing:
                logger.info(
                    "League '%s' already exists (id=%d), skipping.",
                    league_cfg.short_name, existing.id,
                )
                continue

            league = League(
                name=league_cfg.name,
                short_name=league_cfg.short_name,
                country=league_cfg.country,
                football_data_code=league_cfg.football_data_code,
                fbref_league_id=league_cfg.fbref_league_id,
                api_football_id=league_cfg.api_football_id,
                is_active=1 if league_cfg.is_active else 0,
            )
            session.add(league)
            logger.info("Created league: %s (%s).", league.name, league.short_name)


def seed_seasons() -> None:
    """Create season entries for every league × season in config.

    Skips season entries that already exist (matched by league_id + season).
    """
    for league_cfg in config.get_active_leagues():
        with get_session() as session:
            league = session.query(League).filter_by(
                short_name=league_cfg.short_name,
            ).first()
            if not league:
                logger.warning(
                    "League '%s' not found in DB — run seed_leagues() first.",
                    league_cfg.short_name,
                )
                continue

            for season_name in league_cfg.seasons:
                existing = session.query(Season).filter_by(
                    league_id=league.id,
                    season=season_name,
                ).first()
                if existing:
                    logger.info(
                        "Season %s for %s already exists, skipping.",
                        season_name, league_cfg.short_name,
                    )
                    continue

                season = Season(
                    league_id=league.id,
                    season=season_name,
                    is_loaded=0,
                )
                session.add(season)
                logger.info(
                    "Created season: %s %s.",
                    league_cfg.short_name, season_name,
                )


def seed_all() -> None:
    """Run all seeders in order.  Safe to call multiple times."""
    init_db()
    seed_owner()
    seed_leagues()
    seed_seasons()
    logger.info("Seeding complete.")


# Allow running as: python -m src.database.seed
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    seed_all()
