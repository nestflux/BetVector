"""
BetVector World Cup 2026 — Team Seeding (WC-01-02)
====================================================
Populate wc_teams from config/worldcup_2026.yaml. Idempotent — safe to
re-run; updates existing rows on conflict (matched by fifa_code).
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


def seed_teams() -> int:
    config_path = CONFIG_DIR / "worldcup_2026.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)

    groups = data["groups"]
    count = 0

    with get_session() as session:
        for group_letter, teams in groups.items():
            for team_data in teams:
                existing = session.execute(
                    select(WCTeam).where(WCTeam.fifa_code == team_data["fifa_code"])
                ).scalar_one_or_none()

                if existing:
                    existing.name = team_data["name"]
                    existing.confederation = team_data["confederation"]
                    existing.group_letter = group_letter
                    existing.is_host = 1 if team_data.get("is_host") else 0
                    existing.wc_appearances = team_data.get("wc_appearances", 0)
                    existing.best_wc_finish = team_data.get("best_wc_finish")
                    existing.home_capital_lat = team_data.get("capital_lat")
                    existing.home_capital_lon = team_data.get("capital_lon")
                    existing.home_avg_june_temp_c = team_data.get("avg_june_temp_c")
                    logger.debug("Updated team: %s (%s)", existing.name, group_letter)
                else:
                    team = WCTeam(
                        name=team_data["name"],
                        fifa_code=team_data["fifa_code"],
                        confederation=team_data["confederation"],
                        group_letter=group_letter,
                        is_host=1 if team_data.get("is_host") else 0,
                        wc_appearances=team_data.get("wc_appearances", 0),
                        best_wc_finish=team_data.get("best_wc_finish"),
                        home_capital_lat=team_data.get("capital_lat"),
                        home_capital_lon=team_data.get("capital_lon"),
                        home_avg_june_temp_c=team_data.get("avg_june_temp_c"),
                    )
                    session.add(team)
                    logger.debug("Inserted team: %s (%s)", team.name, group_letter)
                count += 1

    logger.info("Seeded %d WC teams across %d groups", count, len(groups))
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = seed_teams()
    print(f"Seeded {n} teams.")
