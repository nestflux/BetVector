"""
BetVector — Transfermarkt Datasets Scraper (E15-03, PC-14-02)
==============================================================
Downloads squad market value data from the public ``dcaribou/transfermarkt-datasets``
GitHub repository, hosted on Cloudflare R2 CDN.  No API key or authentication required.

This data supplements our prediction models by providing:
  - **Squad market value ratio** — richer squads generally outperform poorer ones.
    A €1 billion squad facing a €200 million squad has a structural advantage that
    goes beyond recent form.  Market value captures long-term squad quality.
  - **Average player value** — proxy for depth of talent.
  - **Contract expiring count** — players with contracts ending within 6 months
    are a proxy for squad instability (potential distraction, transfer speculation).

Data Source:
  - Repo: https://github.com/dcaribou/transfermarkt-datasets (CC0 1.0 license)
  - CDN:  https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/{table}.csv.gz
  - Tables used: ``players.csv.gz`` (individual player data + valuations)
  - Filters by ``current_club_domestic_competition_id`` per league (from leagues.yaml):
    GB1 (EPL), GB2 (Championship), ES1 (La Liga), FR1 (Ligue 1), L1 (Bundesliga), IT1 (Serie A)
  - Updated weekly by the repository maintainer

The scraper downloads the full players CSV, filters to the target league's
competition ID, and aggregates player-level data to team-level snapshots.
Individual player values are not stored — only the team aggregate (our
prediction model operates at match level).

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta
from difflib import get_close_matches
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Team Name Mapping: Transfermarkt → Canonical DB Names
# ============================================================================
# Transfermarkt uses full official club names (often with "Football Club"
# suffix).  Our canonical DB names come from Football-Data.co.uk (set during
# initial data load in E3-02).  This mapping bridges the two conventions.
#
# Names verified against actual CDN data and the ``teams`` table in the DB.
# If a new team appears (e.g., promoted side), a fuzzy fallback tries to
# match it, and a warning is logged so we can add the explicit mapping.

TRANSFERMARKT_TEAM_MAP: Dict[str, str] = {
    # =======================================================================
    # EPL (GB1) — English Premier League
    # =======================================================================
    "Arsenal Football Club": "Arsenal",
    "Association Football Club Bournemouth": "AFC Bournemouth",
    "AFC Bournemouth": "AFC Bournemouth",
    "Aston Villa Football Club": "Aston Villa",
    "Brentford Football Club": "Brentford",
    "Brighton and Hove Albion Football Club": "Brighton & Hove Albion",
    "Brighton & Hove Albion": "Brighton & Hove Albion",
    "Burnley Football Club": "Burnley",
    "Chelsea Football Club": "Chelsea",
    "Crystal Palace Football Club": "Crystal Palace",
    "Everton Football Club": "Everton",
    "Fulham Football Club": "Fulham",
    "Liverpool Football Club": "Liverpool",
    "Manchester City Football Club": "Manchester City",
    "Manchester United Football Club": "Manchester United",
    "Newcastle United Football Club": "Newcastle United",
    "Nottingham Forest Football Club": "Nottingham Forest",
    "Southampton FC": "Southampton",
    "Sunderland Association Football Club": "Sunderland",
    "Tottenham Hotspur Football Club": "Tottenham Hotspur",
    "West Ham United Football Club": "West Ham United",
    "Wolverhampton Wanderers Football Club": "Wolverhampton Wanderers",
    "Ipswich Town": "Ipswich Town",
    "Ipswich Town Football Club": "Ipswich Town",
    "Leeds United Association Football Club": "Leeds United",
    "Leeds United": "Leeds United",
    "Leicester City": "Leicester City",
    "Leicester City Football Club": "Leicester City",
    "Luton Town": "Luton Town",
    "Luton Town Football Club": "Luton Town",
    "Sheffield United": "Sheffield United",
    "Sheffield United Football Club": "Sheffield United",
    "Norwich City": "Norwich City",
    "Norwich City Football Club": "Norwich City",
    "Watford FC": "Watford",
    "West Bromwich Albion": "West Bromwich Albion",
    "Huddersfield Town": "Huddersfield Town",
    "Cardiff City": "Cardiff City",
    "Cardiff City Football Club": "Cardiff City",

    # =======================================================================
    # Championship (GB2) — English Championship
    # =======================================================================
    "Barnsley Football Club": "Barnsley",
    "Barnsley FC": "Barnsley",
    "Birmingham City Football Club": "Birmingham",
    "Birmingham City": "Birmingham",
    "Blackburn Rovers Football Club": "Blackburn",
    "Blackburn Rovers": "Blackburn",
    "Blackpool Football Club": "Blackpool",
    "Blackpool FC": "Blackpool",
    "Bristol City Football Club": "Bristol City",
    "Bristol City": "Bristol City",
    "Burnley FC": "Burnley",
    "Charlton Athletic Football Club": "Charlton",
    "Charlton Athletic": "Charlton",
    "Coventry City Football Club": "Coventry",
    "Coventry City": "Coventry",
    "Derby County Football Club": "Derby",
    "Derby County": "Derby",
    "Hull City Association Football Club": "Hull",
    "Hull City": "Hull",
    "Middlesbrough Football Club": "Middlesbrough",
    "Middlesbrough FC": "Middlesbrough",
    "Millwall Football Club": "Millwall",
    "Millwall FC": "Millwall",
    "Oxford United Football Club": "Oxford",
    "Oxford United": "Oxford",
    "Peterborough United Football Club": "Peterboro",
    "Peterborough United": "Peterboro",
    "Plymouth Argyle Football Club": "Plymouth",
    "Plymouth Argyle": "Plymouth",
    "Portsmouth Football Club": "Portsmouth",
    "Portsmouth FC": "Portsmouth",
    "Preston North End Football Club": "Preston",
    "Preston North End": "Preston",
    "Queens Park Rangers Football Club": "QPR",
    "Queens Park Rangers": "QPR",
    "QPR": "QPR",
    "Reading Football Club": "Reading",
    "Reading FC": "Reading",
    "Rotherham United Football Club": "Rotherham",
    "Rotherham United": "Rotherham",
    "Sheffield Wednesday Football Club": "Sheffield Weds",
    "Sheffield Wednesday": "Sheffield Weds",
    "Stoke City Football Club": "Stoke",
    "Stoke City": "Stoke",
    "Swansea City Association Football Club": "Swansea",
    "Swansea City": "Swansea",
    "Wigan Athletic Football Club": "Wigan",
    "Wigan Athletic": "Wigan",
    "Wrexham Association Football Club": "Wrexham",
    "Wrexham AFC": "Wrexham",
    "Wycombe Wanderers Football Club": "Wycombe",
    "Wycombe Wanderers": "Wycombe",

    # =======================================================================
    # La Liga (ES1) — Spanish Primera División
    # =======================================================================
    "Deportivo Alavés": "Alaves",
    "Deportivo Alavés, S.A.D.": "Alaves",
    "UD Almería": "Almeria",
    "Unión Deportiva Almería": "Almeria",
    "Athletic Club": "Ath Bilbao",
    "Athletic Club Bilbao": "Ath Bilbao",
    "Club Atlético de Madrid": "Ath Madrid",
    "Atlético de Madrid": "Ath Madrid",
    "Atletico Madrid": "Ath Madrid",
    "FC Barcelona": "Barcelona",
    "Futbol Club Barcelona": "Barcelona",
    "Real Betis Balompié": "Betis",
    "Real Betis": "Betis",
    "Cádiz Club de Fútbol": "Cadiz",
    "Cádiz CF": "Cadiz",
    "Real Club Celta de Vigo": "Celta",
    "RC Celta de Vigo": "Celta",
    "Celta de Vigo": "Celta",
    "Sociedad Deportiva Eibar": "Eibar",
    "SD Eibar": "Eibar",
    "Elche Club de Fútbol": "Elche",
    "Elche CF": "Elche",
    "RCD Espanyol de Barcelona": "Espanol",
    "RCD Espanyol": "Espanol",
    "Espanyol Barcelona": "Espanol",
    "Getafe Club de Fútbol": "Getafe",
    "Getafe CF": "Getafe",
    "Girona Fútbol Club": "Girona",
    "Girona FC": "Girona",
    "Granada Club de Fútbol": "Granada",
    "Granada CF": "Granada",
    "Sociedad Deportiva Huesca": "Huesca",
    "SD Huesca": "Huesca",
    "Unión Deportiva Las Palmas": "Las Palmas",
    "UD Las Palmas": "Las Palmas",
    "Club Deportivo Leganés": "Leganes",
    "CD Leganés": "Leganes",
    "Levante Unión Deportiva": "Levante",
    "Levante UD": "Levante",
    "Real Club Deportivo Mallorca": "Mallorca",
    "RCD Mallorca": "Mallorca",
    "Club Atlético Osasuna": "Osasuna",
    "CA Osasuna": "Osasuna",
    "Real Oviedo": "Oviedo",
    "Real Oviedo Club de Fútbol": "Oviedo",
    "Real Madrid Club de Fútbol": "Real Madrid",
    "Real Madrid CF": "Real Madrid",
    "Real Madrid": "Real Madrid",
    "Sevilla Fútbol Club": "Sevilla",
    "Sevilla FC": "Sevilla",
    "Real Sociedad de Fútbol": "Sociedad",
    "Real Sociedad": "Sociedad",
    "Valencia Club de Fútbol": "Valencia",
    "Valencia CF": "Valencia",
    "Real Valladolid Club de Fútbol": "Valladolid",
    "Real Valladolid": "Valladolid",
    "Rayo Vallecano de Madrid": "Vallecano",
    "Rayo Vallecano": "Vallecano",
    "Villarreal Club de Fútbol": "Villarreal",
    "Villarreal CF": "Villarreal",
    "Villarreal Club de Fútbol S.A.D.": "Villarreal",
    # --- La Liga S.A.D. variants (CDN uses ultra-long legal names) ---
    "Club Atlético de Madrid S.A.D.": "Ath Madrid",
    "Deportivo Alavés S. A. D.": "Alaves",
    "Elche Club de Fútbol S.A.D.": "Elche",
    "Getafe Club de Fútbol S. A. D. Team Dubai": "Getafe",
    "Girona Fútbol Club S. A. D.": "Girona",
    "Levante Unión Deportiva S.A.D.": "Levante",
    "Rayo Vallecano de Madrid S. A. D.": "Vallecano",
    "Real Betis Balompié S.A.D.": "Betis",
    "Real Club Celta de Vigo S. A. D.": "Celta",
    "Real Club Deportivo Mallorca S.A.D.": "Mallorca",
    "Real Oviedo S.A.D.": "Oviedo",
    "Real Sociedad de Fútbol S.A.D.": "Sociedad",
    "Reial Club Deportiu Espanyol de Barcelona S.A.D.": "Espanol",
    "Sevilla Fútbol Club S.A.D.": "Sevilla",
    "Valencia Club de Fútbol S. A. D.": "Valencia",
    "Real Valladolid Club de Fútbol S.A.D.": "Valladolid",
    "CD Leganés S.A.D.": "Leganes",

    # =======================================================================
    # Ligue 1 (FR1) — French Première Division
    # =======================================================================
    "AC Ajaccio": "Ajaccio",
    "Athletic Club Ajaccien": "Ajaccio",
    "Angers Sporting Club de l'Ouest": "Angers",
    "Angers SCO": "Angers",
    "Association de la Jeunesse Auxerroise": "Auxerre",
    "AJ Auxerre": "Auxerre",
    "Football Club des Girondins de Bordeaux": "Bordeaux",
    "Girondins de Bordeaux": "Bordeaux",
    "Stade Brestois 29": "Brest",
    "Clermont Foot 63": "Clermont",
    "Clermont Foot Auvergne 63": "Clermont",
    "Dijon Football Côte d'Or": "Dijon",
    "Dijon FCO": "Dijon",
    "Le Havre Athletic Club": "Le Havre",
    "Le Havre AC": "Le Havre",
    "Racing Club de Lens": "Lens",
    "RC Lens": "Lens",
    "Lille Olympique Sporting Club": "Lille",
    "LOSC Lille": "Lille",
    "Football Club de Lorient": "Lorient",
    "FC Lorient": "Lorient",
    "Olympique Lyonnais": "Lyon",
    "Olympique de Marseille": "Marseille",
    "Football Club de Metz": "Metz",
    "FC Metz": "Metz",
    "Association Sportive de Monaco Football Club": "Monaco",
    "AS Monaco": "Monaco",
    "Montpellier Hérault Sport Club": "Montpellier",
    "Montpellier HSC": "Montpellier",
    "Football Club de Nantes": "Nantes",
    "FC Nantes": "Nantes",
    "Olympique Gymnaste Club Nice": "Nice",
    "OGC Nice": "Nice",
    "Olympique de Nîmes": "Nimes",
    "Nîmes Olympique": "Nimes",
    "Paris Saint-Germain Football Club": "Paris SG",
    "Paris Saint-Germain": "Paris SG",
    "Stade de Reims": "Reims",
    "Stade Rennais Football Club": "Rennes",
    "Stade Rennais FC": "Rennes",
    "Association Sportive de Saint-Étienne": "St Etienne",
    "AS Saint-Étienne": "St Etienne",
    "Racing Club de Strasbourg Alsace": "Strasbourg",
    "RC Strasbourg Alsace": "Strasbourg",
    "Toulouse Football Club": "Toulouse",
    "Toulouse FC": "Toulouse",
    "Espérance Sportive Troyes Aube Champagne": "Troyes",
    "ES Troyes AC": "Troyes",
    # --- Ligue 1 CDN long-form variants ---
    "Association de la Jeunesse auxerroise": "Auxerre",
    "Association sportive de Monaco Football Club": "Monaco",
    "Football Club Lorient-Bretagne Sud": "Lorient",
    "Olympique Gymnaste Club Nice Côte d'Azur": "Nice",
    "Paris Football Club": "Paris FC",
    "Stade brestois 29": "Brest",

    # =======================================================================
    # Bundesliga (L1) — German Bundesliga
    # =======================================================================
    "FC Augsburg": "Augsburg",
    "FC Augsburg 1907": "Augsburg",
    "FC Bayern München": "Bayern Munich",
    "Bayern Munich": "Bayern Munich",
    "DSC Arminia Bielefeld": "Bielefeld",
    "Arminia Bielefeld": "Bielefeld",
    "VfL Bochum 1848": "Bochum",
    "VfL Bochum": "Bochum",
    "SV Darmstadt 98": "Darmstadt",
    "Darmstadt 98": "Darmstadt",
    "Borussia Dortmund": "Dortmund",
    "BVB Borussia Dortmund": "Dortmund",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "1. FC Köln": "FC Koln",
    "1.FC Köln": "FC Koln",
    "Sport-Club Freiburg": "Freiburg",
    "SC Freiburg": "Freiburg",
    "SpVgg Greuther Fürth": "Greuther Furth",
    "Greuther Fürth": "Greuther Furth",
    "Hamburger SV": "Hamburg",
    "Hamburger Sport-Verein": "Hamburg",
    "1. FC Heidenheim 1846": "Heidenheim",
    "FC Heidenheim": "Heidenheim",
    "Hertha BSC": "Hertha",
    "Hertha Berlin": "Hertha",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    "TSG Hoffenheim": "Hoffenheim",
    "Holstein Kiel": "Holstein Kiel",
    "Kieler SV Holstein von 1900": "Holstein Kiel",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Bayer Leverkusen": "Leverkusen",
    "Borussia Mönchengladbach": "M'gladbach",
    "Borussia Monchengladbach": "M'gladbach",
    "1. FSV Mainz 05": "Mainz",
    "FSV Mainz 05": "Mainz",
    "RasenBallsport Leipzig": "RB Leipzig",
    "RB Leipzig": "RB Leipzig",
    "FC Schalke 04": "Schalke 04",
    "Schalke 04": "Schalke 04",
    "FC St. Pauli": "St Pauli",
    "FC St. Pauli von 1910": "St Pauli",
    "VfB Stuttgart": "Stuttgart",
    "VfB Stuttgart 1893": "Stuttgart",
    "1. FC Union Berlin": "Union Berlin",
    "Union Berlin": "Union Berlin",
    "Sportverein Werder Bremen von 1899": "Werder Bremen",
    "SV Werder Bremen": "Werder Bremen",
    "Werder Bremen": "Werder Bremen",
    "VfL Wolfsburg": "Wolfsburg",
    "VfL Wolfsburg-Fußball": "Wolfsburg",
    # --- Bundesliga CDN long-form variants ---
    "1. Fußball- und Sportverein Mainz 05": "Mainz",
    "1. Fußball-Club Köln": "FC Koln",
    "1. Fußballclub Heidenheim 1846": "Heidenheim",
    "Bayer 04 Leverkusen Fußball": "Leverkusen",
    "Borussia Verein für Leibesübungen 1900 Mönchengladbach": "M'gladbach",
    "Fußball-Club Augsburg 1907": "Augsburg",
    "Fußball-Club St. Pauli von 1910": "St Pauli",
    "Hamburger Sport Verein": "Hamburg",
    "Turn- und Sportgemeinschaft 1899 Hoffenheim Fußball-Spielbetriebs": "Hoffenheim",
    "Verein für Bewegungsspiele Stuttgart 1893": "Stuttgart",
    "Verein für Leibesübungen Wolfsburg": "Wolfsburg",

    # =======================================================================
    # Serie A (IT1) — Italian Serie A
    # =======================================================================
    "Atalanta Bergamasca Calcio": "Atalanta",
    "Atalanta BC": "Atalanta",
    "Benevento Calcio": "Benevento",
    "Bologna Football Club 1909": "Bologna",
    "Bologna FC 1909": "Bologna",
    "Cagliari Calcio": "Cagliari",
    "Como 1907": "Como",
    "Calcio Como": "Como",
    "Unione Sportiva Cremonese": "Cremonese",
    "US Cremonese": "Cremonese",
    "Football Club Crotone": "Crotone",
    "FC Crotone": "Crotone",
    "Empoli Football Club": "Empoli",
    "Empoli FC": "Empoli",
    "ACF Fiorentina": "Fiorentina",
    "Frosinone Calcio": "Frosinone",
    "Genoa Cricket and Football Club": "Genoa",
    "Genoa CFC": "Genoa",
    "Football Club Internazionale Milano": "Inter",
    "Inter Milan": "Inter",
    "FC Internazionale Milano": "Inter",
    "Juventus Football Club": "Juventus",
    "Juventus FC": "Juventus",
    "Società Sportiva Lazio": "Lazio",
    "SS Lazio": "Lazio",
    "Unione Sportiva Lecce": "Lecce",
    "US Lecce": "Lecce",
    "Associazione Calcio Milan": "Milan",
    "AC Milan": "Milan",
    "AC Monza": "Monza",
    "Associazione Calcio Monza": "Monza",
    "Società Sportiva Calcio Napoli": "Napoli",
    "SSC Napoli": "Napoli",
    "Parma Calcio 1913": "Parma",
    "Parma FC": "Parma",
    "AC Pisa 1909": "Pisa",
    "Pisa Sporting Club": "Pisa",
    "Associazione Sportiva Roma": "Roma",
    "AS Roma": "Roma",
    "Unione Sportiva Salernitana 1919": "Salernitana",
    "US Salernitana 1919": "Salernitana",
    "Unione Calcio Sampdoria": "Sampdoria",
    "UC Sampdoria": "Sampdoria",
    "Unione Sportiva Sassuolo Calcio": "Sassuolo",
    "US Sassuolo": "Sassuolo",
    "Spezia Calcio": "Spezia",
    "Torino Football Club": "Torino",
    "Torino FC": "Torino",
    "Udinese Calcio": "Udinese",
    "Venezia Football Club": "Venezia",
    "Venezia FC": "Venezia",
    "Hellas Verona Football Club": "Verona",
    "Hellas Verona FC": "Verona",
    "Hellas Verona": "Verona",
    # --- Serie A CDN long-form variants ---
    "Associazione Calcio Fiorentina": "Fiorentina",
    "Atalanta Bergamasca Calcio S.p.a.": "Atalanta",
    "Football Club Internazionale Milano S.p.A.": "Inter",
    "Società Sportiva Lazio S.p.A.": "Lazio",
    "Unione Sportiva Cremonese S.p.A.": "Cremonese",
    "Verona Hellas Football Club": "Verona",
}


# ============================================================================
# Transfermarkt Datasets Scraper
# ============================================================================

class TransfermarktScraper(BaseScraper):
    """Squad market value scraper via Transfermarkt Datasets CDN.

    Downloads the full ``players.csv.gz`` file from the CDN, filters to the
    target league's competition ID (from ``league_config.transfermarkt_id``),
    and aggregates player-level data to team-level market value snapshots.
    Returns a DataFrame ready for ``load_market_values()``.

    Supported competition IDs (set in ``config/leagues.yaml``):
      GB1 (EPL), GB2 (Championship), ES1 (La Liga), FR1 (Ligue 1),
      L1 (Bundesliga), IT1 (Serie A)

    Output columns: ``team_name, squad_total_value, avg_player_value,
    squad_size, contract_expiring_count, evaluated_at``

    This scraper does NOT require an API key — the CDN is public and free.
    The data is licensed under CC0 1.0 (public domain).
    """

    # Domain for rate limiting
    DOMAIN = "pub-e682421888d945d684bcae8890b0ec20.r2.dev"

    def __init__(self) -> None:
        super().__init__()

        # Override rate limit for the CDN (polite, not aggressive)
        try:
            interval = float(
                getattr(config.settings.scraping.transfermarkt,
                        "min_request_interval_seconds", 2)
            )
            self.rate_limiter._min_interval = interval
        except (AttributeError, TypeError):
            self.rate_limiter._min_interval = 2.0

        # CDN base URL from config (competition ID now comes from league_config)
        try:
            self._cdn_base = str(
                getattr(config.settings.scraping.transfermarkt,
                        "cdn_base_url",
                        "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data")
            )
        except (AttributeError, TypeError):
            self._cdn_base = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"

    @property
    def source_name(self) -> str:
        return "transfermarkt"

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch squad market values for all teams in the target league.

        Downloads ``players.csv.gz`` from the CDN, filters to the league's
        competition ID (``league_config.transfermarkt_id``), and aggregates
        to team-level metrics.

        The ``season`` parameter is used for file naming (``save_raw()``) but
        does not filter the data — the CDN always serves the latest snapshot.

        Parameters
        ----------
        league_config : ConfigNamespace
            League configuration from ``config.get_active_leagues()``.
            Must have ``transfermarkt_id`` (e.g. "GB1", "ES1", "L1").
        season : str
            Season string, e.g. ``"2025-26"`` — used for raw file naming.

        Returns
        -------
        pd.DataFrame
            One row per team with: team_name, squad_total_value,
            avg_player_value, squad_size, contract_expiring_count, evaluated_at.
            Empty DataFrame on any failure.
        """
        league_name = getattr(league_config, "short_name", "unknown")

        # Read competition ID from league config (PC-14-02: multi-league support)
        competition_id = getattr(league_config, "transfermarkt_id", None)
        if not competition_id:
            logger.warning(
                "[%s] No transfermarkt_id for league %s — skipping",
                self.source_name, league_name,
            )
            return pd.DataFrame()

        logger.info(
            "[%s] Fetching squad market values for %s %s",
            self.source_name, league_name, season,
        )

        # --- Download players.csv.gz ---
        players_url = f"{self._cdn_base}/players.csv.gz"

        try:
            response = self._request_with_retry(
                url=players_url,
                domain=self.DOMAIN,
                headers={"Accept": "application/gzip"},
            )
        except ScraperError as e:
            logger.error("[%s] Failed to download players.csv.gz: %s",
                         self.source_name, e)
            return pd.DataFrame()
        except Exception as e:
            logger.error("[%s] Unexpected error downloading players: %s",
                         self.source_name, e)
            return pd.DataFrame()

        # --- Parse the gzip-compressed CSV ---
        try:
            players_df = pd.read_csv(
                io.BytesIO(response.content),
                compression="gzip",
            )
        except Exception as e:
            logger.error("[%s] Failed to parse players CSV: %s",
                         self.source_name, e)
            return pd.DataFrame()

        logger.info(
            "[%s] Downloaded %d total players from CDN",
            self.source_name, len(players_df),
        )

        if players_df.empty:
            logger.warning("[%s] Empty players CSV from CDN", self.source_name)
            return pd.DataFrame()

        # --- Filter to target league clubs ---
        # Use the competition ID column on the players table directly
        league_players = players_df[
            players_df["current_club_domestic_competition_id"] == competition_id
        ].copy()

        if league_players.empty:
            logger.warning(
                "[%s] No players found for %s (competition_id=%s)",
                self.source_name, league_name, competition_id,
            )
            return pd.DataFrame()

        # Filter to recent players only — the dataset includes historical players
        # who may no longer be at the club.  last_season >= (current year - 1)
        # ensures we only count active squad members.
        current_year = datetime.utcnow().year
        min_last_season = current_year - 1  # e.g., 2024 for 2025-26 season
        league_players = league_players[
            league_players["last_season"] >= min_last_season
        ].copy()

        # Only keep players with market values for aggregation
        valued_players = league_players[
            league_players["market_value_in_eur"].notna()
        ].copy()

        logger.info(
            "[%s] %s players: %d total, %d with market values (last_season >= %d)",
            self.source_name, league_name, len(league_players),
            len(valued_players), min_last_season,
        )

        if valued_players.empty:
            logger.warning(
                "[%s] No %s players with market values",
                self.source_name, league_name,
            )
            return pd.DataFrame()

        # --- Calculate contract expiring count ---
        # A player's contract is "expiring" if it ends within 6 months from today.
        # This is a proxy for squad instability — players may be distracted by
        # transfer speculation, and the team risks losing key assets for free.
        today = datetime.utcnow()
        cutoff = today + timedelta(days=180)

        league_players["contract_exp"] = pd.to_datetime(
            league_players["contract_expiration_date"], errors="coerce"
        )
        expiring_counts = (
            league_players[league_players["contract_exp"] <= cutoff]
            .groupby("current_club_name")
            .size()
            .reset_index(name="contract_expiring_count")
        )

        # --- Aggregate to team level ---
        team_agg = (
            valued_players
            .groupby("current_club_name")
            .agg(
                squad_total_value=("market_value_in_eur", "sum"),
                avg_player_value=("market_value_in_eur", "mean"),
                squad_size=("player_id", "count"),
            )
            .reset_index()
            .rename(columns={"current_club_name": "tm_name"})
        )

        # Merge contract expiring counts
        team_agg = team_agg.merge(
            expiring_counts.rename(columns={"current_club_name": "tm_name"}),
            on="tm_name",
            how="left",
        )
        team_agg["contract_expiring_count"] = (
            team_agg["contract_expiring_count"].fillna(0).astype(int)
        )

        # --- Map team names to canonical DB names ---
        team_agg["team_name"] = team_agg["tm_name"].apply(self._map_team_name)

        # Add evaluation date (today's date — this is a snapshot)
        team_agg["evaluated_at"] = date.today().isoformat()

        # Select output columns
        result = team_agg[[
            "team_name", "squad_total_value", "avg_player_value",
            "squad_size", "contract_expiring_count", "evaluated_at",
        ]].copy()

        # Save raw data for reproducibility
        self.save_raw(result, league_name, season)

        # Log summary
        top = result.sort_values("squad_total_value", ascending=False).head(3)
        top_str = ", ".join(
            f"{r['team_name']} (€{r['squad_total_value']/1e6:.0f}M)"
            for _, r in top.iterrows()
        )
        logger.info(
            "[%s] Aggregated market values for %d %s teams. "
            "Top 3: %s",
            self.source_name, len(result), league_name, top_str,
        )

        return result

    # -----------------------------------------------------------------------
    # Player-Level Data (E39-01)
    # -----------------------------------------------------------------------
    # Position mapping: Transfermarkt "position" → abbreviated code.
    # Used for PlayerValue.position and injury display.
    _POSITION_MAP = {
        "Goalkeeper": "GK",
        "Defender": "DF",
        "Midfield": "MF",
        "Attack": "FW",
    }

    def scrape_players(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch individual player market values for all teams in a league.

        Downloads the same ``players.csv.gz`` as ``scrape()``, but returns
        per-player data instead of team-level aggregates.  Used to populate
        the ``player_values`` table, which provides:

        - **Automated injury impact_rating:** a player's value_percentile
          (rank within squad by market value) maps directly to how important
          they are.  Haaland = top percentile ~ 1.0, backup keeper ~ 0.04.
        - **Bench strength feature:** compare bench vs starter market values.

        Parameters
        ----------
        league_config : ConfigNamespace
            Must have ``transfermarkt_id`` (e.g. "GB1").
        season : str
            Season string for raw file naming, e.g. ``"2025-26"``.

        Returns
        -------
        pd.DataFrame
            One row per player: player_name, team_name, position (GK/DF/MF/FW),
            market_value_eur, snapshot_date.  Empty DataFrame on failure.
        """
        league_name = getattr(league_config, "short_name", "unknown")
        competition_id = getattr(league_config, "transfermarkt_id", None)
        if not competition_id:
            logger.warning(
                "[%s] No transfermarkt_id for %s — skipping player scrape",
                self.source_name, league_name,
            )
            return pd.DataFrame()

        logger.info(
            "[%s] Fetching player-level market values for %s %s",
            self.source_name, league_name, season,
        )

        # --- Download players.csv.gz (same file as team-level scrape) ---
        players_url = f"{self._cdn_base}/players.csv.gz"
        try:
            response = self._request_with_retry(
                url=players_url,
                domain=self.DOMAIN,
                headers={"Accept": "application/gzip"},
            )
        except (ScraperError, Exception) as e:
            logger.error("[%s] Failed to download players.csv.gz: %s",
                         self.source_name, e)
            return pd.DataFrame()

        try:
            players_df = pd.read_csv(
                io.BytesIO(response.content),
                compression="gzip",
            )
        except Exception as e:
            logger.error("[%s] Failed to parse players CSV: %s",
                         self.source_name, e)
            return pd.DataFrame()

        if players_df.empty:
            return pd.DataFrame()

        # --- Filter to target league's active players ---
        league_players = players_df[
            players_df["current_club_domestic_competition_id"] == competition_id
        ].copy()

        if league_players.empty:
            logger.warning(
                "[%s] No players for %s (competition_id=%s)",
                self.source_name, league_name, competition_id,
            )
            return pd.DataFrame()

        # Only active players (appeared in recent season)
        current_year = datetime.utcnow().year
        min_last_season = current_year - 1
        league_players = league_players[
            league_players["last_season"] >= min_last_season
        ].copy()

        # Only players with market values
        valued = league_players[
            league_players["market_value_in_eur"].notna()
        ].copy()

        if valued.empty:
            logger.warning("[%s] No %s players with market values",
                           self.source_name, league_name)
            return pd.DataFrame()

        # --- Map position to abbreviated code ---
        valued["pos_code"] = valued["position"].map(self._POSITION_MAP)

        # --- Map team names to canonical DB names ---
        valued["team_name"] = valued["current_club_name"].apply(
            self._map_team_name
        )

        # --- Build output DataFrame ---
        result = pd.DataFrame({
            "player_name": valued["name"].values,
            "team_name": valued["team_name"].values,
            "position": valued["pos_code"].values,
            "market_value_eur": valued["market_value_in_eur"].values,
            "snapshot_date": date.today().isoformat(),
        })

        logger.info(
            "[%s] %s: %d players with market values across %d teams",
            self.source_name, league_name, len(result),
            result["team_name"].nunique(),
        )

        return result

    # -----------------------------------------------------------------------
    # Team Name Mapping
    # -----------------------------------------------------------------------

    def _map_team_name(self, tm_name: str) -> str:
        """Map a Transfermarkt club name to our canonical DB name.

        First tries the explicit mapping dict.  If no match, falls back to
        fuzzy matching against all known canonical names.  If even fuzzy
        matching fails, returns the raw Transfermarkt name and logs a warning
        so the mapping can be added manually.
        """
        if not tm_name:
            return tm_name

        # Direct lookup
        canonical = TRANSFERMARKT_TEAM_MAP.get(tm_name)
        if canonical:
            return canonical

        # Fuzzy fallback — try to match against known canonical names
        all_canonical = list(set(TRANSFERMARKT_TEAM_MAP.values()))
        matches = get_close_matches(tm_name, all_canonical, n=1, cutoff=0.6)
        if matches:
            logger.info(
                "[%s] Fuzzy matched '%s' → '%s'",
                self.source_name, tm_name, matches[0],
            )
            return matches[0]

        # No match — log warning for manual intervention
        logger.warning(
            "[%s] UNMAPPED team name: '%s' — add to TRANSFERMARKT_TEAM_MAP",
            self.source_name, tm_name,
        )
        return tm_name
