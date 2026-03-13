"""
BetVector — Soccerdata API Scraper (E39-02)
============================================
Scrapes injury/sidelined data from the Soccerdata API (soccerdataapi.com).

This is the **primary live injury source** for BetVector, replacing the
API-Football free tier (which blocks current-season injury data).

**Why injuries matter for betting models:**
  A team's strength depends heavily on who is available to play.  Missing
  a star striker (e.g., Haaland) vs missing a backup goalkeeper produces
  very different expected goal outputs.  The ``impact_rating`` field,
  auto-computed from the player's market-value percentile within their
  squad (via PlayerValue table), quantifies this difference on a 0.0–1.0
  scale.

**Data flow:**
  Soccerdata API → scrape_injuries() → DataFrame
  → load_soccerdata_injuries() → InjuryFlag table
  → calculate_injury_features() → injury_impact + key_player_out features
  → Poisson/XGBoost models

**API details:**
  - Base URL: https://api.soccerdataapi.com
  - Auth: ``auth_token`` query parameter (SOCCERDATA_API_KEY env var)
  - Rate limit: 75 requests/day (free tier)
  - Date format: DD/MM/YYYY
  - League IDs configured in ``config/leagues.yaml`` → ``soccerdata_league_id``

Master Plan refs: MP §5 (Data Sources), MP §7 (Scraper Interface)
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Team Name Mapping — Soccerdata API → Canonical DB Names
# ============================================================================
# The Soccerdata API uses its own team names which may differ from our
# canonical database names (sourced from Football-Data.co.uk CSVs).
# This map resolves the differences.  If a team isn't in this map,
# we try an exact match first, then log a warning for manual addition.

SOCCERDATA_TEAM_MAP: Dict[str, str] = {
    # --- EPL (league_id=228) ---
    "Manchester United": "Man United",
    "Manchester City": "Man City",
    "Tottenham Hotspur": "Tottenham",
    "Newcastle United": "Newcastle",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    "Leicester City": "Leicester",
    "Brighton and Hove Albion": "Brighton",
    "Nottingham Forest": "Nott'm Forest",
    "AFC Bournemouth": "Bournemouth",
    "Ipswich Town": "Ipswich",

    # --- Championship (league_id=229) ---
    "Sheffield United": "Sheffield United",
    "West Bromwich Albion": "West Brom",
    "Queens Park Rangers": "QPR",
    "Stoke City": "Stoke",
    "Swansea City": "Swansea",
    "Hull City": "Hull",
    "Cardiff City": "Cardiff",
    "Coventry City": "Coventry",
    "Bristol City": "Bristol City",
    "Norwich City": "Norwich",
    "Preston North End": "Preston",
    "Plymouth Argyle": "Plymouth",
    "Derby County": "Derby",
    "Oxford United": "Oxford",
    "Blackburn Rovers": "Blackburn",
    "Portsmouth FC": "Portsmouth",

    # --- La Liga (league_id=297) ---
    "Atletico Madrid": "Ath Madrid",
    "Athletic Bilbao": "Ath Bilbao",
    "Real Sociedad": "Real Sociedad",
    "Real Betis": "Betis",
    "Celta Vigo": "Celta",
    "Real Valladolid": "Valladolid",
    "Deportivo Alaves": "Alaves",
    "RCD Mallorca": "Mallorca",
    "Rayo Vallecano": "Vallecano",
    "CD Leganes": "Leganes",
    "UD Las Palmas": "Las Palmas",
    "RC Celta de Vigo": "Celta",

    # --- Ligue 1 (league_id=235) ---
    "Paris Saint-Germain": "Paris SG",
    "Paris Saint Germain": "Paris SG",
    "Olympique Marseille": "Marseille",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "Olympique Lyon": "Lyon",
    "AS Monaco": "Monaco",
    "AS Saint-Etienne": "St Etienne",
    "AS Saint Etienne": "St Etienne",
    "Stade Rennais": "Rennes",
    "Stade de Reims": "Reims",
    "RC Strasbourg Alsace": "Strasbourg",
    "RC Lens": "Lens",
    "OGC Nice": "Nice",
    "FC Nantes": "Nantes",
    "Le Havre AC": "Le Havre",
    "AJ Auxerre": "Auxerre",
    "Angers SCO": "Angers",
    "Toulouse FC": "Toulouse",
    "Montpellier HSC": "Montpellier",
    "Stade Brestois": "Brest",
    "Stade Brestois 29": "Brest",

    # --- Bundesliga (league_id=241) ---
    "Bayern Munich": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "RB Leipzig": "RB Leipzig",
    "Bayer Leverkusen": "Leverkusen",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "VfL Wolfsburg": "Wolfsburg",
    "Borussia Monchengladbach": "M'gladbach",
    "Borussia Moenchengladbach": "M'gladbach",
    "SC Freiburg": "Freiburg",
    "1. FSV Mainz 05": "Mainz",
    "FSV Mainz 05": "Mainz",
    "FC Augsburg": "Augsburg",
    "VfB Stuttgart": "Stuttgart",
    "1. FC Union Berlin": "Union Berlin",
    "FC Union Berlin": "Union Berlin",
    "1. FC Heidenheim": "Heidenheim",
    "FC Heidenheim": "Heidenheim",
    "Werder Bremen": "Werder Bremen",
    "TSG Hoffenheim": "Hoffenheim",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    "Holstein Kiel": "Holstein Kiel",
    "FC St. Pauli": "St Pauli",

    # --- Serie A (league_id=253) ---
    "AC Milan": "Milan",
    "Inter Milan": "Inter",
    "AS Roma": "Roma",
    "SS Lazio": "Lazio",
    "SSC Napoli": "Napoli",
    "ACF Fiorentina": "Fiorentina",
    "Atalanta BC": "Atalanta",
    "Torino FC": "Torino",
    "Bologna FC": "Bologna",
    "US Lecce": "Lecce",
    "Cagliari Calcio": "Cagliari",
    "Genoa CFC": "Genoa",
    "Hellas Verona": "Verona",
    "Udinese Calcio": "Udinese",
    "US Sassuolo": "Sassuolo",
    "Empoli FC": "Empoli",
    "Parma Calcio": "Parma",
    "Monza FC": "Monza",
    "AC Monza": "Monza",
    "Como 1907": "Como",
    "Venezia FC": "Venezia",
}


class SoccerdataScraper(BaseScraper):
    """Scraper for the Soccerdata API (soccerdataapi.com).

    Primary source for live injury/sidelined data across all 6 leagues.
    The free tier provides 75 requests/day — our morning pipeline uses
    6 requests (one per league), leaving 69 for other calls.

    The ``scrape_injuries()`` method fetches the sidelined list for
    upcoming matches in a league and returns a DataFrame suitable for
    ``load_soccerdata_injuries()`` in the loader.
    """

    # Soccerdata API domain for rate limiting
    _DOMAIN = "api.soccerdataapi.com"

    @property
    def source_name(self) -> str:
        return "soccerdata"

    def __init__(self) -> None:
        super().__init__()
        self._api_key: Optional[str] = os.environ.get("SOCCERDATA_API_KEY")
        self._base_url = "https://api.soccerdataapi.com"

    # --- abstract method (required by BaseScraper) ---

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Not used directly — Soccerdata provides injury/lineup data, not
        match results.  Call ``scrape_injuries()`` or ``scrape_lineups()``
        instead.

        Returns an empty DataFrame to satisfy the BaseScraper interface.
        """
        return pd.DataFrame()

    # --- public API: injury scraping ------------------------------------------

    def scrape_injuries(
        self,
        league_config: object,
        season: str = "",
    ) -> pd.DataFrame:
        """Scrape sidelined/injured players for a league's upcoming matches.

        Uses the Soccerdata ``/matches/`` endpoint to find upcoming fixtures,
        then fetches match detail for each to extract the sidelined list.

        **How sidelined data maps to our InjuryFlag model:**
          - Soccerdata status "out" → InjuryFlag status "out"
          - Soccerdata status "questionable" → InjuryFlag status "doubt"
          - Any other status → InjuryFlag status "doubt" (safe default)

        Parameters
        ----------
        league_config : ConfigNamespace
            League configuration with ``soccerdata_league_id`` attribute.
        season : str, optional
            Season string (not used — API returns current data).

        Returns
        -------
        pd.DataFrame
            Columns: player_name, team_name, status, description.
            Empty DataFrame if API key is missing, league not configured,
            or no upcoming matches found.
        """
        empty = pd.DataFrame(
            columns=["player_name", "team_name", "status", "description"]
        )

        # --- Validate API key ---
        if not self._check_api_key():
            return empty

        # --- Get Soccerdata league ID from config ---
        soccerdata_id = getattr(league_config, "soccerdata_league_id", None)
        if not soccerdata_id:
            logger.warning(
                "[%s] No soccerdata_league_id configured for %s — skipping",
                self.source_name,
                getattr(league_config, "short_name", "unknown"),
            )
            return empty

        league_name = getattr(league_config, "short_name", "unknown")
        logger.info(
            "[%s] Scraping injuries for %s (soccerdata_id=%s)",
            self.source_name, league_name, soccerdata_id,
        )

        # --- Fetch upcoming matches via livescores endpoint ---
        # The livescores endpoint returns today's matches across all leagues.
        # We filter for our target league.
        try:
            sidelined_data = self._fetch_sidelined_from_livescores(
                soccerdata_id, league_name
            )
        except (ScraperError, Exception) as e:
            logger.error(
                "[%s] Error fetching injury data for %s: %s",
                self.source_name, league_name, e,
            )
            return empty

        if not sidelined_data:
            logger.info(
                "[%s] No sidelined data found for %s (no matches today "
                "or no sidelined players)",
                self.source_name, league_name,
            )
            return empty

        # Build DataFrame from sidelined records
        rows: List[Dict[str, Any]] = []
        for entry in sidelined_data:
            player_info = entry.get("player", {})
            team_name_api = entry.get("team_name", "")
            # Map team name to canonical DB name
            team_name = self._map_team_name(team_name_api)

            # Map status: "out" → "out", "questionable" → "doubt"
            raw_status = str(entry.get("status", "")).strip().lower()
            if raw_status == "out":
                status = "out"
            elif raw_status in ("questionable", "doubtful", "doubt"):
                status = "doubt"
            else:
                status = "doubt"  # Safe default for unknown statuses

            rows.append({
                "player_name": player_info.get("name", "Unknown"),
                "team_name": team_name,
                "status": status,
                "description": entry.get("desc", ""),
            })

        if not rows:
            return empty

        df = pd.DataFrame(rows)
        logger.info(
            "[%s] Found %d sidelined players for %s",
            self.source_name, len(df), league_name,
        )

        # Save raw data for reproducibility
        self.save_raw(df, league_name, season or "current")

        return df

    # --- internal helpers -----------------------------------------------------

    def _fetch_sidelined_from_livescores(
        self,
        soccerdata_league_id: int,
        league_name: str,
    ) -> List[Dict[str, Any]]:
        """Fetch sidelined players from today's livescores for a league.

        The livescores endpoint returns all of today's matches grouped by
        league.  We find our target league, get match IDs, then fetch
        each match's detail to extract sidelined data.

        Returns a flat list of sidelined player dicts with an extra
        ``team_name`` key indicating which team the player belongs to.
        """
        # Step 1: Get today's matches via livescores
        url = f"{self._base_url}/livescores/"
        params = {"auth_token": self._api_key}

        response = self._request_with_retry(url, self._DOMAIN, params=params)
        data = response.json()

        # Find matches for our target league
        match_ids: List[int] = []
        for league_group in data.get("results", []):
            if league_group.get("league_id") == soccerdata_league_id:
                for stage in league_group.get("stage", []):
                    for match in stage.get("matches", []):
                        mid = match.get("id")
                        if mid:
                            match_ids.append(mid)

        if not match_ids:
            # No matches today — try the matches endpoint with today's date
            today_str = date.today().strftime("%d/%m/%Y")
            url2 = f"{self._base_url}/matches/"
            params2 = {
                "auth_token": self._api_key,
                "league_id": soccerdata_league_id,
                "date": today_str,
            }
            try:
                response2 = self._request_with_retry(
                    url2, self._DOMAIN, params=params2,
                )
                data2 = response2.json()
                for match in data2.get("results", []):
                    mid = match.get("id")
                    if mid:
                        match_ids.append(mid)
            except (ScraperError, Exception) as e:
                logger.debug(
                    "[%s] matches/ endpoint failed for %s: %s",
                    self.source_name, league_name, e,
                )

        if not match_ids:
            logger.info(
                "[%s] No matches found today for %s — no sidelined data",
                self.source_name, league_name,
            )
            return []

        # Step 2: Fetch match details to get sidelined players
        # Limit to 3 matches to conserve daily API budget (75 req/day)
        sidelined: List[Dict[str, Any]] = []
        for mid in match_ids[:3]:
            try:
                match_sidelined = self._fetch_match_sidelined(mid)
                sidelined.extend(match_sidelined)
            except (ScraperError, Exception) as e:
                logger.warning(
                    "[%s] Error fetching sidelined for match %d: %s",
                    self.source_name, mid, e,
                )

        return sidelined

    def _fetch_match_sidelined(
        self,
        match_id: int,
    ) -> List[Dict[str, Any]]:
        """Fetch sidelined players from a single match detail.

        The match detail endpoint returns a ``sidelined`` object with
        ``home`` and ``away`` lists of absent players.

        Returns a flat list of sidelined player dicts with an extra
        ``team_name`` key for team identification.
        """
        url = f"{self._base_url}/match/"
        params = {
            "auth_token": self._api_key,
            "match_id": match_id,
        }

        response = self._request_with_retry(url, self._DOMAIN, params=params)
        detail = response.json()

        sidelined: List[Dict[str, Any]] = []

        # Get team names from match detail
        teams = detail.get("teams", {})
        home_name = teams.get("home", {}).get("name", "")
        away_name = teams.get("away", {}).get("name", "")

        # Extract sidelined players
        sidelined_data = detail.get("sidelined", {})

        # Home team sidelined
        for player_entry in sidelined_data.get("home", []):
            entry = dict(player_entry)
            entry["team_name"] = home_name
            sidelined.append(entry)

        # Away team sidelined
        for player_entry in sidelined_data.get("away", []):
            entry = dict(player_entry)
            entry["team_name"] = away_name
            sidelined.append(entry)

        return sidelined

    def _map_team_name(self, api_name: str) -> str:
        """Map a Soccerdata API team name to the canonical DB name.

        Checks SOCCERDATA_TEAM_MAP first, then returns the original name
        if no mapping exists (exact match will be attempted in the loader).

        Parameters
        ----------
        api_name : str
            Team name as returned by the Soccerdata API.

        Returns
        -------
        str
            Canonical team name for database lookup.
        """
        mapped = SOCCERDATA_TEAM_MAP.get(api_name)
        if mapped:
            return mapped

        # Try case-insensitive lookup
        for key, value in SOCCERDATA_TEAM_MAP.items():
            if key.lower() == api_name.lower():
                return value

        # No mapping found — return as-is, loader will attempt direct match
        return api_name

    def _check_api_key(self) -> bool:
        """Verify SOCCERDATA_API_KEY is configured.

        Returns False and logs a warning if the environment variable is
        not set.  This is a non-fatal condition — the pipeline continues
        without Soccerdata data and falls back to API-Football.
        """
        if not self._api_key:
            logger.warning(
                "[%s] SOCCERDATA_API_KEY environment variable "
                "is not set — Soccerdata scraping disabled.  "
                "Set it in .env to enable live injury data.",
                self.source_name,
            )
            return False
        return True
