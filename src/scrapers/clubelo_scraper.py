"""
BetVector — ClubElo Scraper (E21-01)
====================================
Fetches Elo ratings from the free ClubElo API (http://api.clubelo.com).

ClubElo provides daily Elo ratings for football clubs worldwide.  Elo ratings
are a strength-of-schedule-adjusted measure of team quality — a team that
beats strong opponents gains more rating points than one that beats weak ones.

**Why Elo matters for prediction:**
  - Captures long-term team quality (rolling form is short-term noise)
  - Especially valuable early in the season when rolling stats are sparse
  - Promoted teams start with lower Elo — this encodes "newly promoted" signal
  - Elo difference between teams is a strong predictor of match outcome
  - Expected Brier improvement: 1-8% (larger for promoted teams, early season)

**API endpoints:**
  - ``GET /YYYY-MM-DD`` → CSV of all clubs' ratings for that date
  - ``GET /ClubName`` → full rating history for a single club

**CSV columns:** Rank, Club, Country, Level, Elo, From, To

**Rate limiting:** 2-second minimum between requests (inherited from BaseScraper).
No API key required — the API is completely free and public.

Master Plan refs: MP §5 Architecture → Data Sources
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Any, Dict, List, Optional

import pandas as pd

from pathlib import Path

from src.config import PROJECT_ROOT
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Domain & API Configuration
# ============================================================================

DOMAIN = "api.clubelo.com"
BASE_URL = "http://api.clubelo.com"

# ClubElo uses short team names — map them to BetVector canonical names.
# This covers all EPL 2024-25 and 2025-26 teams + common historical teams.
# ClubElo names are case-sensitive and use abbreviated forms.
TEAM_NAME_MAP: Dict[str, str] = {
    # Maps ClubElo club names → BetVector canonical DB names.
    # BetVector DB uses full official names (e.g., "AFC Bournemouth",
    # "Wolverhampton Wanderers").  ClubElo uses shorter forms.
    # Verified against actual API response for 2026-03-02 and DB teams table.
    #
    # Current EPL 2025-26 (20 teams)
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "AFC Bournemouth",
    "Brentford": "Brentford",
    "Brighton": "Brighton & Hove Albion",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Forest": "Nottingham Forest",
    "Leeds": "Leeds United",
    "Liverpool": "Liverpool",
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Newcastle": "Newcastle United",
    "Sunderland": "Sunderland",
    "Tottenham": "Tottenham Hotspur",
    "West Ham": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
    # Recent EPL teams (2020-2025) — may appear in historical Elo lookups
    "Leicester": "Leicester City",
    "Southampton": "Southampton",
    "Ipswich": "Ipswich Town",
    "Sheffield United": "Sheffield United",
    "Luton": "Luton Town",
    "West Brom": "West Bromwich Albion",
    "Watford": "Watford",
    "Norwich": "Norwich City",
    # Legacy ClubElo names (older API data may use concatenated forms)
    "AstonVilla": "Aston Villa",
    "CrystalPalace": "Crystal Palace",
    "ManCity": "Manchester City",
    "ManUtd": "Manchester United",
    "NottmForest": "Nottingham Forest",
    "WestHam": "West Ham United",
    "SheffieldUtd": "Sheffield United",
    "WestBrom": "West Bromwich Albion",

    # -------------------------------------------------------------------------
    # La Liga teams (E36-02)
    # ClubElo names verified against API for 2022-23, 2023-24, 2024-25 seasons.
    # DB canonical names follow Football-Data.co.uk (primary match data source).
    # -------------------------------------------------------------------------
    # 2024-25 La Liga (20 teams)
    "Real Madrid": "Real Madrid",
    "Barcelona": "Barcelona",
    "Atletico": "Ath Madrid",          # ClubElo: "Atletico" → FD.co.uk: "Ath Madrid"
    "Girona": "Girona",
    "Villarreal": "Villarreal",
    "Bilbao": "Ath Bilbao",            # ClubElo: "Bilbao" → FD.co.uk: "Ath Bilbao"
    "Sociedad": "Sociedad",
    "Betis": "Betis",
    "Sevilla": "Sevilla",
    "Celta": "Celta",
    "Alaves": "Alaves",
    "Mallorca": "Mallorca",
    "Valencia": "Valencia",
    "Osasuna": "Osasuna",
    "Getafe": "Getafe",
    "Rayo Vallecano": "Vallecano",     # ClubElo: "Rayo Vallecano" → FD.co.uk: "Vallecano"
    "Espanyol": "Espanol",             # ClubElo: "Espanyol" → FD.co.uk: "Espanol"
    "Valladolid": "Valladolid",
    "Las Palmas": "Las Palmas",
    "Leganes": "Leganes",
    # Historical La Liga teams (relegated during 2020-2024 seasons)
    "Almeria": "Almeria",
    "Cadiz": "Cadiz",
    "Eibar": "Eibar",                  # E38-01: relegated after 2020-21
    "Elche": "Elche",
    "Granada": "Granada",
    "Huesca": "Huesca",                # E38-01: in La Liga 2020-21 only
    "Levante": "Levante",              # E38-01: relegated after 2021-22

    # -------------------------------------------------------------------------
    # Championship teams (E38-01)
    # ClubElo uses short names — same as Football-Data.co.uk pass-through names
    # for Championship teams.  Teams that also appear in EPL with a DIFFERENT
    # canonical name (e.g., ClubElo "Leeds" → EPL "Leeds United") are NOT
    # duplicated here — they get Elo via their EPL team record.
    #
    # Championship-only teams (never in EPL during 2020-2026 with different
    # name) get their own entries here so the feature engineer can use Elo.
    # -------------------------------------------------------------------------
    "Barnsley": "Barnsley",
    "Birmingham": "Birmingham",
    "Blackburn": "Blackburn",
    "Blackpool": "Blackpool",
    "Bristol City": "Bristol City",
    "Cardiff": "Cardiff",
    "Coventry": "Coventry",
    "Derby": "Derby",
    "Huddersfield": "Huddersfield",
    "Hull": "Hull",
    "Middlesbrough": "Middlesbrough",
    "Millwall": "Millwall",
    "Oxford": "Oxford",                 # 2024-25+
    "Peterboro": "Peterboro",
    "Plymouth": "Plymouth",             # 2023-24+
    "Portsmouth": "Portsmouth",         # 2024-25+
    "Preston": "Preston",
    "QPR": "QPR",
    "Reading": "Reading",
    "Rotherham": "Rotherham",
    "Sheffield Weds": "Sheffield Weds",
    "Stoke": "Stoke",
    "Swansea": "Swansea",
    "Wycombe": "Wycombe",

    # -------------------------------------------------------------------------
    # Ligue 1 teams (PC-08-02)
    # ClubElo French team names — map to Football-Data.co.uk canonical DB names.
    # 27 unique teams across 2020-21 to 2025-26 seasons.
    # ClubElo covers French Level 1 (Ligue 1) and Level 2 (Ligue 2) for
    # relegated teams, so all teams have Elo coverage.
    # -------------------------------------------------------------------------
    "Ajaccio": "Ajaccio",                    # 2022-23
    "Angers": "Angers",
    "Auxerre": "Auxerre",
    "Bordeaux": "Bordeaux",                  # 2020-21, 2021-22
    "Brest": "Brest",
    "Clermont": "Clermont",                  # 2021-22, 2022-23, 2023-24
    "Dijon": "Dijon",                        # 2020-21
    "Le Havre": "Le Havre",                  # 2023-24+
    "Lens": "Lens",
    "Lille": "Lille",
    "Lorient": "Lorient",
    "Lyon": "Lyon",
    "Marseille": "Marseille",
    "Metz": "Metz",
    "Monaco": "Monaco",
    "Montpellier": "Montpellier",
    "Nantes": "Nantes",
    "Nice": "Nice",
    "Nimes": "Nimes",                        # 2020-21
    "Paris FC": "Paris FC",                  # 2025-26 (promoted)
    "PSG": "Paris SG",                       # ClubElo: "PSG" → FD: "Paris SG"
    "Reims": "Reims",
    "Rennes": "Rennes",
    "Saint-Etienne": "St Etienne",           # ClubElo: "Saint-Etienne" → FD: "St Etienne"
    "Strasbourg": "Strasbourg",
    "Toulouse": "Toulouse",
    "Troyes": "Troyes",                      # 2021-22, 2022-23

    # -------------------------------------------------------------------------
    # Bundesliga teams (E38-03)
    # ClubElo uses short German names — map to Football-Data.co.uk canonical
    # DB names.  25 unique teams across 2020-21 to 2025-26 seasons.
    # -------------------------------------------------------------------------
    # Teams with different ClubElo vs FD names:
    "Bayern": "Bayern Munich",              # ClubElo: "Bayern" → FD: "Bayern Munich"
    "Frankfurt": "Ein Frankfurt",          # ClubElo: "Frankfurt" → FD: "Ein Frankfurt"
    "Fuerth": "Greuther Furth",            # ClubElo: "Fuerth" → FD: "Greuther Furth" (2021-22)
    "Gladbach": "M'gladbach",              # ClubElo: "Gladbach" → FD: "M'gladbach"
    "Holstein": "Holstein Kiel",           # ClubElo: "Holstein" → FD: "Holstein Kiel" (2024-25)
    "Koeln": "FC Koln",                    # ClubElo: "Koeln" → FD: "FC Koln"
    "Schalke": "Schalke 04",              # ClubElo: "Schalke" → FD: "Schalke 04"
    "Werder": "Werder Bremen",             # ClubElo: "Werder" → FD: "Werder Bremen"
    # Teams with matching ClubElo & FD names (identity):
    "Augsburg": "Augsburg",
    "Bielefeld": "Bielefeld",              # 2020-21, 2021-22
    "Bochum": "Bochum",                    # 2021-22 through 2024-25
    "Darmstadt": "Darmstadt",              # 2023-24
    "Dortmund": "Dortmund",
    "Freiburg": "Freiburg",
    "Hamburg": "Hamburg",                   # 2025-26
    "Heidenheim": "Heidenheim",            # 2023-24+
    "Hertha": "Hertha",                    # 2020-21 through 2022-23
    "Hoffenheim": "Hoffenheim",
    "Leverkusen": "Leverkusen",
    "Mainz": "Mainz",
    "RB Leipzig": "RB Leipzig",
    "St Pauli": "St Pauli",               # 2024-25, 2025-26
    "Stuttgart": "Stuttgart",
    "Union Berlin": "Union Berlin",
    "Wolfsburg": "Wolfsburg",

    # -------------------------------------------------------------------------
    # Serie A teams (E38-04)
    # ClubElo Italian team names match Football-Data.co.uk exactly (identity).
    # 29 unique teams across 2020-21 to 2025-26 seasons.
    # Covers Level 1 (Serie A) and Level 2 (Serie B) for relegated teams.
    # -------------------------------------------------------------------------
    "Atalanta": "Atalanta",
    "Benevento": "Benevento",             # 2020-21
    "Bologna": "Bologna",
    "Cagliari": "Cagliari",
    "Como": "Como",                       # 2024-25+
    "Cremonese": "Cremonese",             # 2022-23, 2025-26
    "Crotone": "Crotone",                 # 2020-21
    "Empoli": "Empoli",
    "Fiorentina": "Fiorentina",
    "Frosinone": "Frosinone",             # 2023-24
    "Genoa": "Genoa",
    "Inter": "Inter",
    "Juventus": "Juventus",
    "Lazio": "Lazio",
    "Lecce": "Lecce",                     # 2022-23+
    "Milan": "Milan",
    "Monza": "Monza",                     # 2022-23, 2023-24, 2024-25
    "Napoli": "Napoli",
    "Parma": "Parma",                     # 2020-21, 2024-25+
    "Pisa": "Pisa",                       # 2025-26
    "Roma": "Roma",
    "Salernitana": "Salernitana",         # 2021-22, 2022-23, 2023-24
    "Sampdoria": "Sampdoria",
    "Sassuolo": "Sassuolo",
    "Spezia": "Spezia",                   # 2020-21, 2021-22, 2022-23
    "Torino": "Torino",
    "Udinese": "Udinese",
    "Venezia": "Venezia",                 # 2021-22, 2024-25
    "Verona": "Verona",
}


class ClubEloScraper(BaseScraper):
    """Fetches Elo ratings from the ClubElo API.

    Two modes of operation:

    1. **Daily fetch** (morning pipeline): fetch today's ratings for all clubs.
       Used for upcoming match predictions.

    2. **Historical backfill** (one-time): fetch ratings for specific dates
       to populate Elo features on historical matches.
    """

    @property
    def source_name(self) -> str:
        return "clubelo"

    def scrape(
        self,
        league_config: object = None,
        season: str = "",
    ) -> pd.DataFrame:
        """Fetch today's Elo ratings for all clubs.

        Parameters
        ----------
        league_config : object, optional
            Not used — ClubElo returns all clubs regardless of league.
        season : str, optional
            Not used — ratings are date-based, not season-based.

        Returns
        -------
        pd.DataFrame
            Columns: club_name (canonical), elo_rating, rank, country, level,
            rating_date (ISO string).
        """
        today = date.today().isoformat()
        return self.fetch_ratings_for_date(today)

    def fetch_ratings_for_date(self, date_str: str) -> pd.DataFrame:
        """Fetch Elo ratings for a specific date.

        Parameters
        ----------
        date_str : str
            Date in ISO format (YYYY-MM-DD).

        Returns
        -------
        pd.DataFrame
            Columns: club_name, elo_rating, rank, country, level, rating_date.
            Empty DataFrame if the API is unavailable.
        """
        url = f"{BASE_URL}/{date_str}"

        try:
            response = self._request_with_retry(url, DOMAIN)
        except ScraperError as e:
            logger.warning(
                "ClubElo API unavailable for %s: %s", date_str, e,
            )
            return pd.DataFrame()

        if not response.text or response.text.strip() == "":
            logger.warning("ClubElo returned empty response for %s", date_str)
            return pd.DataFrame()

        # Parse CSV response
        try:
            df = pd.read_csv(StringIO(response.text), sep=",")
        except Exception as e:
            logger.error("Failed to parse ClubElo CSV for %s: %s", date_str, e)
            return pd.DataFrame()

        if df.empty:
            logger.warning("ClubElo returned empty DataFrame for %s", date_str)
            return pd.DataFrame()

        # Validate expected columns
        expected_cols = {"Club", "Elo", "Rank"}
        if not expected_cols.issubset(set(df.columns)):
            logger.error(
                "ClubElo CSV missing expected columns. Got: %s",
                list(df.columns),
            )
            return pd.DataFrame()

        # Save raw CSV text for reproducibility.
        # ClubElo returns raw CSV text (not a DataFrame), so we write directly
        # instead of using BaseScraper.save_raw() which expects a DataFrame.
        self._save_raw_text(response.text, date_str)

        # Map club names to canonical BetVector names
        records: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            clubelo_name = str(row["Club"]).strip()
            canonical = TEAM_NAME_MAP.get(clubelo_name)

            if canonical is None:
                # Skip non-EPL clubs (ClubElo returns ALL clubs worldwide)
                continue

            records.append({
                "club_name": canonical,
                "elo_rating": float(row["Elo"]) if pd.notna(row["Elo"]) else None,
                "rank": int(row["Rank"]) if pd.notna(row["Rank"]) else None,
                "country": str(row.get("Country", "")) if pd.notna(row.get("Country")) else None,
                "level": int(row["Level"]) if pd.notna(row.get("Level")) else None,
                "rating_date": date_str,
            })

        result_df = pd.DataFrame(records)
        logger.info(
            "ClubElo: %d EPL teams fetched for %s", len(result_df), date_str,
        )
        return result_df

    def _save_raw_text(self, text: str, date_str: str) -> Path:
        """Save raw CSV text to data/raw/ for reproducibility.

        ClubElo returns plain CSV text, not a DataFrame, so we override the
        standard save_raw pattern to write the text directly.

        Parameters
        ----------
        text : str
            Raw CSV text from the ClubElo API.
        date_str : str
            Date for which the ratings were fetched (used in filename).

        Returns
        -------
        Path
            Absolute path to the saved file.
        """
        raw_dir = PROJECT_ROOT / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        filepath = raw_dir / f"clubelo_{date_str}.csv"
        filepath.write_text(text, encoding="utf-8")
        logger.info(
            "[%s] Saved raw data → %s",
            self.source_name, filepath,
        )
        return filepath

    def fetch_ratings_for_dates(
        self,
        dates: List[str],
    ) -> pd.DataFrame:
        """Fetch Elo ratings for multiple dates (for historical backfill).

        Deduplicates dates and fetches each one with rate limiting.

        Parameters
        ----------
        dates : list[str]
            List of dates in ISO format.

        Returns
        -------
        pd.DataFrame
            Combined DataFrame with ratings for all dates.
        """
        unique_dates = sorted(set(dates))
        all_dfs: List[pd.DataFrame] = []

        for i, d in enumerate(unique_dates):
            if (i + 1) % 50 == 0:
                logger.info(
                    "ClubElo backfill: %d/%d dates fetched",
                    i + 1, len(unique_dates),
                )

            df = self.fetch_ratings_for_date(d)
            if not df.empty:
                all_dfs.append(df)

        if not all_dfs:
            return pd.DataFrame()

        return pd.concat(all_dfs, ignore_index=True)
