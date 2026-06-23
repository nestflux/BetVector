"""
BetVector World Cup 2026 — Squad Data Collector (WC-02-05)
==========================================================
Load squad-level features from the seed YAML file and compute
dark_horse_score for all 48 WC teams.

Primary source: config/wc_squads_2026.yaml (manually curated from
Transfermarkt national team pages). This is faster and more reliable
than scraping 48 national team pages mid-tournament.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from sqlalchemy import select

from src.database.db import get_session
from src.world_cup.models import WCTeam

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
SQUAD_FILE = CONFIG_DIR / "wc_squads_2026.yaml"

# Columns that map directly from YAML to WCTeam, with expected types
SQUAD_FIELDS = {
    "squad_market_value": (int, float),
    "avg_squad_age": (int, float),
    "players_in_top5_leagues": (int,),
    "cl_players": (int,),
    "avg_caps": (int, float),
    "squad_mv_gini": (int, float),
    "manager_name": (str,),
    "manager_tenure_months": (int,),
}


def fetch_squad_data() -> dict[str, dict]:
    """
    Load squad data from the seed YAML file for all 48 WC teams.
    Stores results in wc_teams table and computes dark_horse_score.

    Returns dict of {fifa_code: {field: value, ...}}.
    """
    if not SQUAD_FILE.exists():
        logger.error("Squad seed file not found: %s", SQUAD_FILE)
        return {}

    try:
        with open(SQUAD_FILE) as f:
            config = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        logger.error("Failed to read squad seed file: %s", e)
        return {}

    squads = config.get("squads", {})
    if not squads:
        logger.warning("No squad data found in %s", SQUAD_FILE)
        return {}

    logger.info("Loaded squad data for %d teams from YAML", len(squads))

    _store_squad_data(squads)
    _compute_dark_horse_scores()

    return squads


def _store_squad_data(squads: dict[str, dict]) -> None:
    """Write squad data from YAML into the wc_teams table."""
    try:
        with get_session() as session:
            teams = session.execute(select(WCTeam)).scalars().all()
            team_map = {t.fifa_code: t for t in teams}

            updated = 0
            missing = []
            for fifa_code, data in squads.items():
                team = team_map.get(fifa_code)
                if not team:
                    missing.append(fifa_code)
                    continue

                for field, expected_types in SQUAD_FIELDS.items():
                    value = data.get(field)
                    if value is not None:
                        if not isinstance(value, expected_types):
                            logger.warning(
                                "%s.%s: expected %s, got %s — skipping",
                                fifa_code, field, expected_types, type(value).__name__,
                            )
                            continue
                        setattr(team, field, value)
                updated += 1

            session.commit()

            if missing:
                logger.warning("No WCTeam found for FIFA codes: %s", missing)
            logger.info("Stored squad data for %d teams", updated)
    except Exception as e:
        logger.error("Failed to store squad data in DB: %s", e)


def _compute_dark_horse_scores() -> None:
    """
    Compute dark_horse_score = mv_rank - elo_rank.

    Positive = team's Elo ranking is better than their market value ranking,
    meaning they're stronger than the money suggests. Bookmakers weight squad
    value heavily, so a high dark_horse_score flags teams the market likely
    undervalues — a potential edge for value betting.
    Example: Morocco might have Elo rank 4 but MV rank 15 → score +11.
    """
    try:
        with get_session() as session:
            teams = session.execute(select(WCTeam)).scalars().all()
            n_teams = len(teams)

            by_elo = sorted(teams, key=lambda t: t.elo_rating or 0, reverse=True)
            elo_rank = {t.fifa_code: i + 1 for i, t in enumerate(by_elo)}

            by_mv = sorted(teams, key=lambda t: t.squad_market_value or 0, reverse=True)
            mv_rank = {t.fifa_code: i + 1 for i, t in enumerate(by_mv)}

            computed = 0
            for team in teams:
                er = elo_rank.get(team.fifa_code, n_teams)
                mr = mv_rank.get(team.fifa_code, n_teams)
                team.dark_horse_score = float(mr - er)
                computed += 1

            session.commit()
            logger.info("Computed dark_horse_score for %d teams", computed)

            # Log top dark horses
            dark_horses = sorted(teams, key=lambda t: t.dark_horse_score or 0, reverse=True)
            logger.info("Top dark horses:")
            for t in dark_horses[:5]:
                logger.info(
                    "  %s: score=%.0f (Elo rank %d, MV rank %d)",
                    t.name, t.dark_horse_score,
                    elo_rank[t.fifa_code], mv_rank[t.fifa_code],
                )
    except Exception as e:
        logger.error("Failed to compute dark_horse_scores: %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()

    print("=== Loading Squad Data ===")
    data = fetch_squad_data()

    print(f"\nLoaded {len(data)} squads")

    print("\n=== Squad Summary ===")
    with get_session() as session:
        teams = session.execute(
            select(WCTeam).order_by(WCTeam.squad_market_value.desc())
        ).scalars().all()

        nulls = {"squad_market_value": 0, "avg_squad_age": 0, "players_in_top5_leagues": 0,
                 "cl_players": 0, "manager_tenure_months": 0, "dark_horse_score": 0}
        for t in teams:
            for field in nulls:
                if getattr(t, field) is None:
                    nulls[field] += 1

        total = len(teams)
        for field, count in nulls.items():
            print(f"  {field}: {total - count}/{total} populated ({count} NULL)")

        print("\n=== Top 10 by Market Value ===")
        for t in teams[:10]:
            mv = t.squad_market_value or 0
            age = t.avg_squad_age or 0
            t5 = t.players_in_top5_leagues or 0
            cl = t.cl_players or 0
            dh = t.dark_horse_score or 0
            print(f"  {t.name:<25s} MV=€{mv:>7.0f}M Age={age:.1f} Top5={t5:>2d} CL={cl:>2d} DH={dh:>+5.0f}")

        print("\n=== Top 5 Dark Horses ===")
        dark = sorted(teams, key=lambda t: t.dark_horse_score or 0, reverse=True)
        for t in dark[:5]:
            dh = t.dark_horse_score or 0
            elo = t.elo_rating or 0
            mv = t.squad_market_value or 0
            print(f"  {t.name:<25s} DH={dh:>+5.0f} (Elo={elo:.0f}, MV=€{mv:.0f}M)")
