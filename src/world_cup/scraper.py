"""
BetVector World Cup 2026 — Data Scraper (WC-02-01, WC-02-02)
==============================================================
Fetches WC match odds from The Odds API and results/fixtures from
the scores endpoint. Maps team names between API and our database.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml
from sqlalchemy import select

from src.config import PROJECT_ROOT
from src.database.db import get_session
from src.world_cup.models import WCMatch, WCOdds, WCTeam

logger = logging.getLogger(__name__)

API_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "soccer_fifa_world_cup"
SPORT_KEY_WINNER = "soccer_fifa_world_cup_winner"
DATA_DIR = PROJECT_ROOT / "data" / "raw"

# Load name map from config
_CONFIG_PATH = PROJECT_ROOT / "config" / "worldcup_2026.yaml"
_NAME_MAP: dict[str, str] | None = None


def _get_api_key() -> str:
    key = os.environ.get("THE_ODDS_API_KEY", "")
    if not key:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        key = os.environ.get("THE_ODDS_API_KEY", "")
    return key.strip().strip('"').strip("'")


def _get_name_map() -> dict[str, str]:
    global _NAME_MAP
    if _NAME_MAP is None:
        with open(_CONFIG_PATH) as f:
            data = yaml.safe_load(f)
        _NAME_MAP = data.get("odds_api_name_map", {})
        # Also build reverse map from DB names to DB names (identity)
        for group_teams in data.get("groups", {}).values():
            for t in group_teams:
                _NAME_MAP[t["name"]] = t["name"]
    return _NAME_MAP


def _normalize_team_name(api_name: str) -> str:
    name_map = _get_name_map()
    return name_map.get(api_name, api_name)


def _get_team_by_name(session, name: str) -> WCTeam | None:
    normalized = _normalize_team_name(name)
    return session.execute(
        select(WCTeam).where(WCTeam.name == normalized)
    ).scalar_one_or_none()


def _load_venue_data() -> dict[str, dict]:
    venue_path = PROJECT_ROOT / "config" / "worldcup_venues.yaml"
    with open(venue_path) as f:
        data = yaml.safe_load(f)
    return {v["city"]: v for v in data["venues"]}


# ============================================================================
# WC-02-01: Odds Scraper
# ============================================================================

def scrape_wc_odds(
    markets: str = "h2h,spreads,totals",
    regions: str = "us,uk,eu,au",
) -> int:
    api_key = _get_api_key()
    if not api_key:
        logger.error("THE_ODDS_API_KEY not set")
        return 0

    url = f"{API_BASE}/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
    }

    logger.info("Fetching WC odds: markets=%s, regions=%s", markets, regions)
    resp = requests.get(url, params=params, timeout=30)
    remaining = resp.headers.get("x-requests-remaining", "?")
    logger.info("Odds API requests remaining: %s", remaining)

    if resp.status_code != 200:
        logger.error("Odds API error %d: %s", resp.status_code, resp.text[:300])
        return 0

    events = resp.json()

    # Save raw JSON
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    raw_path = DATA_DIR / f"wc_odds_{today}.json"
    with open(raw_path, "w") as f:
        json.dump(events, f, indent=2)
    logger.info("Saved raw odds to %s", raw_path)

    return _load_odds_to_db(events)


def _load_odds_to_db(events: list[dict[str, Any]]) -> int:
    loaded = 0

    with get_session() as session:
        for event in events:
            home_name = event.get("home_team", "")
            away_name = event.get("away_team", "")
            home_team = _get_team_by_name(session, home_name)
            away_team = _get_team_by_name(session, away_name)

            if not home_team or not away_team:
                logger.warning(
                    "Team not found: %s vs %s (skipping odds)", home_name, away_name
                )
                continue

            match = session.execute(
                select(WCMatch).where(
                    WCMatch.home_team_id == home_team.id,
                    WCMatch.away_team_id == away_team.id,
                )
            ).scalar_one_or_none()

            if not match:
                logger.debug(
                    "No match record for %s vs %s (skipping odds)", home_name, away_name
                )
                continue

            for bookmaker in event.get("bookmakers", []):
                bookie_name = bookmaker.get("title", bookmaker.get("key", "unknown"))
                for market in bookmaker.get("markets", []):
                    market_type = market.get("key", "")
                    for outcome in market.get("outcomes", []):
                        selection = outcome.get("name", "")
                        price = outcome.get("price")
                        point = outcome.get("point")
                        if not price or price <= 1.0:
                            continue

                        implied_prob = round(1.0 / price, 4) if price > 0 else None

                        existing = session.execute(
                            select(WCOdds).where(
                                WCOdds.match_id == match.id,
                                WCOdds.bookmaker == bookie_name,
                                WCOdds.market_type == market_type,
                                WCOdds.selection == selection,
                            )
                        ).scalar_one_or_none()

                        if existing:
                            existing.odds_decimal = price
                            existing.implied_prob = implied_prob
                            existing.point = point
                            existing.captured_at = datetime.utcnow().isoformat()
                        else:
                            odds = WCOdds(
                                match_id=match.id,
                                bookmaker=bookie_name,
                                market_type=market_type,
                                selection=selection,
                                odds_decimal=price,
                                opening_odds=price,  # frozen first-seen price (WC-09-03)
                                implied_prob=implied_prob,
                                point=point,
                                source="odds_api",
                            )
                            session.add(odds)
                        loaded += 1

    logger.info("Loaded %d WC odds entries", loaded)
    return loaded


# ============================================================================
# WC-02-02: Results & Fixtures Scraper
# ============================================================================

def scrape_wc_results() -> dict[str, int]:
    api_key = _get_api_key()
    if not api_key:
        logger.error("THE_ODDS_API_KEY not set")
        return {"matches_updated": 0, "matches_created": 0}

    url = f"{API_BASE}/sports/{SPORT_KEY}/scores"
    params = {"apiKey": api_key, "daysFrom": 3}

    logger.info("Fetching WC scores and fixtures...")
    resp = requests.get(url, params=params, timeout=30)
    remaining = resp.headers.get("x-requests-remaining", "?")
    logger.info("Odds API requests remaining: %s", remaining)

    if resp.status_code != 200:
        logger.error("Scores API error %d: %s", resp.status_code, resp.text[:300])
        return {"matches_updated": 0, "matches_created": 0}

    events = resp.json()
    venues = _load_venue_data()

    updated = 0
    created = 0

    with get_session() as session:
        for event in events:
            home_name = event.get("home_team", "")
            away_name = event.get("away_team", "")
            home_team = _get_team_by_name(session, home_name)
            away_team = _get_team_by_name(session, away_name)

            if not home_team or not away_team:
                logger.warning("Team not found: %s vs %s", home_name, away_name)
                continue

            commence = event.get("commence_time", "")
            match_date = commence[:10] if commence else ""
            kickoff = commence[11:16] if len(commence) >= 16 else None

            match = session.execute(
                select(WCMatch).where(
                    WCMatch.home_team_id == home_team.id,
                    WCMatch.away_team_id == away_team.id,
                )
            ).scalar_one_or_none()

            completed = event.get("completed", False)
            scores = event.get("scores")

            if match:
                match.date = match_date
                match.kickoff_time = kickoff
                if completed and scores:
                    for s in scores:
                        if s["name"] == home_name:
                            match.home_goals = int(s["score"])
                        elif s["name"] == away_name:
                            match.away_goals = int(s["score"])
                    match.status = "finished"
                elif not completed:
                    if match.status != "finished":
                        match.status = "scheduled"
                updated += 1
            else:
                # Determine group from team data
                group = home_team.group_letter if home_team.group_letter == away_team.group_letter else None
                stage = "group" if group else "knockout"

                new_match = WCMatch(
                    group_letter=group,
                    stage=stage,
                    date=match_date,
                    kickoff_time=kickoff,
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    status="finished" if completed else "scheduled",
                )

                if completed and scores:
                    for s in scores:
                        if s["name"] == home_name:
                            new_match.home_goals = int(s["score"])
                        elif s["name"] == away_name:
                            new_match.away_goals = int(s["score"])

                session.add(new_match)
                created += 1

    logger.info("WC results: %d updated, %d created", updated, created)
    return {"matches_updated": updated, "matches_created": created}


def compute_group_standings() -> dict[str, list[dict]]:
    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()
        matches = session.execute(
            select(WCMatch).where(
                WCMatch.stage == "group",
                WCMatch.status == "finished",
            )
        ).scalars().all()

        team_map = {t.id: t for t in teams}
        standings: dict[str, dict[int, dict]] = {}

        for t in teams:
            if t.group_letter not in standings:
                standings[t.group_letter] = {}
            standings[t.group_letter][t.id] = {
                "name": t.name,
                "fifa_code": t.fifa_code,
                "played": 0, "won": 0, "drawn": 0, "lost": 0,
                "gf": 0, "ga": 0, "gd": 0, "points": 0,
            }

        for m in matches:
            g = m.group_letter
            if not g or g not in standings:
                continue
            hid, aid = m.home_team_id, m.away_team_id
            hg, ag = m.home_goals or 0, m.away_goals or 0

            for tid, goals_for, goals_against in [(hid, hg, ag), (aid, ag, hg)]:
                if tid not in standings[g]:
                    continue
                s = standings[g][tid]
                s["played"] += 1
                s["gf"] += goals_for
                s["ga"] += goals_against
                s["gd"] = s["gf"] - s["ga"]
                if goals_for > goals_against:
                    s["won"] += 1
                    s["points"] += 3
                elif goals_for == goals_against:
                    s["drawn"] += 1
                    s["points"] += 1
                else:
                    s["lost"] += 1

        result = {}
        for group in sorted(standings):
            group_teams = list(standings[group].values())
            group_teams.sort(key=lambda x: (-x["points"], -x["gd"], -x["gf"]))
            result[group] = group_teams

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("=== Scraping WC results ===")
    r = scrape_wc_results()
    print(f"Results: {r}")

    print("\n=== Group standings ===")
    standings = compute_group_standings()
    for group, teams in standings.items():
        print(f"\nGroup {group}:")
        for t in teams:
            print(f"  {t['fifa_code']:4s} {t['name']:25s} P:{t['played']} W:{t['won']} D:{t['drawn']} L:{t['lost']} GD:{t['gd']:+d} Pts:{t['points']}")
