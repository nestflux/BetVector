"""
BetVector — Fetch Team Badges from Football-Data.org
=====================================================
Downloads team crest images from the free Football-Data.org API for all
6 active leagues and saves them to ``data/badges/{team_id}.png``.

This script replaces the API-Football-based badge fetcher for non-EPL
leagues, since API-Football's free tier cannot access 2025-26 data.
Football-Data.org covers all 6 leagues on its free tier and provides
crest PNG URLs for every team.

Usage::

    python scripts/fetch_badges_fdo.py

What it does:

1. For each active league, calls football-data.org
   ``GET /v4/competitions/{code}/teams`` to get crest URLs.
2. Matches API team names to local DB Team records by fuzzy name matching.
3. Downloads crest images and saves as ``data/badges/{team_id}.png``.
4. Skips teams that already have a badge file on disk (idempotent).

API budget: 6 requests (1 per league), well within the 10 req/min limit.
Rate limit: 6-second delay between API calls.

Master Plan refs: MP §5 Data Sources, MP §8 Design System
"""

from __future__ import annotations

import logging
import os
import sys
import time
from difflib import get_close_matches
from io import BytesIO
from pathlib import Path

import requests
from dotenv import load_dotenv

# Ensure the project root is on sys.path for imports
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# Load environment variables from .env
load_dotenv(_project_root / ".env")

from src.config import PROJECT_ROOT, config
from src.database.db import get_session
from src.database.models import Team, League

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Directory where badge images are cached
BADGES_DIR = PROJECT_ROOT / "data" / "badges"

# Football-Data.org API base URL and auth
FDO_BASE_URL = "https://api.football-data.org/v4"
FDO_KEY = os.getenv("FOOTBALL_DATA_ORG_KEY", "")

# Map our config football_data_code → football-data.org competition code
# Our codes come from Football-Data.co.uk CSV naming (E0, E1, SP1, etc.)
# Football-Data.org uses different competition codes (PL, ELC, PD, etc.)
FOOTBALL_DATA_CODE_TO_FDO: dict[str, str] = {
    "E0": "PL",       # English Premier League
    "E1": "ELC",      # English Championship
    "SP1": "PD",      # Spanish La Liga (Primera División)
    "F1": "FL1",      # French Ligue 1
    "D1": "BL1",      # German Bundesliga
    "I1": "SA",       # Italian Serie A
}

# ============================================================================
# Team Name Mapping: Football-Data.org API names → our canonical DB names
# ============================================================================
# Football-Data.org uses official club names (often with "FC" suffixes and
# full formal names).  Our canonical DB names come from Football-Data.co.uk
# CSV files (set during initial data load) and are typically shorter/informal.
#
# This mapping handles the known mismatches.  Any team NOT in this map will
# be matched via fuzzy string matching (difflib.get_close_matches).

FDO_TEAM_NAME_MAP: dict[str, str] = {
    # --- EPL ---
    "Arsenal FC": "Arsenal",
    "Aston Villa FC": "Aston Villa",
    "AFC Bournemouth": "AFC Bournemouth",
    "Brentford FC": "Brentford",
    "Brighton & Hove Albion FC": "Brighton & Hove Albion",
    "Chelsea FC": "Chelsea",
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Ipswich Town FC": "Ipswich Town",
    "Leicester City FC": "Leicester City",
    "Liverpool FC": "Liverpool",
    "Manchester City FC": "Manchester City",
    "Manchester United FC": "Manchester United",
    "Newcastle United FC": "Newcastle United",
    "Nottingham Forest FC": "Nottingham Forest",
    "Southampton FC": "Southampton",
    "Tottenham Hotspur FC": "Tottenham Hotspur",
    "West Ham United FC": "West Ham United",
    "Wolverhampton Wanderers FC": "Wolverhampton Wanderers",

    # --- Championship ---
    "Blackburn Rovers FC": "Blackburn",
    "Bristol City FC": "Bristol City",
    "Burnley FC": "Burnley",
    "Cardiff City FC": "Cardiff",
    "Coventry City FC": "Coventry",
    "Derby County FC": "Derby",
    "Hull City AFC": "Hull",
    "Leeds United FC": "Leeds",
    "Luton Town FC": "Luton",
    "Middlesbrough FC": "Middlesbrough",
    "Millwall FC": "Millwall",
    "Norwich City FC": "Norwich",
    "Oxford United FC": "Oxford",
    "Plymouth Argyle FC": "Plymouth",
    "Portsmouth FC": "Portsmouth",
    "Preston North End FC": "Preston",
    "Queens Park Rangers FC": "QPR",
    "Sheffield United FC": "Sheffield United",
    "Sheffield Wednesday FC": "Sheffield Weds",
    "Stoke City FC": "Stoke",
    "Sunderland AFC": "Sunderland",
    "Swansea City AFC": "Swansea",
    "Watford FC": "Watford",
    "West Bromwich Albion FC": "West Brom",

    # --- La Liga ---
    "Athletic Club": "Ath Bilbao",
    "Club Atlético de Madrid": "Ath Madrid",
    "FC Barcelona": "Barcelona",
    "Real Betis Balompié": "Betis",
    "RC Celta de Vigo": "Celta",
    "RCD Espanyol de Barcelona": "Espanol",
    "Getafe CF": "Getafe",
    "Girona FC": "Girona",
    "CD Leganés": "Leganes",
    "RCD Mallorca": "Mallorca",
    "CA Osasuna": "Osasuna",
    "Rayo Vallecano de Madrid": "Vallecano",
    "Real Madrid CF": "Real Madrid",
    "Real Sociedad de Fútbol": "Sociedad",
    "Sevilla FC": "Sevilla",
    "UD Almería": "Almeria",
    "UD Las Palmas": "Las Palmas",
    "Valencia CF": "Valencia",
    "Real Valladolid CF": "Valladolid",
    "Villarreal CF": "Villarreal",
    "Deportivo Alavés": "Alaves",
    "Granada CF": "Granada",
    "Cádiz CF": "Cadiz",
    "Elche CF": "Elche",
    "SD Eibar": "Eibar",
    "SD Huesca": "Huesca",
    "Levante UD": "Levante",
    "Real Oviedo": "Oviedo",

    # --- Bundesliga ---
    "FC Bayern München": "Bayern Munich",
    "FC Schalke 04": "Schalke 04",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "DSC Arminia Bielefeld": "Bielefeld",
    "1. FC Köln": "FC Koln",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    "VfB Stuttgart": "Stuttgart",
    "SC Freiburg": "Freiburg",
    "1. FC Union Berlin": "Union Berlin",
    "FC Augsburg": "Augsburg",
    "SV Werder Bremen": "Werder Bremen",
    "Hertha BSC": "Hertha",
    "Borussia Dortmund": "Dortmund",
    "Borussia Mönchengladbach": "M'gladbach",
    "RB Leipzig": "RB Leipzig",
    "1. FSV Mainz 05": "Mainz",
    "VfL Wolfsburg": "Wolfsburg",
    "Bayer 04 Leverkusen": "Leverkusen",
    "SpVgg Greuther Fürth": "Greuther Furth",
    "VfL Bochum 1848": "Bochum",
    "1. FC Heidenheim 1846": "Heidenheim",
    "SV Darmstadt 98": "Darmstadt",
    "Holstein Kiel": "Holstein Kiel",
    "FC St. Pauli 1910": "St Pauli",
    "Hamburger SV": "Hamburg",

    # --- Serie A ---
    "AC Milan": "Milan",
    "ACF Fiorentina": "Fiorentina",
    "AS Roma": "Roma",
    "Atalanta BC": "Atalanta",
    "Bologna FC 1909": "Bologna",
    "Cagliari Calcio": "Cagliari",
    "Empoli FC": "Empoli",
    "FC Internazionale Milano": "Inter",
    "Genoa CFC": "Genoa",
    "Hellas Verona FC": "Verona",
    "Juventus FC": "Juventus",
    "SS Lazio": "Lazio",
    "US Lecce": "Lecce",
    "AC Monza": "Monza",
    "SSC Napoli": "Napoli",
    "Parma Calcio 1913": "Parma",
    "US Salernitana 1919": "Salernitana",
    "US Sassuolo Calcio": "Sassuolo",
    "Spezia Calcio": "Spezia",
    "Torino FC": "Torino",
    "Udinese Calcio": "Udinese",
    "Unione Venezia": "Venezia",
    "UC Sampdoria": "Sampdoria",
    "US Cremonese": "Cremonese",
    "Frosinone Calcio": "Frosinone",
    "Como 1907": "Como",
    "FC Crotone": "Crotone",
    "Benevento Calcio": "Benevento",

    # --- Ligue 1 ---
    # Note: Our DB may not have Ligue 1 teams yet if backfill is still running.
    # These mappings are ready for when the teams appear.
    "Paris Saint-Germain FC": "Paris SG",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "AS Monaco FC": "Monaco",
    "Lille OSC": "Lille",
    "OGC Nice": "Nice",
    "RC Lens": "Lens",
    "Stade Rennais FC 1901": "Rennes",
    "RC Strasbourg Alsace": "Strasbourg",
    "FC Nantes": "Nantes",
    "Stade Brestois 29": "Brest",
    "Toulouse FC": "Toulouse",
    "Montpellier HSC": "Montpellier",
    "Stade de Reims": "Reims",
    "FC Lorient": "Lorient",
    "Clermont Foot 63": "Clermont Foot",
    "Le Havre AC": "Le Havre",
    "FC Metz": "Metz",
    "AJ Auxerre": "Auxerre",
    "Angers SCO": "Angers",
    "AS Saint-Étienne": "St Etienne",
}


def _match_api_team_to_db(
    api_name: str,
    db_teams_by_name: dict[str, Team],
    league_id: int,
) -> Team | None:
    """Match a football-data.org team name to a local DB Team record.

    Matching strategy (in order):
    1. Explicit name map: api_name → canonical DB name via FDO_TEAM_NAME_MAP
    2. Direct match: api_name exactly matches a DB team name
    3. Fuzzy match: closest match from DB team names (cutoff 0.5)
    """
    # Strategy 1: Explicit name map
    if api_name in FDO_TEAM_NAME_MAP:
        mapped_name = FDO_TEAM_NAME_MAP[api_name]
        if mapped_name in db_teams_by_name:
            return db_teams_by_name[mapped_name]

    # Strategy 2: Direct match
    if api_name in db_teams_by_name:
        return db_teams_by_name[api_name]

    # Strategy 3: Fuzzy match (lower threshold for international names)
    all_db_names = list(db_teams_by_name.keys())
    matches = get_close_matches(api_name, all_db_names, n=1, cutoff=0.5)
    if matches:
        logger.info(
            "Fuzzy matched '%s' → DB '%s'",
            api_name, matches[0],
        )
        return db_teams_by_name[matches[0]]

    return None


def _download_crest(url: str, dest: Path) -> bool:
    """Download a crest image from a URL to a local file.

    Handles both PNG and SVG crests from football-data.org.
    SVGs are saved as-is with .png extension (badge helper reads raw bytes).

    Returns True if download succeeded, False otherwise.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()

        if len(resp.content) < 50:
            logger.warning("Suspiciously small response (%d bytes) for %s", len(resp.content), url)
            return False

        dest.write_bytes(resp.content)
        return True
    except requests.RequestException as e:
        logger.error("Failed to download crest from %s: %s", url, e)
        return False


def fetch_all_badges() -> None:
    """Fetch and cache team crests for all active leagues from football-data.org.

    For each league, queries the /competitions/{code}/teams endpoint to get
    crest URLs, then matches teams by name to local DB records and downloads
    the crest image files.
    """
    if not FDO_KEY:
        logger.error("FOOTBALL_DATA_ORG_KEY not set in .env — cannot fetch crests")
        return

    BADGES_DIR.mkdir(parents=True, exist_ok=True)

    total_downloaded = 0
    total_skipped = 0
    total_unmatched = 0

    leagues_cfg = config.leagues
    if not leagues_cfg:
        logger.error("No leagues configured — check config/leagues.yaml")
        return

    for league_cfg in leagues_cfg:
        league_name = getattr(league_cfg, "short_name", "unknown")
        fd_code = getattr(league_cfg, "football_data_code", None)

        if fd_code is None:
            logger.info("Skipping %s — no football_data_code", league_name)
            continue

        fdo_comp_code = FOOTBALL_DATA_CODE_TO_FDO.get(fd_code)
        if fdo_comp_code is None:
            logger.warning(
                "No football-data.org competition code mapped for %s (fd_code=%s)",
                league_name, fd_code,
            )
            continue

        # Rate limit: 6 seconds between API calls (10 req/min limit)
        time.sleep(6)

        logger.info("Fetching teams for %s (competition=%s)...", league_name, fdo_comp_code)

        try:
            resp = requests.get(
                f"{FDO_BASE_URL}/competitions/{fdo_comp_code}/teams",
                headers={"X-Auth-Token": FDO_KEY},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Failed to fetch teams for %s: %s", league_name, e)
            continue

        data = resp.json()
        api_teams = data.get("teams", [])
        logger.info("Got %d teams from football-data.org for %s", len(api_teams), league_name)

        # Load DB teams for this league
        with get_session() as session:
            league_record = (
                session.query(League)
                .filter(League.short_name == league_name)
                .first()
            )
            if not league_record:
                logger.warning("League '%s' not found in DB — skipping", league_name)
                continue

            db_teams = (
                session.query(Team)
                .filter(Team.league_id == league_record.id)
                .all()
            )
            db_teams_by_name: dict[str, Team] = {t.name: t for t in db_teams}

            logger.info("DB has %d teams for %s", len(db_teams_by_name), league_name)

            for api_team in api_teams:
                api_name = api_team.get("name", "")
                crest_url = api_team.get("crest", "")

                if not crest_url:
                    logger.warning("No crest URL for %s — skipping", api_name)
                    continue

                # Match to DB team
                team = _match_api_team_to_db(api_name, db_teams_by_name, league_record.id)

                if not team:
                    logger.warning(
                        "❌ No DB match for '%s' in %s — skipping",
                        api_name, league_name,
                    )
                    total_unmatched += 1
                    continue

                # Check if badge already exists on disk
                badge_path = BADGES_DIR / f"{team.id}.png"
                if badge_path.exists():
                    total_skipped += 1
                    logger.debug(
                        "Badge already exists for %s (ID %d) — skipping",
                        team.name, team.id,
                    )
                    continue

                # Download the crest image
                # Rate limit: 2s between downloads (Rule 6)
                time.sleep(2)
                if _download_crest(crest_url, badge_path):
                    total_downloaded += 1
                    logger.info(
                        "✅ Downloaded badge for %s (ID %d) → %s",
                        team.name, team.id, badge_path.name,
                    )
                else:
                    logger.warning(
                        "Failed to download badge for %s (ID %d)",
                        team.name, team.id,
                    )

    # Also try to fetch badges for historical teams not in current API response
    # (e.g., relegated teams from past seasons). Check all teams without badges.
    _fetch_missing_via_search(total_downloaded, total_skipped, total_unmatched)

    logger.info(
        "Badge fetch complete: %d downloaded, %d already existed, %d unmatched",
        total_downloaded, total_skipped, total_unmatched,
    )


def _fetch_missing_via_search(
    downloaded_so_far: int,
    skipped_so_far: int,
    unmatched_so_far: int,
) -> None:
    """For teams still missing badges after the league-by-league fetch,
    try searching football-data.org by team name.

    This catches relegated/promoted teams that aren't in the current season's
    API response but exist in our DB from historical data.
    """
    with get_session() as session:
        all_teams = session.query(Team).all()
        missing = [
            t for t in all_teams
            if not (BADGES_DIR / f"{t.id}.png").exists()
        ]

    if not missing:
        logger.info("All teams have badges — no search needed")
        return

    logger.info(
        "Still %d teams without badges after league fetch — "
        "trying individual team search...",
        len(missing),
    )

    # For remaining teams, try the /teams?name= search endpoint
    fetched = 0
    for team in missing:
        time.sleep(6)  # Rate limit

        # Clean up the team name for search
        search_name = team.name.replace("'", "")

        try:
            resp = requests.get(
                f"{FDO_BASE_URL}/teams",
                headers={"X-Auth-Token": FDO_KEY},
                params={"name": search_name},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                api_teams = data.get("teams", [])
                if api_teams:
                    crest_url = api_teams[0].get("crest", "")
                    if crest_url:
                        badge_path = BADGES_DIR / f"{team.id}.png"
                        time.sleep(2)
                        if _download_crest(crest_url, badge_path):
                            fetched += 1
                            logger.info(
                                "✅ Search found badge for %s (ID %d)",
                                team.name, team.id,
                            )
                        continue

            logger.debug("No search result for '%s'", search_name)
        except requests.RequestException as e:
            logger.debug("Search failed for '%s': %s", search_name, e)

    logger.info("Search phase: %d additional badges fetched", fetched)


if __name__ == "__main__":
    fetch_all_badges()
