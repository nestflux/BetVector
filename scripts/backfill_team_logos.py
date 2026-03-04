"""
BetVector — Backfill Team Logos (E28-01)
========================================
One-time script to fetch team crest images from API-Football and cache
them locally in ``data/badges/{team_id}.png``.

Usage::

    source venv/bin/activate
    python scripts/backfill_team_logos.py

What it does:

1. For each active league in ``config/leagues.yaml``, calls the
   API-Football ``/teams`` endpoint to get logo URLs.
2. Matches API-Football teams to local Team records by name
   (using the ``API_FOOTBALL_EPL_TEAM_MAP`` reverse lookup).
3. Sets ``Team.api_football_id`` and ``Team.logo_url`` in the database.
4. Downloads each logo image to ``data/badges/{team_id}.png``.

Idempotent:  Re-running skips teams that already have a cached badge file
and a populated ``logo_url`` in the database.

API budget: ~1 request per active league (typically 1-3 leagues).

Master Plan refs: MP §5 Data Sources (API-Football)
"""

from __future__ import annotations

import logging
import sys
import time
from difflib import get_close_matches
from pathlib import Path

import requests
from dotenv import load_dotenv

# Ensure the project root is on sys.path for imports
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# Load environment variables from .env (API_FOOTBALL_KEY, etc.)
load_dotenv(_project_root / ".env")

from src.config import PROJECT_ROOT, config
from src.database.db import get_session
from src.database.models import Team
from src.scrapers.api_football import API_FOOTBALL_EPL_TEAM_MAP, APIFootballScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Directory where badge images are cached
BADGES_DIR = PROJECT_ROOT / "data" / "badges"


def _build_name_lookup() -> dict[str, str]:
    """Build a lookup: lowered canonical name → full DB team name.

    ``API_FOOTBALL_EPL_TEAM_MAP`` maps *various name forms* (keys) →
    *canonical short names* (values).  For example::

        "AFC Bournemouth": "Bournemouth"
        "Wolverhampton Wanderers": "Wolves"
        "Wolves": "Wolves"
        "Newcastle United": "Newcastle"
        "Newcastle": "Newcastle"

    The API-Football ``/teams`` endpoint returns short names like "Wolves",
    "Brighton", "Newcastle".  These are the *values* in the map.  We need
    to go the other direction: given a short name, find the longest key
    that maps to it — that longest key is typically the full official name
    stored in our ``teams`` table (e.g. "Wolverhampton Wanderers").

    Returns a dict keyed by lowered canonical value, with the longest
    corresponding map key as the value.
    """
    # Group all keys by their canonical value
    canonical_to_keys: dict[str, list[str]] = {}
    for name_form, canonical in API_FOOTBALL_EPL_TEAM_MAP.items():
        canonical_lower = canonical.lower()
        canonical_to_keys.setdefault(canonical_lower, []).append(name_form)

    # For each canonical, pick the longest key (full official DB name)
    lookup: dict[str, str] = {}
    for canonical_lower, keys in canonical_to_keys.items():
        # Longest key is typically the full name in our DB
        longest_key = max(keys, key=len)
        lookup[canonical_lower] = longest_key
        # Also add each key as a lookup entry (for direct API name matching)
        for key in keys:
            lookup[key.lower()] = longest_key

    return lookup


def _match_api_team_to_db(
    af_name: str,
    db_teams_by_name: dict[str, "Team"],
    name_map: dict[str, str],
) -> "Team | None":
    """Match an API-Football team name to a local DB Team record.

    Matching strategy (in order):
    1. Direct match: ``af_name`` exactly matches a key in our DB teams dict
    2. Name map: ``af_name`` is a known key in ``API_FOOTBALL_EPL_TEAM_MAP``,
       which maps to a DB team name (e.g. "Bournemouth" → "AFC Bournemouth")
    3. Fuzzy match: closest match from DB team names (cutoff 0.6)
    """
    # Strategy 1: Direct match by exact DB name
    if af_name in db_teams_by_name:
        return db_teams_by_name[af_name]

    # Strategy 2: Name map lookup (API-Football name → DB team name)
    af_lower = af_name.lower()
    if af_lower in name_map:
        db_name = name_map[af_lower]
        if db_name in db_teams_by_name:
            return db_teams_by_name[db_name]

    # Strategy 3: Fuzzy match against all DB team names
    all_db_names = list(db_teams_by_name.keys())
    matches = get_close_matches(af_name, all_db_names, n=1, cutoff=0.6)
    if matches:
        logger.info(
            "Fuzzy matched API-Football '%s' → DB '%s'",
            af_name, matches[0],
        )
        return db_teams_by_name[matches[0]]

    return None


def download_badge(url: str, dest: Path) -> bool:
    """Download a badge image from a URL to a local file.

    Parameters
    ----------
    url : str
        The image URL (typically a PNG on media.api-sports.io).
    dest : Path
        Local file path to save the image.

    Returns
    -------
    bool
        True if the download succeeded, False otherwise.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()

        # Verify we got image content (not an HTML error page)
        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type and len(resp.content) < 100:
            logger.warning(
                "Unexpected content type %s for %s — skipping",
                content_type, url,
            )
            return False

        dest.write_bytes(resp.content)
        return True
    except requests.RequestException as e:
        logger.error("Failed to download badge from %s: %s", url, e)
        return False


def backfill_logos() -> None:
    """Fetch and cache team logos for all active leagues.

    This matches API-Football teams to local DB teams by name (using the
    ``API_FOOTBALL_EPL_TEAM_MAP`` reverse lookup), then sets both
    ``api_football_id`` and ``logo_url`` on the Team record.  Badge images
    are downloaded to ``data/badges/{team_id}.png``.
    """
    # Ensure the badges directory exists
    BADGES_DIR.mkdir(parents=True, exist_ok=True)

    scraper = APIFootballScraper()
    name_map = _build_name_lookup()

    # Get active leagues from config
    leagues = config.leagues
    if not leagues:
        logger.error("No leagues configured — check config/leagues.yaml")
        return

    total_updated = 0
    total_downloaded = 0
    total_id_set = 0

    for league_cfg in leagues:
        league_name = getattr(league_cfg, "short_name", "unknown")
        api_id = getattr(league_cfg, "api_football_id", None)

        if api_id is None:
            logger.info("Skipping %s — no api_football_id configured", league_name)
            continue

        # Get the current (latest) season from the seasons list.
        # API-Football free tier only covers 2022-2024, so we try
        # the current season first, then fall back to the most recent
        # season within free-tier range.  Team logos rarely change
        # between seasons, so an older season is fine for badge images.
        seasons_list = getattr(league_cfg, "seasons", [])
        if not seasons_list:
            logger.warning("No seasons configured for %s — skipping", league_name)
            continue

        # Try current season, then fallback to "2024-25" (within free tier)
        seasons_to_try = [seasons_list[-1]]
        if "2024-25" in seasons_list and "2024-25" != seasons_list[-1]:
            seasons_to_try.append("2024-25")
        elif "2023-24" in seasons_list:
            seasons_to_try.append("2023-24")

        logo_data = []
        for season_attempt in seasons_to_try:
            logo_data = scraper.fetch_team_logos(league_cfg, season_attempt)
            if logo_data:
                logger.info(
                    "Got logo data using season %s for %s",
                    season_attempt, league_name,
                )
                break
            logger.info(
                "No data for season %s, trying next fallback...",
                season_attempt,
            )

        if not logo_data:
            logger.warning("No logo data returned for %s", league_name)
            continue

        logger.info(
            "Processing %d teams from API-Football for %s",
            len(logo_data), league_name,
        )

        # Match to local teams by name and update
        with get_session() as session:
            # Load all DB teams into a name → Team dict for fast lookup
            all_teams = session.query(Team).all()
            db_teams_by_name: dict[str, Team] = {t.name: t for t in all_teams}

            for entry in logo_data:
                af_id = entry["api_football_id"]
                logo_url = entry["logo_url"]
                af_name = entry["name"]

                # Match by name (not by api_football_id, which may not be set yet)
                team = _match_api_team_to_db(af_name, db_teams_by_name, name_map)

                if not team:
                    logger.warning(
                        "No DB match for API-Football team '%s' (ID %d) — skipping",
                        af_name, af_id,
                    )
                    continue

                # Set api_football_id if not already set (first-time backfill)
                if team.api_football_id != af_id:
                    team.api_football_id = af_id
                    total_id_set += 1
                    logger.info(
                        "Set api_football_id=%d for %s (DB ID %d)",
                        af_id, team.name, team.id,
                    )

                # Update logo_url in database (idempotent)
                if team.logo_url != logo_url:
                    team.logo_url = logo_url
                    total_updated += 1
                    logger.info(
                        "Updated logo_url for %s (ID %d)", team.name, team.id,
                    )

                # Download badge image if not already cached
                badge_path = BADGES_DIR / f"{team.id}.png"
                if not badge_path.exists():
                    # Rate limit: 2s between downloads (Rule 6 — min 2s per domain)
                    time.sleep(2.0)
                    if download_badge(logo_url, badge_path):
                        total_downloaded += 1
                        logger.info(
                            "Downloaded badge for %s → %s",
                            team.name, badge_path.name,
                        )
                    else:
                        logger.warning(
                            "Failed to download badge for %s", team.name,
                        )
                else:
                    logger.debug(
                        "Badge already cached for %s (%s)",
                        team.name, badge_path.name,
                    )

            session.commit()

    logger.info(
        "Backfill complete: %d api_football_ids set, %d logo URLs updated, "
        "%d badges downloaded",
        total_id_set, total_updated, total_downloaded,
    )


if __name__ == "__main__":
    backfill_logos()
