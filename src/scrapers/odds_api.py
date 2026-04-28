"""
BetVector — The Odds API Scraper (E19-01)
==========================================
Fetches pre-match bookmaker odds from The Odds API (the-odds-api.com),
BetVector's primary source for live/daily odds data.

The Odds API aggregates odds from 50+ bookmakers in a single API call,
including sharp bookmakers (Pinnacle) and US sportsbooks (FanDuel, DraftKings)
that other sources don't cover.

Endpoint used::

    GET /v4/sports/soccer_epl/odds
    ?apiKey={key}&regions=uk,us,eu&markets=h2h,totals&oddsFormat=decimal

The response is an array of upcoming matches (events), each containing a
``bookmakers`` array with nested ``markets`` and ``outcomes``.  For soccer
h2h markets, there are three outcomes: home team, "Draw", and away team.
For totals markets, there are two outcomes: "Over" and "Under", each with
a ``point`` value (e.g., 2.5 for Over/Under 2.5 goals).

**Free tier:** 500 requests/month.  Each call to the odds endpoint costs
1 request and returns ALL upcoming EPL matches with ALL bookmaker odds.
A 3x/day pipeline (morning, midday, evening) uses ~90 requests/month —
well within the free tier for single-league EPL operation.

**API usage tracking:** The response includes headers:
  - ``x-requests-remaining`` — requests left until quota resets
  - ``x-requests-used`` — requests consumed this billing period
  - ``x-requests-last`` — cost of the current request

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import PROJECT_ROOT, config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


def _http_status_from_exc(exc: BaseException) -> Optional[int]:
    """Walk the exception chain and return the HTTP status code, if any.

    ``ScraperError`` wraps the underlying ``requests.HTTPError`` via ``raise
    ... from exc``; the original status lives on ``HTTPError.response``.
    Returns None when no HTTP status can be recovered (e.g. timeouts).
    """
    cur: Optional[BaseException] = exc
    while cur is not None:
        response = getattr(cur, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
            if isinstance(status, int):
                return status
        cur = cur.__cause__
    return None


# ============================================================================
# Constants
# ============================================================================

DOMAIN = "api.the-odds-api.com"

# ============================================================================
# League → Sport Key Mapping (PC-09-04)
# ============================================================================
# Each league has its own Odds API sport key.  Previously, "soccer_epl" was
# hardcoded for ALL leagues, causing cross-league contamination — e.g.,
# Championship pipeline fetched EPL odds and created phantom EPL fixtures
# in the Championship league via auto-stub creation.
#
# The mapping below uses the league's ``short_name`` from config/leagues.yaml
# to look up the correct Odds API sport key.  If a league is not in this
# mapping, odds fetching is gracefully skipped for that league.

LEAGUE_TO_SPORT_KEY: Dict[str, str] = {
    "EPL": "soccer_epl",
    "Championship": "soccer_championship",
    "LaLiga": "soccer_spain_la_liga",
    "Ligue1": "soccer_france_ligue_one",
    "Bundesliga": "soccer_germany_bundesliga",
    "SerieA": "soccer_italy_serie_a",
}

# Fallback for backwards compatibility (used by _fetch_odds if no override)
SPORT_KEY = "soccer_epl"

# ============================================================================
# Team Name Normalisation
# ============================================================================
# The Odds API uses full team names (e.g., "Manchester City", "Arsenal").
# Most already match our canonical names, but a few need mapping to ensure
# exact matches against the Team table in the database.
#
# If a team isn't in this map, we try an exact match first, then fuzzy match.

TEAM_NAME_MAP: Dict[str, str] = {
    # ── EPL ──────────────────────────────────────────────────────────────
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Brentford": "Brentford",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Liverpool": "Liverpool",
    "Southampton": "Southampton",
    "AFC Bournemouth": "AFC Bournemouth",
    "Bournemouth": "AFC Bournemouth",
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Brighton & Hove Albion": "Brighton & Hove Albion",
    "Ipswich Town": "Ipswich Town",
    "Leeds United": "Leeds United",
    "Leicester City": "Leicester City",
    "Luton Town": "Luton Town",
    "Manchester City": "Manchester City",
    "Manchester United": "Manchester United",
    "Newcastle United": "Newcastle United",
    "Nottingham Forest": "Nottingham Forest",
    "Norwich City": "Norwich City",
    "Sheffield United": "Sheffield United",
    "Sunderland": "Sunderland",
    "Tottenham Hotspur": "Tottenham Hotspur",
    "West Bromwich Albion": "West Bromwich Albion",
    "West Ham United": "West Ham United",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",
    "Wolves": "Wolverhampton Wanderers",
    "Spurs": "Tottenham Hotspur",
    "West Ham": "West Ham United",
    "Newcastle": "Newcastle United",
    "Nottm Forest": "Nottingham Forest",

    # ── Championship ─────────────────────────────────────────────────────
    # Odds API uses full names; DB uses Football-Data.co.uk short forms
    "Birmingham City": "Birmingham",
    "Blackburn Rovers": "Blackburn",
    "Bristol City": "Bristol City",
    "Cardiff City": "Cardiff",
    "Coventry City": "Coventry",
    "Derby County": "Derby",
    "Huddersfield Town": "Huddersfield",
    "Hull City": "Hull",
    "Ipswich": "Ipswich",
    "Leeds": "Leeds",
    "Leicester": "Leicester",
    "Luton": "Luton",
    "Middlesbrough": "Middlesbrough",
    "Millwall": "Millwall",
    "Oxford United": "Oxford",
    "Plymouth Argyle": "Plymouth",
    "Portsmouth": "Portsmouth",
    "Preston North End": "Preston",
    "Queens Park Rangers": "QPR",
    "QPR": "QPR",
    "Sheffield Wednesday": "Sheffield Weds",
    "Stoke City": "Stoke",
    "Swansea City": "Swansea",
    "Watford": "Watford",
    "West Brom": "West Brom",
    "West Bromwich": "West Brom",
    "Wrexham": "Wrexham",

    # ── La Liga ──────────────────────────────────────────────────────────
    # Odds API uses full Spanish names; DB uses Football-Data short forms
    "Atletico Madrid": "Ath Madrid",
    "Atlético Madrid": "Ath Madrid",
    "Atletico de Madrid": "Ath Madrid",
    "Athletic Bilbao": "Ath Bilbao",
    "Athletic Club": "Ath Bilbao",
    "FC Barcelona": "Barcelona",
    "Barcelona": "Barcelona",
    "Real Betis": "Betis",
    "Betis": "Betis",
    "Cadiz CF": "Cadiz",
    "Cadiz": "Cadiz",
    "Celta Vigo": "Celta",
    "Celta": "Celta",
    "Deportivo Alavés": "Alaves",
    "Deportivo Alaves": "Alaves",
    "Alaves": "Alaves",
    "Alavés": "Alaves",
    "Elche CF": "Elche",
    "Elche": "Elche",
    "Espanyol": "Espanol",
    "RCD Espanyol": "Espanol",
    "Getafe CF": "Getafe",
    "Getafe": "Getafe",
    "Girona FC": "Girona",
    "Girona": "Girona",
    "Granada CF": "Granada",
    "Granada": "Granada",
    "Las Palmas": "Las Palmas",
    "UD Las Palmas": "Las Palmas",
    "CD Leganés": "Leganes",
    "CD Leganes": "Leganes",
    "Leganes": "Leganes",
    "Leganés": "Leganes",
    "Levante UD": "Levante",
    "Levante": "Levante",
    "RCD Mallorca": "Mallorca",
    "Mallorca": "Mallorca",
    "CA Osasuna": "Osasuna",
    "Osasuna": "Osasuna",
    "Real Oviedo": "Oviedo",
    "Oviedo": "Oviedo",
    "Real Madrid": "Real Madrid",
    "Rayo Vallecano": "Vallecano",
    "Vallecano": "Vallecano",
    "Real Sociedad": "Sociedad",
    "Sociedad": "Sociedad",
    "Real Valladolid": "Valladolid",
    "Valladolid": "Valladolid",
    "Sevilla FC": "Sevilla",
    "Sevilla": "Sevilla",
    "Valencia CF": "Valencia",
    "Valencia": "Valencia",
    "Villarreal CF": "Villarreal",
    "Villarreal": "Villarreal",
    "SD Huesca": "Huesca",
    "Huesca": "Huesca",
    "UD Almería": "Almeria",
    "UD Almeria": "Almeria",
    "Almería": "Almeria",
    "Almeria": "Almeria",
    "SD Eibar": "Eibar",
    "Eibar": "Eibar",

    # ── Ligue 1 ──────────────────────────────────────────────────────────
    # Odds API uses full French names; DB uses Football-Data short forms
    "AC Ajaccio": "Ajaccio",
    "Ajaccio": "Ajaccio",
    "Angers SCO": "Angers",
    "Angers": "Angers",
    "AJ Auxerre": "Auxerre",
    "Auxerre": "Auxerre",
    "Girondins de Bordeaux": "Bordeaux",
    "Bordeaux": "Bordeaux",
    "Stade Brestois 29": "Brest",
    "Brest": "Brest",
    "Clermont Foot": "Clermont",
    "Clermont": "Clermont",
    "Dijon FCO": "Dijon",
    "Dijon": "Dijon",
    "Le Havre AC": "Le Havre",
    "Le Havre": "Le Havre",
    "RC Lens": "Lens",
    "Lens": "Lens",
    "Lille OSC": "Lille",
    "Lille": "Lille",
    "FC Lorient": "Lorient",
    "Lorient": "Lorient",
    "Olympique Lyonnais": "Lyon",
    "Olympique Lyon": "Lyon",
    "Lyon": "Lyon",
    "Olympique de Marseille": "Marseille",
    "Olympique Marseille": "Marseille",
    "Marseille": "Marseille",
    "FC Metz": "Metz",
    "Metz": "Metz",
    "AS Monaco": "Monaco",
    "Monaco": "Monaco",
    "Montpellier HSC": "Montpellier",
    "Montpellier": "Montpellier",
    "FC Nantes": "Nantes",
    "Nantes": "Nantes",
    "OGC Nice": "Nice",
    "Nice": "Nice",
    "Nîmes Olympique": "Nimes",
    "Nimes": "Nimes",
    "Paris FC": "Paris FC",
    "Paris Saint-Germain": "Paris SG",
    "Paris Saint Germain": "Paris SG",
    "PSG": "Paris SG",
    "Stade de Reims": "Reims",
    "Reims": "Reims",
    "Stade Rennais": "Rennes",
    "Rennes": "Rennes",
    "AS Saint-Étienne": "St Etienne",
    "AS Saint-Etienne": "St Etienne",
    "Saint-Étienne": "St Etienne",
    "Saint-Etienne": "St Etienne",
    "St Etienne": "St Etienne",
    "RC Strasbourg Alsace": "Strasbourg",
    "RC Strasbourg": "Strasbourg",
    "Strasbourg": "Strasbourg",
    "Toulouse FC": "Toulouse",
    "Toulouse": "Toulouse",
    "ES Troyes AC": "Troyes",
    "Troyes": "Troyes",

    # ── Bundesliga ───────────────────────────────────────────────────────
    # Odds API uses full German names; DB uses Football-Data short forms
    "FC Augsburg": "Augsburg",
    "Augsburg": "Augsburg",
    "Bayern Munich": "Bayern Munich",
    "FC Bayern Munich": "Bayern Munich",
    "Bayern München": "Bayern Munich",
    "VfL Bochum": "Bochum",
    "Bochum": "Bochum",
    "Borussia Dortmund": "Dortmund",
    "Dortmund": "Dortmund",
    "SV Darmstadt 98": "Darmstadt",
    "Darmstadt": "Darmstadt",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "Frankfurt": "Ein Frankfurt",
    "SC Freiburg": "Freiburg",
    "Freiburg": "Freiburg",
    "SpVgg Greuther Fürth": "Greuther Furth",
    "Greuther Fürth": "Greuther Furth",
    "Greuther Furth": "Greuther Furth",
    "1. FC Heidenheim 1846": "Heidenheim",
    "FC Heidenheim": "Heidenheim",
    "Heidenheim": "Heidenheim",
    "Hertha BSC": "Hertha",
    "Hertha Berlin": "Hertha",
    "Hertha": "Hertha",
    "TSG Hoffenheim": "Hoffenheim",
    "Hoffenheim": "Hoffenheim",
    "Holstein Kiel": "Holstein Kiel",
    "Bayer Leverkusen": "Leverkusen",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Leverkusen": "Leverkusen",
    "Borussia Mönchengladbach": "M'gladbach",
    "Borussia Monchengladbach": "M'gladbach",
    "Mönchengladbach": "M'gladbach",
    "Monchengladbach": "M'gladbach",
    "1. FSV Mainz 05": "Mainz",
    "Mainz 05": "Mainz",
    "Mainz": "Mainz",
    "RB Leipzig": "RB Leipzig",
    "FC Schalke 04": "Schalke 04",
    "Schalke 04": "Schalke 04",
    "FC St. Pauli": "St Pauli",
    "St. Pauli": "St Pauli",
    "St Pauli": "St Pauli",
    "VfB Stuttgart": "Stuttgart",
    "Stuttgart": "Stuttgart",
    "1. FC Union Berlin": "Union Berlin",
    "Union Berlin": "Union Berlin",
    "SV Werder Bremen": "Werder Bremen",
    "Werder Bremen": "Werder Bremen",
    "VfL Wolfsburg": "Wolfsburg",
    "Wolfsburg": "Wolfsburg",
    "1. FC Köln": "FC Koln",
    "FC Köln": "FC Koln",
    "1. FC Koln": "FC Koln",
    "FC Koln": "FC Koln",
    "Arminia Bielefeld": "Bielefeld",
    "Bielefeld": "Bielefeld",

    # ── Serie A ──────────────────────────────────────────────────────────
    # Odds API uses English/full names; DB uses Football-Data short forms
    "Atalanta BC": "Atalanta",
    "Atalanta": "Atalanta",
    "Bologna FC": "Bologna",
    "Bologna": "Bologna",
    "Cagliari Calcio": "Cagliari",
    "Cagliari": "Cagliari",
    "Como 1907": "Como",
    "Como": "Como",
    "US Cremonese": "Cremonese",
    "Cremonese": "Cremonese",
    "Empoli FC": "Empoli",
    "Empoli": "Empoli",
    "ACF Fiorentina": "Fiorentina",
    "Fiorentina": "Fiorentina",
    "Frosinone Calcio": "Frosinone",
    "Frosinone": "Frosinone",
    "Genoa CFC": "Genoa",
    "Genoa": "Genoa",
    "Hellas Verona": "Verona",
    "Hellas Verona FC": "Verona",
    "Verona": "Verona",
    "Inter Milan": "Inter",
    "FC Internazionale": "Inter",
    "Inter": "Inter",
    "Juventus FC": "Juventus",
    "Juventus": "Juventus",
    "SS Lazio": "Lazio",
    "Lazio": "Lazio",
    "US Lecce": "Lecce",
    "Lecce": "Lecce",
    "AC Milan": "Milan",
    "Milan": "Milan",
    "AC Monza": "Monza",
    "Monza": "Monza",
    "SSC Napoli": "Napoli",
    "Napoli": "Napoli",
    "Parma Calcio 1913": "Parma",
    "Parma": "Parma",
    "AC Pisa 1909": "Pisa",
    "Pisa": "Pisa",
    "AS Roma": "Roma",
    "Roma": "Roma",
    "US Salernitana 1919": "Salernitana",
    "Salernitana": "Salernitana",
    "UC Sampdoria": "Sampdoria",
    "Sampdoria": "Sampdoria",
    "US Sassuolo": "Sassuolo",
    "Sassuolo": "Sassuolo",
    "Spezia Calcio": "Spezia",
    "Spezia": "Spezia",
    "Torino FC": "Torino",
    "Torino": "Torino",
    "Udinese Calcio": "Udinese",
    "Udinese": "Udinese",
    "Venezia FC": "Venezia",
    "Venezia": "Venezia",
}

# ============================================================================
# Bookmaker Key Mapping
# ============================================================================
# The Odds API uses lowercase string keys for bookmakers (e.g., "pinnacle",
# "bet365").  We map them to display names stored in config/settings.yaml.
# This fallback dict handles the most important bookmakers if config is missing.

DEFAULT_BOOKMAKER_MAP: Dict[str, str] = {
    "pinnacle": "Pinnacle",
    "bet365": "Bet365",
    "fanduel": "FanDuel",
    "draftkings": "DraftKings",
    "betmgm": "BetMGM",
    "williamhill_us": "William Hill",
    "williamhill": "William Hill",
    "unibet_eu": "Unibet",
    "unibet_uk": "Unibet",
    "unibet": "Unibet",
    "betway": "Betway",
    "ladbrokes_uk": "Ladbrokes",
    "ladbrokes": "Ladbrokes",
    "betfair_ex_eu": "Betfair",
    "betfair_ex_uk": "Betfair",
    "betfair": "Betfair",
    "bovada": "Bovada",
    "bwin": "Bwin",
    "888sport": "888sport",
    "betrivers": "BetRivers",
    "pointsbetus": "PointsBet",
    "barstool": "Barstool",
    "foxbet": "Fox Bet",
    "superbook": "SuperBook",
    "lowvig": "LowVig",
    "betonlineag": "BetOnline",
    "mybookieag": "MyBookie",
    "matchbook": "Matchbook",
    "betsson": "Betsson",
    "nordicbet": "NordicBet",
    "marathonbet": "Marathonbet",
    "sport888": "888sport",
    "coolbet": "Coolbet",
    "gtbets": "GTBets",
}

# ============================================================================
# Market Type Mapping
# ============================================================================
# Maps The Odds API market keys to BetVector's canonical market_type enum.

MARKET_TYPE_MAP: Dict[str, str] = {
    "h2h": "1X2",       # Head-to-head = match result (home/draw/away)
    "totals": "OU25",    # Totals = Over/Under (point value determines exact market)
}


class TheOddsAPIScraper(BaseScraper):
    """Scraper for The Odds API — pre-match bookmaker odds from 50+ books.

    Fetches odds for all upcoming EPL matches in a single API call.
    Returns a DataFrame with columns: date, home_team, away_team,
    bookmaker, market_type, selection, odds_decimal.

    The free tier (500 requests/month) is sufficient for EPL-only operation
    at 3 calls/day (~90/month).  Usage is tracked via response headers and
    logged at each request.

    Example::

        scraper = TheOddsAPIScraper()
        df = scraper.scrape(league_config, "2025-26")
        # → DataFrame with one row per bookmaker × market × selection
    """

    def __init__(self) -> None:
        super().__init__()

        # API key from environment variable (never hardcoded)
        self._api_key: Optional[str] = os.environ.get("THE_ODDS_API_KEY")

        # Base URL from config, with sensible default
        self._base_url: str = getattr(
            getattr(config.settings.scraping, "the_odds_api", None),
            "base_url",
            "https://api.the-odds-api.com/v4",
        )

        # Regions to request — determines which bookmakers are included.
        # "uk" gives UK books (Bet365, William Hill, Ladbrokes),
        # "us" gives US books (FanDuel, DraftKings),
        # "eu" gives European books (Pinnacle, Unibet, Betway).
        self._regions: str = getattr(
            getattr(config.settings.scraping, "the_odds_api", None),
            "regions",
            "uk,us,eu",
        )

        # Markets to fetch — "h2h" = match result, "totals" = over/under
        self._markets: str = getattr(
            getattr(config.settings.scraping, "the_odds_api", None),
            "markets",
            "h2h,totals",
        )

        # Budget tracking — updated from response headers after each request
        self._requests_remaining: Optional[int] = None
        self._requests_used: Optional[int] = None

        # Auth-failure flag — set to True when the API returns 401/403 so the
        # pipeline can distinguish a key/quota problem from an empty response.
        # A silent "no data" used to be misreported as "budget exhausted" even
        # when the real cause was a revoked/expired key.
        self._auth_failed: bool = False

        # Warning threshold: log a warning when remaining requests drop below this
        self._warning_threshold: int = int(getattr(
            getattr(config.settings.scraping, "the_odds_api", None),
            "warning_threshold",
            50,
        ))

        # Hard stop threshold: refuse to make requests below this to preserve
        # budget for critical pipeline runs
        self._hard_stop_threshold: int = int(getattr(
            getattr(config.settings.scraping, "the_odds_api", None),
            "hard_stop_threshold",
            10,
        ))

        # Bookmaker mapping from config (falls back to DEFAULT_BOOKMAKER_MAP)
        self._bookmaker_map: Dict[str, str] = self._load_bookmaker_map()

    @property
    def source_name(self) -> str:
        """Short identifier for this data source."""
        return "the_odds_api"

    # ========================================================================
    # Public API
    # ========================================================================

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch pre-match odds for all upcoming EPL matches.

        One API call returns odds from all bookmakers for all upcoming matches.
        The response is parsed into a flat DataFrame suitable for loading
        into the database via ``load_odds_the_odds_api()``.

        Parameters
        ----------
        league_config : ConfigNamespace
            League configuration object.  The ``short_name`` attribute is used
            for logging and raw file naming (e.g., "EPL").
        season : str
            Season identifier (e.g., "2025-26").  Not directly used by the API
            (which always returns upcoming matches) but used for logging and
            raw file naming.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: date, home_team, away_team, bookmaker,
            market_type, selection, odds_decimal.  Empty DataFrame if no
            odds are available or the API key is missing.
        """
        league_name = getattr(league_config, "short_name", "EPL")

        # PC-09-04: Resolve the correct Odds API sport key for this league.
        # Previously, SPORT_KEY was always "soccer_epl" regardless of league,
        # causing cross-league contamination (e.g., Championship fetching EPL
        # odds and creating phantom EPL fixtures in the Championship league).
        sport_key = LEAGUE_TO_SPORT_KEY.get(league_name)
        if sport_key is None:
            logger.warning(
                "[the_odds_api] No sport key mapping for league '%s' — "
                "skipping odds fetch.  Add an entry to LEAGUE_TO_SPORT_KEY "
                "in odds_api.py if this league should have live odds.",
                league_name,
            )
            return pd.DataFrame()

        # Validate API key
        if not self._check_api_key():
            return pd.DataFrame()

        # Check budget before making request
        if not self._check_budget():
            return pd.DataFrame()

        # Fetch odds from The Odds API
        logger.info(
            "[the_odds_api] Fetching odds for %s (season %s, sport_key=%s)",
            league_name, season, sport_key,
        )

        raw_data = self._fetch_odds(sport_key=sport_key)
        if raw_data is None:
            logger.warning("[the_odds_api] No data returned from API")
            return pd.DataFrame()

        # Save raw response for reproducibility
        self._save_raw_json(raw_data, league_name, "odds", season)

        # Parse events into flat odds records
        all_records: List[Dict[str, Any]] = []
        events_parsed = 0

        for event in raw_data:
            records = self._parse_event(event)
            all_records.extend(records)
            if records:
                events_parsed += 1

        if not all_records:
            logger.warning(
                "[the_odds_api] Parsed 0 odds records from %d events",
                len(raw_data),
            )
            return pd.DataFrame()

        df = pd.DataFrame(all_records)

        logger.info(
            "[the_odds_api] Parsed %d odds records across %d events "
            "from %d bookmakers",
            len(df), events_parsed, df["bookmaker"].nunique(),
        )

        return df

    def scrape_odds(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Alias for scrape() — consistent with APIFootballScraper naming.

        The pipeline calls ``scraper.scrape_odds()`` for odds-specific scrapers.
        This method just delegates to ``scrape()`` for compatibility.
        """
        return self.scrape(league_config, season)

    # ========================================================================
    # API Communication
    # ========================================================================

    def _fetch_odds(
        self, sport_key: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Make the authenticated API call and return the parsed JSON response.

        Parameters
        ----------
        sport_key : str, optional
            The Odds API sport key (e.g., "soccer_epl", "soccer_spain_la_liga").
            Falls back to the module-level SPORT_KEY constant if not provided.

        Returns
        -------
        list of dict or None
            List of event objects from the API, or None on failure.
        """
        key = sport_key or SPORT_KEY
        url = f"{self._base_url}/sports/{key}/odds"

        params = {
            "apiKey": self._api_key,
            "regions": self._regions,
            "markets": self._markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }

        try:
            response = self._request_with_retry(url, DOMAIN, params=params)

            # Update budget tracking from response headers.
            # These headers tell us how many API requests we have left this
            # billing period — critical for staying within the free tier.
            self._update_budget_from_headers(response.headers)

            data = response.json()

            if not isinstance(data, list):
                logger.error(
                    "[the_odds_api] Unexpected response type: %s (expected list)",
                    type(data).__name__,
                )
                return None

            logger.info(
                "[the_odds_api] API returned %d events "
                "(remaining requests: %s)",
                len(data),
                self._requests_remaining or "unknown",
            )
            return data

        except ScraperError as exc:
            # Distinguish auth failures (401/403) from generic scrape errors.
            # 401 = key invalid/revoked, 403 = key valid but plan/quota denied.
            # Either way, this is NOT a transient "budget exhausted" condition —
            # it requires owner intervention (rotate key or check plan).
            status = _http_status_from_exc(exc)
            if status in (401, 403):
                self._auth_failed = True
                logger.error(
                    "[the_odds_api] AUTH FAILURE (HTTP %s) for sport_key=%s — "
                    "THE_ODDS_API_KEY is invalid, revoked, or out of quota. "
                    "Check the-odds-api.com dashboard and rotate the key in .env.",
                    status, key,
                )
            else:
                logger.error("[the_odds_api] Failed to fetch odds: %s", exc)
            return None
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "[the_odds_api] Failed to parse API response: %s", exc,
            )
            return None

    def _update_budget_from_headers(
        self, headers: Dict[str, str],
    ) -> None:
        """Read API usage counters from response headers.

        The Odds API includes these headers in every response:
          - x-requests-remaining: credits left until quota resets
          - x-requests-used: credits consumed since last reset
          - x-requests-last: cost of the current API call

        We log warnings when approaching the budget limit so the user
        can monitor API consumption without manually checking the dashboard.
        """
        remaining = headers.get("x-requests-remaining")
        used = headers.get("x-requests-used")
        last_cost = headers.get("x-requests-last")

        if remaining is not None:
            self._requests_remaining = int(remaining)
        if used is not None:
            self._requests_used = int(used)

        logger.info(
            "[the_odds_api] API budget — remaining: %s, used: %s, "
            "last request cost: %s",
            remaining or "?", used or "?", last_cost or "?",
        )

        # Warn if running low on budget
        if (
            self._requests_remaining is not None
            and self._requests_remaining < self._warning_threshold
        ):
            logger.warning(
                "[the_odds_api] ⚠️  Low API budget: %d requests remaining "
                "(warning threshold: %d)",
                self._requests_remaining, self._warning_threshold,
            )

    # ========================================================================
    # Event Parsing
    # ========================================================================

    def _parse_event(
        self, event: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Parse a single event (match) from the API response.

        Each event contains a ``bookmakers`` array, which in turn contains
        ``markets`` (h2h, totals) with ``outcomes`` (the actual odds).

        For soccer h2h, outcomes are named by team name (e.g., "Arsenal")
        and "Draw".  We map these to our canonical selections: "home",
        "draw", "away".

        Parameters
        ----------
        event : dict
            Single event object from the API response.

        Returns
        -------
        list of dict
            Flat odds records for this event, ready for DataFrame conversion.
        """
        records: List[Dict[str, Any]] = []

        # Extract match identifiers
        event_id = event.get("id", "")
        home_team_raw = event.get("home_team", "")
        away_team_raw = event.get("away_team", "")
        commence_time = event.get("commence_time", "")

        # Map team names to canonical DB names
        home_team = self._map_team_name(home_team_raw)
        away_team = self._map_team_name(away_team_raw)

        # Parse date from ISO 8601 commence_time (e.g., "2025-03-08T15:00:00Z")
        match_date = self._parse_date(commence_time)
        if not match_date:
            logger.warning(
                "[the_odds_api] Skipping event %s — invalid commence_time: %s",
                event_id, commence_time,
            )
            return records

        # Parse each bookmaker's odds for this event
        bookmakers = event.get("bookmakers", [])
        for bookie in bookmakers:
            bookie_key = bookie.get("key", "")
            bookie_display = self._map_bookmaker(bookie_key)

            # Parse each market (h2h, totals) for this bookmaker
            markets = bookie.get("markets", [])
            for market in markets:
                market_key = market.get("key", "")
                outcomes = market.get("outcomes", [])

                market_records = self._parse_market_outcomes(
                    market_key=market_key,
                    outcomes=outcomes,
                    home_team_raw=home_team_raw,
                    away_team_raw=away_team_raw,
                )

                for selection, odds_decimal, market_type in market_records:
                    records.append({
                        "date": match_date,
                        "home_team": home_team,
                        "away_team": away_team,
                        "bookmaker": bookie_display,
                        "market_type": market_type,
                        "selection": selection,
                        "odds_decimal": odds_decimal,
                    })

        return records

    def _parse_market_outcomes(
        self,
        market_key: str,
        outcomes: List[Dict[str, Any]],
        home_team_raw: str,
        away_team_raw: str,
    ) -> List[tuple]:
        """Parse outcomes for a single market (h2h or totals).

        Parameters
        ----------
        market_key : str
            API market key, e.g., "h2h" or "totals".
        outcomes : list of dict
            Outcome objects from the API, each with "name", "price",
            and optionally "point" (for totals).
        home_team_raw : str
            Home team name as returned by the API (for h2h outcome matching).
        away_team_raw : str
            Away team name as returned by the API.

        Returns
        -------
        list of tuple
            Each tuple is (selection, odds_decimal, market_type).
        """
        results: List[tuple] = []

        if market_key == "h2h":
            # Soccer h2h has three outcomes: home win, draw, away win.
            # Outcomes are named by team name (home/away) and "Draw".
            for outcome in outcomes:
                name = outcome.get("name", "")
                price = self._safe_float(outcome.get("price"))
                if price is None or price <= 1.0:
                    continue

                # Map outcome name to canonical selection
                if name == home_team_raw:
                    selection = "home"
                elif name == away_team_raw:
                    selection = "away"
                elif name.lower() == "draw":
                    selection = "draw"
                else:
                    logger.debug(
                        "[the_odds_api] Unknown h2h outcome '%s' "
                        "(home=%s, away=%s)",
                        name, home_team_raw, away_team_raw,
                    )
                    continue

                results.append((selection, price, "1X2"))

        elif market_key == "totals":
            # Totals market has "Over" and "Under" outcomes with a point value.
            # The point value determines which specific market (OU25, OU15, etc.).
            for outcome in outcomes:
                name = outcome.get("name", "")
                price = self._safe_float(outcome.get("price"))
                point = self._safe_float(outcome.get("point"))

                if price is None or price <= 1.0 or point is None:
                    continue

                # Map point value to our canonical market_type enum
                market_type = self._point_to_market_type(point)
                if market_type is None:
                    # Unsupported point value (e.g., 1.0, 3.0) — skip
                    continue

                # Map Over/Under to canonical selection
                name_lower = name.lower().strip()
                if "over" in name_lower:
                    selection = "over"
                elif "under" in name_lower:
                    selection = "under"
                else:
                    continue

                results.append((selection, price, market_type))

        return results

    # ========================================================================
    # Name Mapping Helpers
    # ========================================================================

    def _map_team_name(self, api_name: str) -> str:
        """Map an API team name to the canonical BetVector DB name.

        First tries an exact match in the TEAM_NAME_MAP.  If no match,
        falls back to fuzzy matching against all canonical names.  If
        still no match, returns the original name and logs a warning.

        Parameters
        ----------
        api_name : str
            Team name as returned by The Odds API.

        Returns
        -------
        str
            Canonical team name for the database.
        """
        if not api_name:
            return api_name

        # Direct lookup
        canonical = TEAM_NAME_MAP.get(api_name)
        if canonical:
            return canonical

        # Fuzzy fallback using difflib — handles minor spelling variations
        from difflib import get_close_matches

        all_canonical = list(set(TEAM_NAME_MAP.values()))
        matches = get_close_matches(api_name, all_canonical, n=1, cutoff=0.7)
        if matches:
            logger.info(
                "[the_odds_api] Fuzzy matched team '%s' → '%s'",
                api_name, matches[0],
            )
            return matches[0]

        # No match found — return original and log for investigation
        logger.warning(
            "[the_odds_api] UNMAPPED team name: '%s' — add it to "
            "TEAM_NAME_MAP in odds_api.py",
            api_name,
        )
        return api_name

    def _map_bookmaker(self, bookie_key: str) -> str:
        """Map a bookmaker API key to a clean display name.

        Tries the config-loaded bookmaker map first, then falls back to
        the DEFAULT_BOOKMAKER_MAP.  If neither has the key, returns the
        raw key with a title-cased fallback.

        Parameters
        ----------
        bookie_key : str
            Bookmaker key from The Odds API (e.g., "pinnacle", "bet365").

        Returns
        -------
        str
            Clean display name (e.g., "Pinnacle", "Bet365").
        """
        # Config-loaded map takes priority (allows user customisation)
        name = self._bookmaker_map.get(bookie_key)
        if name:
            return name

        # Fallback to hardcoded defaults
        name = DEFAULT_BOOKMAKER_MAP.get(bookie_key)
        if name:
            return name

        # Last resort — log and return a cleaned version of the key
        logger.debug(
            "[the_odds_api] Unknown bookmaker key: '%s'", bookie_key,
        )
        return bookie_key.replace("_", " ").title()

    # ========================================================================
    # Utility Helpers
    # ========================================================================

    @staticmethod
    def _parse_date(commence_time: str) -> Optional[str]:
        """Parse an ISO 8601 timestamp into a YYYY-MM-DD date string.

        The Odds API returns commence_time in ISO format with timezone:
        ``"2025-03-08T15:00:00Z"``

        We extract just the date portion for matching against our Match table.

        Parameters
        ----------
        commence_time : str
            ISO 8601 timestamp from the API.

        Returns
        -------
        str or None
            Date in YYYY-MM-DD format, or None if parsing fails.
        """
        if not commence_time:
            return None

        try:
            # Handle both "Z" suffix and "+00:00" timezone formats
            cleaned = commence_time.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            # Fallback: try to extract just the date portion
            try:
                return commence_time[:10]  # "YYYY-MM-DD" from the front
            except (IndexError, TypeError):
                return None

    @staticmethod
    def _point_to_market_type(point: float) -> Optional[str]:
        """Map a totals point value to our canonical market_type enum.

        The Odds API returns the exact goal line (e.g., 2.5, 1.5, 3.5).
        We map these to our enum values.  Unsupported lines return None.

        Parameters
        ----------
        point : float
            The goal line from the totals outcome (e.g., 2.5).

        Returns
        -------
        str or None
            Canonical market_type (e.g., "OU25") or None if unsupported.
        """
        point_map = {
            1.5: "OU15",
            2.5: "OU25",
            3.5: "OU35",
        }
        # Use approximate comparison to handle floating point
        for target, market_type in point_map.items():
            if abs(point - target) < 0.01:
                return market_type
        return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Safely convert a value to float, returning None on failure.

        Handles None, empty strings, and non-numeric values gracefully.
        """
        if value is None:
            return None
        try:
            result = float(value)
            return result if result == result else None  # NaN check
        except (ValueError, TypeError):
            return None

    def _check_api_key(self) -> bool:
        """Verify that the API key is available.

        Returns False (and logs a warning) if THE_ODDS_API_KEY is not
        set in the environment.  This allows the pipeline to skip odds
        fetching gracefully without crashing.

        Returns
        -------
        bool
            True if API key is available, False otherwise.
        """
        if not self._api_key:
            logger.warning(
                "[the_odds_api] THE_ODDS_API_KEY environment variable "
                "not set — skipping odds fetch.  Get a free API key at "
                "https://the-odds-api.com/"
            )
            return False
        return True

    def _check_budget(self) -> bool:
        """Check if we have enough API budget remaining.

        If we've previously received budget information from the API
        headers and the remaining requests are below the hard stop
        threshold, refuse to make the request.  This preserves budget
        for critical pipeline runs.

        Returns
        -------
        bool
            True if OK to proceed, False if budget is too low.
        """
        if (
            self._requests_remaining is not None
            and self._requests_remaining < self._hard_stop_threshold
        ):
            logger.warning(
                "[the_odds_api] 🛑 API budget critically low: %d requests "
                "remaining (hard stop threshold: %d). Skipping to preserve "
                "budget for critical runs.",
                self._requests_remaining, self._hard_stop_threshold,
            )
            return False
        return True

    def _load_bookmaker_map(self) -> Dict[str, str]:
        """Load bookmaker name mapping from config.

        Reads ``config.settings.scraping.the_odds_api.bookmaker_map``
        and converts the ConfigNamespace to a plain dict.  Falls back
        to DEFAULT_BOOKMAKER_MAP if config section doesn't exist.

        Returns
        -------
        dict
            Mapping of API bookmaker key → display name.
        """
        bookie_map: Dict[str, str] = {}

        try:
            cfg_section = getattr(config.settings.scraping, "the_odds_api", None)
            if cfg_section is None:
                return DEFAULT_BOOKMAKER_MAP.copy()

            cfg_map = getattr(cfg_section, "bookmaker_map", None)
            if cfg_map is None:
                return DEFAULT_BOOKMAKER_MAP.copy()

            # ConfigNamespace stores attributes — iterate over them
            if hasattr(cfg_map, "__dict__"):
                for k, v in cfg_map.__dict__.items():
                    if not k.startswith("_"):
                        bookie_map[str(k)] = str(v)
            elif isinstance(cfg_map, dict):
                bookie_map = {str(k): str(v) for k, v in cfg_map.items()}

        except (AttributeError, TypeError) as exc:
            logger.debug(
                "[the_odds_api] Could not load bookmaker map from config: %s",
                exc,
            )

        # Merge with defaults — config values take priority
        merged = DEFAULT_BOOKMAKER_MAP.copy()
        merged.update(bookie_map)
        return merged

    def _save_raw_json(
        self,
        data: Any,
        league_name: str,
        data_type: str,
        season: str,
    ) -> Path:
        """Save raw API response as JSON for reproducibility.

        Every API response is saved to ``data/raw/`` before processing.
        This guarantees that if a parsing bug is found later, the original
        data is still on disk for reprocessing.

        Parameters
        ----------
        data : any
            The raw parsed JSON data (typically a list of dicts).
        league_name : str
            League short name (e.g., "EPL").
        data_type : str
            Type of data (e.g., "odds").
        season : str
            Season identifier (e.g., "2025-26").

        Returns
        -------
        Path
            Path to the saved JSON file.
        """
        raw_dir = PROJECT_ROOT / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        today = date.today().isoformat()
        filename = (
            f"{self.source_name}_{league_name}_{data_type}"
            f"_{season}_{today}.json"
        )
        filepath = raw_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.info(
            "[the_odds_api] Saved raw JSON → %s (%d items)",
            filepath, len(data) if isinstance(data, list) else 1,
        )
        return filepath
