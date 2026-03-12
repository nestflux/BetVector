"""
BetVector — odds-api.io Supplementary Odds Scraper (PC-15-02)
==============================================================
Fetches pre-match bookmaker odds from odds-api.io as a **fallback** when
The Odds API (the-odds-api.com) is out of monthly budget.

odds-api.io is a separate service with a generous free tier:
  - 100 requests/hour (resets hourly, no monthly cap ≈ 72K/month)
  - 250+ bookmakers including Bet365, FanDuel, DraftKings, Betway
  - All 6 BetVector leagues covered
  - Markets: ML (1X2), Over/Under, BTTS, Asian Handicap
  - Real decimal bookmaker odds (not predictions)
  - Free tier: 2 bookmakers per /odds request

API Details (v3):
  - Base URL: ``https://api.odds-api.io/v3``
  - Auth: ``apiKey`` query parameter from ``ODDS_API_IO_KEY`` env var
  - Workflow: ``GET /events`` (get fixtures) → ``GET /odds`` (get odds per event)
  - Rate limit: 100 requests/hour on free tier
  - Rate limit headers: ``X-Ratelimit-Remaining``, ``X-Ratelimit-Reset``

Key difference from The Odds API:
  The Odds API returns all events + odds in one call.
  odds-api.io requires: 1) fetch events list, 2) fetch odds per event.
  To stay within free tier, we batch up to 10 events in ``/odds/multi``.

Output DataFrame uses the **same schema** as TheOddsAPIScraper so that the
existing ``load_odds_the_odds_api()`` loader works unchanged.

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# League → odds-api.io League Slug Mapping
# ============================================================================
# odds-api.io uses league slugs like "england-premier-league" rather than
# sport keys like "soccer_epl".  The mapping below uses the league's
# ``short_name`` from config/leagues.yaml to look up the correct slug.

LEAGUE_TO_SLUG: Dict[str, str] = {
    "EPL": "england-premier-league",
    "Championship": "england-championship",
    "LaLiga": "spain-laliga",
    "Ligue1": "france-ligue-1",
    "Bundesliga": "germany-bundesliga",
    "SerieA": "italy-serie-a",
}

# ============================================================================
# Bookmaker Selection
# ============================================================================
# Free tier allows 2 bookmakers per /odds request.  We prioritise sharp
# bookmakers (Bet365 is widely available and well-calibrated) plus a
# US sportsbook for market breadth.
#
# These are the bookmaker names as returned by ``GET /bookmakers``.

DEFAULT_BOOKMAKERS = ["Bet365", "Betway"]

# ============================================================================
# Team Name Normalisation
# ============================================================================
# odds-api.io returns official team names with "FC"/"AFC" suffixes
# (e.g., "Burnley FC", "AFC Bournemouth").  We need to map these to
# canonical DB names from Football-Data.co.uk.
#
# We reuse the Odds API TEAM_NAME_MAP where names match, and add
# odds-api.io-specific mappings here.

TEAM_NAME_MAP: Dict[str, str] = {
    # ── EPL ──────────────────────────────────────────────────────────────
    # Canonical names MUST match the Team table in the DB exactly.
    # EPL teams use full names (from Football-Data.co.uk initial load).
    "Arsenal FC": "Arsenal",
    "Arsenal": "Arsenal",
    "Aston Villa FC": "Aston Villa",
    "Aston Villa": "Aston Villa",
    "AFC Bournemouth": "AFC Bournemouth",
    "Bournemouth": "AFC Bournemouth",
    "Brentford FC": "Brentford",
    "Brentford": "Brentford",
    "Brighton & Hove Albion FC": "Brighton & Hove Albion",
    "Brighton & Hove Albion": "Brighton & Hove Albion",
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Brighton": "Brighton & Hove Albion",
    "Burnley FC": "Burnley",
    "Burnley": "Burnley",
    "Chelsea FC": "Chelsea",
    "Chelsea": "Chelsea",
    "Crystal Palace FC": "Crystal Palace",
    "Crystal Palace": "Crystal Palace",
    "Everton FC": "Everton",
    "Everton": "Everton",
    "Fulham FC": "Fulham",
    "Fulham": "Fulham",
    "Ipswich Town FC": "Ipswich Town",
    "Ipswich Town": "Ipswich Town",
    "Leicester City FC": "Leicester City",
    "Leicester City": "Leicester City",
    "Liverpool FC": "Liverpool",
    "Liverpool": "Liverpool",
    "Manchester City FC": "Manchester City",
    "Manchester City": "Manchester City",
    "Manchester United FC": "Manchester United",
    "Manchester United": "Manchester United",
    "Newcastle United FC": "Newcastle United",
    "Newcastle United": "Newcastle United",
    "Newcastle": "Newcastle United",
    "Nottingham Forest FC": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    "Nott'm Forest": "Nottingham Forest",
    "Sheffield United FC": "Sheffield United",
    "Sheffield United": "Sheffield United",
    "Southampton FC": "Southampton",
    "Southampton": "Southampton",
    "Sunderland AFC": "Sunderland",
    "Sunderland": "Sunderland",
    "Tottenham Hotspur FC": "Tottenham Hotspur",
    "Tottenham Hotspur": "Tottenham Hotspur",
    "Tottenham": "Tottenham Hotspur",
    "Spurs": "Tottenham Hotspur",
    "West Ham United FC": "West Ham United",
    "West Ham United": "West Ham United",
    "West Ham": "West Ham United",
    "Wolverhampton Wanderers FC": "Wolverhampton Wanderers",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",
    "Wolverhampton": "Wolverhampton Wanderers",
    "Wolves": "Wolverhampton Wanderers",
    "Leeds United FC": "Leeds United",
    "Leeds United": "Leeds United",
    "Norwich City FC": "Norwich City",
    "Norwich City": "Norwich City",
    "Watford FC": "Watford",
    "Watford": "Watford",
    "West Bromwich Albion FC": "West Bromwich Albion",
    "West Bromwich Albion": "West Bromwich Albion",
    "West Brom": "West Bromwich Albion",
    "Luton Town FC": "Luton Town",
    "Luton Town": "Luton Town",

    # ── Championship (ELC) ───────────────────────────────────────────────
    "Birmingham City FC": "Birmingham",
    "Blackburn Rovers FC": "Blackburn",
    "Blackburn Rovers": "Blackburn",
    "Bristol City FC": "Bristol City",
    "Charlton Athletic FC": "Charlton",
    "Charlton Athletic": "Charlton",
    "Coventry City FC": "Coventry",
    "Coventry City": "Coventry",
    "Derby County FC": "Derby",
    "Derby County": "Derby",
    "Hull City AFC": "Hull",
    "Hull City": "Hull",
    "Middlesbrough FC": "Middlesbrough",
    "Millwall FC": "Millwall",
    "Oxford United FC": "Oxford",
    "Oxford United": "Oxford",
    "Portsmouth FC": "Portsmouth",
    "Preston North End FC": "Preston",
    "Preston North End": "Preston",
    "Queens Park Rangers FC": "QPR",
    "Queens Park Rangers": "QPR",
    "QPR": "QPR",
    "Sheffield Wednesday FC": "Sheffield Weds",
    "Sheffield Wednesday": "Sheffield Weds",
    "Stoke City FC": "Stoke",
    "Stoke City": "Stoke",
    "Swansea City AFC": "Swansea",
    "Swansea City": "Swansea",
    "Wrexham AFC": "Wrexham",
    "Plymouth Argyle FC": "Plymouth",
    "Plymouth Argyle": "Plymouth",
    "Barnsley FC": "Barnsley",
    "Cardiff City FC": "Cardiff",
    "Cardiff City": "Cardiff",
    "Peterborough United FC": "Peterboro",
    "Reading FC": "Reading",
    "Rotherham United FC": "Rotherham",
    "Wigan Athletic FC": "Wigan",

    # ── La Liga (PD) ─────────────────────────────────────────────────────
    "Athletic Bilbao": "Ath Bilbao",
    "Athletic Club": "Ath Bilbao",
    "Atletico Madrid": "Ath Madrid",
    "Club Atletico de Madrid": "Ath Madrid",
    "Deportivo Alaves": "Alaves",
    "Deportivo Alavés": "Alaves",
    "FC Barcelona": "Barcelona",
    "Barcelona": "Barcelona",
    "Getafe CF": "Getafe",
    "Getafe": "Getafe",
    "Girona FC": "Girona",
    "Girona": "Girona",
    "Levante UD": "Levante",
    "Levante": "Levante",
    "CA Osasuna": "Osasuna",
    "Osasuna": "Osasuna",
    "RCD Mallorca": "Mallorca",
    "Mallorca": "Mallorca",
    "RCD Espanyol": "Espanol",
    "Espanyol Barcelona": "Espanol",
    "Espanyol": "Espanol",
    "Rayo Vallecano": "Vallecano",
    "Rayo Vallecano de Madrid": "Vallecano",
    "Real Betis": "Betis",
    "Real Betis Balompie": "Betis",
    "Real Betis Seville": "Betis",
    "Real Madrid": "Real Madrid",
    "Real Madrid CF": "Real Madrid",
    "Real Sociedad": "Sociedad",
    "Real Sociedad de Futbol": "Sociedad",
    "Real Sociedad San Sebastian": "Sociedad",
    "RC Celta de Vigo": "Celta",
    "Celta Vigo": "Celta",
    "Sevilla FC": "Sevilla",
    "Sevilla": "Sevilla",
    "Valencia CF": "Valencia",
    "Valencia": "Valencia",
    "Villarreal CF": "Villarreal",
    "Villarreal": "Villarreal",
    "Elche CF": "Elche",
    "Cadiz CF": "Cadiz",
    "Granada CF": "Granada",
    "UD Almeria": "Almeria",
    "UD Las Palmas": "Las Palmas",
    "Las Palmas": "Las Palmas",
    "CD Leganes": "Leganes",
    "Leganes": "Leganes",
    "Real Valladolid CF": "Valladolid",
    "Real Valladolid": "Valladolid",
    "Real Oviedo": "Oviedo",

    # ── Ligue 1 (FL1) ───────────────────────────────────────────────────
    "Paris Saint-Germain FC": "Paris SG",
    "Paris Saint-Germain": "Paris SG",
    "PSG": "Paris SG",
    "Olympique Lyonnais": "Lyon",
    "Olympique Lyon": "Lyon",
    "Lyon": "Lyon",
    "Olympique de Marseille": "Marseille",
    "Olympique Marseille": "Marseille",
    "Marseille": "Marseille",
    "AS Monaco FC": "Monaco",
    "AS Monaco": "Monaco",
    "Monaco": "Monaco",
    "Lille OSC": "Lille",
    "Lille": "Lille",
    "OGC Nice": "Nice",
    "Nice": "Nice",
    "Stade Rennais FC 1901": "Rennes",
    "Stade Rennais FC": "Rennes",
    "Stade Rennais": "Rennes",
    "Rennes": "Rennes",
    "Stade Brestois 29": "Brest",
    "Stade Brest 29": "Brest",
    "Brest": "Brest",
    "RC Strasbourg Alsace": "Strasbourg",
    "Strasbourg": "Strasbourg",
    "RC Lens": "Lens",
    "Racing Club de Lens": "Lens",
    "Racing Club De Lens": "Lens",
    "Lens": "Lens",
    "Toulouse FC": "Toulouse",
    "Toulouse": "Toulouse",
    "FC Nantes": "Nantes",
    "Nantes": "Nantes",
    "FC Lorient": "Lorient",
    "Lorient": "Lorient",
    "Montpellier HSC": "Montpellier",
    "Montpellier": "Montpellier",
    "Stade de Reims": "Reims",
    "Reims": "Reims",
    "AJ Auxerre": "Auxerre",
    "Auxerre": "Auxerre",
    "Angers SCO": "Angers",
    "Le Havre AC": "Le Havre",
    "Le Havre": "Le Havre",
    "AS Saint-Etienne": "St Etienne",
    "Saint-Etienne": "St Etienne",
    "Clermont Foot 63": "Clermont",
    "FC Metz": "Metz",
    "Metz": "Metz",
    "Paris FC": "Paris FC",

    # ── Bundesliga (BL1) ─────────────────────────────────────────────────
    "FC Bayern Munich": "Bayern Munich",
    "FC Bayern Munchen": "Bayern Munich",
    "Bayern Munich": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "Dortmund": "Dortmund",
    "RB Leipzig": "RB Leipzig",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Bayer Leverkusen": "Leverkusen",
    "Leverkusen": "Leverkusen",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "VfB Stuttgart": "Stuttgart",
    "Stuttgart": "Stuttgart",
    "VfL Wolfsburg": "Wolfsburg",
    "Wolfsburg": "Wolfsburg",
    "SC Freiburg": "Freiburg",
    "Freiburg": "Freiburg",
    "Borussia Monchengladbach": "M'gladbach",
    "Borussia Mgladbach": "M'gladbach",
    "Borussia M'gladbach": "M'gladbach",
    "1. FC Union Berlin": "Union Berlin",
    "Union Berlin": "Union Berlin",
    "FC Augsburg": "Augsburg",
    "Augsburg": "Augsburg",
    "1. FSV Mainz 05": "Mainz",
    "Mainz 05": "Mainz",
    "Mainz": "Mainz",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    "TSG Hoffenheim": "Hoffenheim",
    "Hoffenheim": "Hoffenheim",
    "SV Werder Bremen": "Werder Bremen",
    "Werder Bremen": "Werder Bremen",
    "1. FC Heidenheim 1846": "Heidenheim",
    "1. FC Heidenheim": "Heidenheim",
    "Heidenheim": "Heidenheim",
    "FC St. Pauli 1910": "St Pauli",
    "FC St. Pauli": "St Pauli",
    "St. Pauli": "St Pauli",
    "1. FC Koln": "FC Koln",
    "1. FC Cologne": "FC Koln",
    "FC Koln": "FC Koln",
    "Holstein Kiel": "Holstein Kiel",
    "VfL Bochum 1848": "Bochum",
    "VfL Bochum": "Bochum",
    "Hertha BSC": "Hertha",
    "FC Schalke 04": "Schalke 04",
    "Schalke 04": "Schalke 04",
    "SV Darmstadt 98": "Darmstadt",
    "Darmstadt": "Darmstadt",
    "Hamburger SV": "Hamburg",

    # ── Serie A (SA) ─────────────────────────────────────────────────────
    "AC Milan": "Milan",
    "Milan": "Milan",
    "FC Internazionale Milano": "Inter",
    "Inter Milan": "Inter",
    "Inter Milano": "Inter",
    "Juventus FC": "Juventus",
    "Juventus": "Juventus",
    "SSC Napoli": "Napoli",
    "Napoli": "Napoli",
    "AS Roma": "Roma",
    "Roma": "Roma",
    "SS Lazio": "Lazio",
    "Lazio Rome": "Lazio",
    "Lazio": "Lazio",
    "Atalanta BC": "Atalanta",
    "Atalanta": "Atalanta",
    "ACF Fiorentina": "Fiorentina",
    "Fiorentina": "Fiorentina",
    "Bologna FC 1909": "Bologna",
    "Bologna": "Bologna",
    "Torino FC": "Torino",
    "Torino": "Torino",
    "Udinese Calcio": "Udinese",
    "Udinese": "Udinese",
    "Cagliari Calcio": "Cagliari",
    "Cagliari": "Cagliari",
    "Genoa CFC": "Genoa",
    "Genoa": "Genoa",
    "Hellas Verona FC": "Verona",
    "Hellas Verona": "Verona",
    "US Lecce": "Lecce",
    "Lecce": "Lecce",
    "US Sassuolo Calcio": "Sassuolo",
    "Sassuolo Calcio": "Sassuolo",
    "Sassuolo": "Sassuolo",
    "Empoli FC": "Empoli",
    "Empoli": "Empoli",
    "UC Sampdoria": "Sampdoria",
    "Sampdoria": "Sampdoria",
    "US Salernitana 1919": "Salernitana",
    "Salernitana": "Salernitana",
    "Spezia Calcio": "Spezia",
    "Spezia": "Spezia",
    "Venezia FC": "Venezia",
    "Venezia": "Venezia",
    "Parma Calcio 1913": "Parma",
    "Parma Calcio": "Parma",
    "Parma": "Parma",
    "Como 1907": "Como",
    "Como": "Como",
    "AC Monza": "Monza",
    "Monza": "Monza",
    "AC Pisa 1909": "Pisa",
    "Pisa SC": "Pisa",
    "Pisa": "Pisa",
    "US Cremonese": "Cremonese",
    "Frosinone Calcio": "Frosinone",
    "Frosinone": "Frosinone",
}


class OddsApiIoScraper(BaseScraper):
    """Scraper for odds-api.io — supplementary odds from 250+ bookmakers.

    Used as an automatic fallback when The Odds API (the-odds-api.com) is
    out of monthly budget (500 req/month on free tier).  odds-api.io has a
    much more generous free tier: 100 requests/hour, no monthly cap.

    The scraper produces a DataFrame with the **same output schema** as
    ``TheOddsAPIScraper``, so the existing ``load_odds_the_odds_api()``
    loader works unchanged.

    Output columns::

        date, home_team, away_team, bookmaker, market_type, selection, odds_decimal

    Workflow:
      1. ``GET /events`` — fetch upcoming fixtures for the league
      2. ``GET /odds/multi`` — fetch odds for up to 10 events at once
      3. Parse ML (1X2) and Over/Under markets into flat records
      4. Map team names to canonical DB names
      5. Return DataFrame matching TheOddsAPIScraper output schema

    Master Plan refs: MP §5 Data Sources
    """

    # Domain for rate limiting — 2s between requests (BaseScraper default)
    DOMAIN = "api.odds-api.io"

    @property
    def source_name(self) -> str:
        """Identifier for raw file saving and logging."""
        return "odds_api_io"

    def __init__(self) -> None:
        super().__init__()

        # API key from environment variable
        self._api_key: Optional[str] = os.environ.get("ODDS_API_IO_KEY", "").strip() or None

        # Base URL from config or default
        try:
            self._base_url = str(
                getattr(config.settings.scraping.odds_api_io,
                        "base_url", "https://api.odds-api.io/v3")
            )
        except (AttributeError, TypeError):
            self._base_url = "https://api.odds-api.io/v3"

        # Bookmaker selection (free tier: max 2 per request)
        try:
            bookie_list = getattr(
                config.settings.scraping.odds_api_io,
                "bookmakers", None
            )
            if bookie_list:
                self._bookmakers = list(bookie_list)
            else:
                self._bookmakers = DEFAULT_BOOKMAKERS
        except (AttributeError, TypeError):
            self._bookmakers = DEFAULT_BOOKMAKERS

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch pre-match odds for all upcoming matches in a league.

        Parameters
        ----------
        league_config : ConfigNamespace
            League configuration from ``config.get_active_leagues()``.
            Must have ``short_name`` (e.g., "EPL").
        season : str
            Season identifier (e.g., "2025-26").  Used for logging only —
            odds-api.io always returns current upcoming fixtures.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: date, home_team, away_team, bookmaker,
            market_type, selection, odds_decimal.  Empty DataFrame if no
            odds are available or the API key is missing.
        """
        league_name = getattr(league_config, "short_name", "unknown")

        # --- Guard: API key required ---
        if not self._api_key:
            logger.warning(
                "[%s] ODDS_API_IO_KEY not set — skipping. "
                "Register for free at https://odds-api.io",
                self.source_name,
            )
            return pd.DataFrame()

        # --- Guard: league must have a slug mapping ---
        league_slug = LEAGUE_TO_SLUG.get(league_name)
        if not league_slug:
            logger.info(
                "[%s] No odds-api.io league slug for '%s' — skipping.",
                self.source_name, league_name,
            )
            return pd.DataFrame()

        # Step 1: Fetch upcoming events for this league
        events = self._fetch_events(league_slug, league_name)
        if not events:
            logger.info(
                "[%s] No upcoming events for %s from odds-api.io",
                self.source_name, league_name,
            )
            return pd.DataFrame()

        logger.info(
            "[%s] Found %d upcoming events for %s",
            self.source_name, len(events), league_name,
        )

        # Step 2: Fetch odds for all events (batched via /odds/multi)
        all_records: List[Dict[str, Any]] = []
        event_ids = [e["id"] for e in events]
        bookmakers_str = ",".join(self._bookmakers)

        # /odds/multi supports up to 10 event IDs per request
        batch_size = 10
        for i in range(0, len(event_ids), batch_size):
            batch = event_ids[i : i + batch_size]
            batch_str = ",".join(str(eid) for eid in batch)

            try:
                # Build event lookup for team names
                event_map = {
                    e["id"]: e for e in events
                    if e["id"] in batch
                }

                resp = self._request_with_retry(
                    url=f"{self._base_url}/odds/multi",
                    params={
                        "apiKey": self._api_key,
                        "eventIds": batch_str,
                        "bookmakers": bookmakers_str,
                    },
                    domain=self.DOMAIN,
                )

                if resp is None:
                    logger.warning(
                        "[%s] Failed to fetch odds batch %d-%d for %s",
                        self.source_name, i, i + len(batch), league_name,
                    )
                    continue

                data = resp.json()

                # Log rate limit info from headers
                remaining = resp.headers.get("X-Ratelimit-Remaining")
                if remaining is not None:
                    logger.info(
                        "[%s] odds-api.io rate limit: %s requests remaining this hour",
                        self.source_name, remaining,
                    )

                # Parse response — can be a list of events or a single event
                events_data = data if isinstance(data, list) else [data]

                for event_data in events_data:
                    records = self._parse_event_odds(event_data, event_map)
                    all_records.extend(records)

            except Exception as e:
                logger.error(
                    "[%s] Error fetching odds batch for %s: %s",
                    self.source_name, league_name, e,
                )
                continue

        if not all_records:
            logger.info(
                "[%s] No odds records parsed for %s",
                self.source_name, league_name,
            )
            return pd.DataFrame()

        df = pd.DataFrame(all_records)

        # Save raw data for reproducibility
        self.save_raw(df, league_name, season)

        logger.info(
            "[%s] Scraped %d odds records for %s (%d events, %d bookmakers)",
            self.source_name, len(df), league_name,
            df[["home_team", "away_team"]].drop_duplicates().shape[0],
            df["bookmaker"].nunique(),
        )

        return df

    # ====================================================================
    # Private helpers
    # ====================================================================

    def _fetch_events(
        self, league_slug: str, league_name: str,
    ) -> List[Dict[str, Any]]:
        """Fetch upcoming (pending) events for a league.

        Returns a list of event dicts from the /events endpoint.
        Each dict has: id, home, away, homeId, awayId, date, status, etc.
        """
        try:
            resp = self._request_with_retry(
                url=f"{self._base_url}/events",
                params={
                    "apiKey": self._api_key,
                    "sport": "football",
                    "league": league_slug,
                    "status": "pending",
                },
                domain=self.DOMAIN,
            )
            if resp is None:
                return []

            data = resp.json()

            # Response is a list of events
            if isinstance(data, list):
                return data
            # Or could be paginated dict
            elif isinstance(data, dict) and "data" in data:
                return data["data"]
            else:
                logger.warning(
                    "[%s] Unexpected events response format for %s: %s",
                    self.source_name, league_name, type(data).__name__,
                )
                return []

        except Exception as e:
            logger.error(
                "[%s] Failed to fetch events for %s: %s",
                self.source_name, league_name, e,
            )
            return []

    def _parse_event_odds(
        self,
        event_data: Dict[str, Any],
        event_map: Dict[int, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Parse odds for a single event into flat records.

        odds-api.io returns odds in this structure::

            {
              "id": 12345,
              "home": "Burnley FC",
              "away": "AFC Bournemouth",
              "date": "2026-03-14T15:00:00Z",
              "bookmakers": {
                "Bet365": [
                  {"name": "ML", "odds": [{"home": "4.20", "draw": "3.75", "away": "1.83"}]},
                  {"name": "Totals", "odds": [{"hdp": 2.5, "over": "1.90", "under": "1.95"}]}
                ]
              }
            }

        We extract:
          - ML (Match Line = 1X2) → market_type "h2h", selections: home/draw/away
          - Totals (Over/Under) → market_type "totals", selections: Over/Under {line}

        Returns list of dicts matching TheOddsAPIScraper output schema.
        """
        records: List[Dict[str, Any]] = []

        # Get match date
        date_str = self._parse_date(event_data.get("date", ""))
        if not date_str:
            return records

        # Get and map team names
        home_raw = event_data.get("home", "")
        away_raw = event_data.get("away", "")
        home_team = self._map_team_name(home_raw)
        away_team = self._map_team_name(away_raw)

        # Parse bookmaker odds
        bookmakers = event_data.get("bookmakers", {})
        if not isinstance(bookmakers, dict):
            return records

        for bookie_name, markets in bookmakers.items():
            if not isinstance(markets, list):
                continue

            for market in markets:
                market_name = market.get("name", "")
                odds_list = market.get("odds", [])

                if not odds_list:
                    continue

                # ML (Match Line) = 1X2 market
                # Map to canonical DB values: market_type="1X2",
                # selection in ("home", "draw", "away")
                # Matches TheOddsAPIScraper output format exactly.
                if market_name == "ML":
                    for odds_entry in odds_list:
                        home_odds = self._safe_float(odds_entry.get("home"))
                        draw_odds = self._safe_float(odds_entry.get("draw"))
                        away_odds = self._safe_float(odds_entry.get("away"))

                        if home_odds:
                            records.append({
                                "date": date_str,
                                "home_team": home_team,
                                "away_team": away_team,
                                "bookmaker": bookie_name,
                                "market_type": "1X2",
                                "selection": "home",
                                "odds_decimal": home_odds,
                            })
                        if draw_odds:
                            records.append({
                                "date": date_str,
                                "home_team": home_team,
                                "away_team": away_team,
                                "bookmaker": bookie_name,
                                "market_type": "1X2",
                                "selection": "draw",
                                "odds_decimal": draw_odds,
                            })
                        if away_odds:
                            records.append({
                                "date": date_str,
                                "home_team": home_team,
                                "away_team": away_team,
                                "bookmaker": bookie_name,
                                "market_type": "1X2",
                                "selection": "away",
                                "odds_decimal": away_odds,
                            })

                # Totals (Over/Under) market
                # Map to canonical DB values: market_type="OU15"/"OU25"/"OU35",
                # selection in ("over", "under")
                # Goal line (hdp) determines which specific OU market.
                # Matches TheOddsAPIScraper._point_to_market_type() mapping.
                elif market_name in ("Totals", "Over/Under"):
                    for odds_entry in odds_list:
                        line = odds_entry.get("hdp", 2.5)
                        over_odds = self._safe_float(odds_entry.get("over"))
                        under_odds = self._safe_float(odds_entry.get("under"))

                        # Map goal line to canonical market_type enum
                        market_type_canonical = self._point_to_market_type(line)
                        if market_type_canonical is None:
                            # Unsupported goal line (e.g., 1.0, 4.5) — skip
                            continue

                        if over_odds:
                            records.append({
                                "date": date_str,
                                "home_team": home_team,
                                "away_team": away_team,
                                "bookmaker": bookie_name,
                                "market_type": market_type_canonical,
                                "selection": "over",
                                "odds_decimal": over_odds,
                            })
                        if under_odds:
                            records.append({
                                "date": date_str,
                                "home_team": home_team,
                                "away_team": away_team,
                                "bookmaker": bookie_name,
                                "market_type": market_type_canonical,
                                "selection": "under",
                                "odds_decimal": under_odds,
                            })

        return records

    def _map_team_name(self, api_name: str) -> str:
        """Map an odds-api.io team name to the canonical DB name.

        Three-tier strategy:
          1. Explicit lookup in TEAM_NAME_MAP
          2. Fuzzy matching via difflib (cutoff=0.7)
          3. Raw name passthrough with warning
        """
        if not api_name:
            return api_name

        # Tier 1: Exact match
        canonical = TEAM_NAME_MAP.get(api_name)
        if canonical:
            return canonical

        # Tier 2: Fuzzy fallback
        all_canonical = list(set(TEAM_NAME_MAP.values()))
        matches = get_close_matches(api_name, all_canonical, n=1, cutoff=0.7)
        if matches:
            logger.info(
                "[%s] Fuzzy matched team '%s' → '%s'",
                self.source_name, api_name, matches[0],
            )
            return matches[0]

        # Tier 3: Passthrough with warning
        logger.warning(
            "[%s] Unmapped team '%s' — using raw name. "
            "Add mapping to TEAM_NAME_MAP in odds_api_io.py",
            self.source_name, api_name,
        )
        return api_name

    @staticmethod
    def _point_to_market_type(point) -> Optional[str]:
        """Map a totals goal line to our canonical market_type enum.

        odds-api.io returns the exact goal line (e.g., 2.5, 1.5, 3.5)
        in the "hdp" field.  We map these to our enum values that match
        the CHECK constraint on the Odds table: OU15, OU25, OU35.
        Unsupported lines (e.g., 0.5, 4.5) return None and are skipped.

        Mirrors TheOddsAPIScraper._point_to_market_type() for consistency.
        """
        if point is None:
            return None
        try:
            p = float(point)
        except (ValueError, TypeError):
            return None
        # Map common goal lines to canonical market_type enum values
        point_map = {
            1.5: "OU15",
            2.5: "OU25",
            3.5: "OU35",
        }
        for target, market_type in point_map.items():
            if abs(p - target) < 0.01:
                return market_type
        return None

    @staticmethod
    def _parse_date(date_str: str) -> Optional[str]:
        """Parse ISO 8601 date string into YYYY-MM-DD format.

        odds-api.io returns dates like "2026-03-14T15:00:00Z".
        We extract just the date portion for consistency with
        TheOddsAPIScraper output.
        """
        if not date_str:
            return None
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            # Fallback: try to extract date portion directly
            try:
                return date_str[:10]
            except (IndexError, TypeError):
                return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Safely convert a value to float, returning None on failure.

        odds-api.io returns odds as strings (e.g., "4.200") that need
        to be converted to floats for storage in the Odds table.
        """
        if value is None:
            return None
        try:
            f = float(value)
            # Sanity check: odds must be > 1.0 (decimal format)
            return f if f > 1.0 else None
        except (ValueError, TypeError):
            return None
