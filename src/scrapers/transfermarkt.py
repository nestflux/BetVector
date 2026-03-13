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
import os
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
    "Real Valladolid CF": "Valladolid",
    "Córdoba CF": "Cordoba",
    "Deportivo de La Coruña": "La Coruna",
    "Málaga CF": "Malaga",
    "Real Zaragoza": "Zaragoza",
    "Sporting Gijón": "Sporting Gijon",

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
    "ESTAC Troyes": "Troyes",
    "FC Girondins Bordeaux": "Bordeaux",
    "Stade Reims": "Reims",
    "AS Nancy-Lorraine": "Nancy",
    "Amiens SC": "Amiens",
    "EA Guingamp": "Guingamp",
    "FC Sochaux-Montbéliard": "Sochaux",
    "GFC Ajaccio": "GFC Ajaccio",
    "SC Bastia": "Bastia",
    "SM Caen": "Caen",
    "Thonon Évian Grand Genève FC": "Evian",
    "Valenciennes FC": "Valenciennes",

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
    "1. Fußballclub Union Berlin": "Union Berlin",
    "Eintracht Frankfurt Fußball AG": "Ein Frankfurt",
    "1.FC Nuremberg": "Nurnberg",
    "Eintracht Braunschweig": "Braunschweig",
    "FC Ingolstadt 04": "Ingolstadt",
    "Fortuna Düsseldorf": "Dusseldorf",
    "Hannover 96": "Hannover",
    "SC Paderborn 07": "Paderborn",

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
    "FC Empoli": "Empoli",
    "Torino Calcio": "Torino",
    "AC Carpi": "Carpi",
    "Brescia Calcio": "Brescia",
    "Catania FC": "Catania",
    "Cesena FC": "Cesena",
    "Chievo Verona": "Chievo",
    "Delfino Pescara 1936": "Pescara",
    "Palermo FC": "Palermo",
    "SPAL": "SPAL",
    "Siena FC": "Siena",
    "US Livorno 1915": "Livorno",
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


# ============================================================================
# Transfermarkt-Datasets Full Integration (E40)
# ============================================================================
# The dcaribou/transfermarkt-datasets repo provides a comprehensive,
# weekly-updated dataset covering 78K+ matches with lineups, formations,
# manager names, player appearances, and transfers.  This section handles:
#   1. Downloading the full ZIP from the R2 CDN
#   2. Matching TM games to our Match table via (date + home/away team)
#   3. Providing DataFrames for use by backfill functions in loader.py
#
# Data source: https://github.com/dcaribou/transfermarkt-datasets (CC0 1.0)
# CDN:         https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/
# ============================================================================

# Competition IDs for our 5 supported leagues (Championship excluded — no TM data)
TM_LEAGUE_IDS = {"GB1", "ES1", "FR1", "L1", "IT1"}

# Default data directory for the downloaded ZIP contents
TM_DATASETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "raw", "transfermarkt", "datasets",
)

# R2 CDN URL for the full dataset ZIP
TM_DATASETS_ZIP_URL = (
    "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/"
    "transfermarkt-datasets.zip"
)


def download_transfermarkt_datasets(
    dest_dir: Optional[str] = None,
    force: bool = False,
    max_age_days: int = 7,
) -> Dict[str, str]:
    """Download the full transfermarkt-datasets ZIP from the R2 CDN.

    Extracts CSV files to ``dest_dir`` (default: ``data/raw/transfermarkt/datasets/``).
    Skips re-download if files exist and are less than ``max_age_days`` old,
    unless ``force=True``.

    Parameters
    ----------
    dest_dir : str, optional
        Directory to extract CSV files into.  Defaults to TM_DATASETS_DIR.
    force : bool
        If True, re-download even if recent files exist.
    max_age_days : int
        Maximum age (in days) of existing files before triggering re-download.

    Returns
    -------
    dict
        Mapping of table name → file path for each extracted CSV file.
        E.g. ``{"games": "/path/to/games.csv.gz", ...}``
    """
    import zipfile
    import time as _time

    dest = dest_dir or TM_DATASETS_DIR
    os.makedirs(dest, exist_ok=True)

    # Check if we already have recent files
    games_path = os.path.join(dest, "games.csv.gz")
    if os.path.exists(games_path) and not force:
        age_days = (_time.time() - os.path.getmtime(games_path)) / 86400
        if age_days < max_age_days:
            logger.info(
                "TM datasets already present (%.1f days old, max %d) — skipping download",
                age_days, max_age_days,
            )
            return _list_tm_files(dest)

    # Download ZIP
    logger.info("Downloading transfermarkt-datasets ZIP (%s) ...", TM_DATASETS_ZIP_URL)
    import requests as _requests

    try:
        resp = _requests.get(TM_DATASETS_ZIP_URL, timeout=300, stream=True)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Failed to download TM datasets ZIP: %s", exc)
        # Return existing files if available
        return _list_tm_files(dest) if os.path.exists(games_path) else {}

    zip_path = os.path.join(dest, "transfermarkt-datasets.zip")
    with open(zip_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    logger.info("Downloaded %.1f MB → %s", size_mb, zip_path)

    # Extract CSVs
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)
        logger.info("Extracted TM datasets to %s", dest)
    except Exception as exc:
        logger.error("Failed to extract TM datasets ZIP: %s", exc)
        return {}

    return _list_tm_files(dest)


def _list_tm_files(dest_dir: str) -> Dict[str, str]:
    """List available TM dataset CSV files in the given directory."""
    tables = {}
    for fname in os.listdir(dest_dir):
        if fname.endswith(".csv.gz"):
            table_name = fname.replace(".csv.gz", "")
            tables[table_name] = os.path.join(dest_dir, fname)
    return tables


def load_tm_games(dest_dir: Optional[str] = None) -> pd.DataFrame:
    """Load the TM games table, filtered to our 5 leagues.

    Returns a DataFrame with columns: game_id, competition_id, season, date,
    home_club_id, away_club_id, home_club_name, away_club_name,
    home_club_manager_name, away_club_manager_name,
    home_club_formation, away_club_formation, home_club_goals, away_club_goals.
    """
    dest = dest_dir or TM_DATASETS_DIR
    path = os.path.join(dest, "games.csv.gz")
    if not os.path.exists(path):
        logger.error("TM games.csv.gz not found at %s", path)
        return pd.DataFrame()

    games = pd.read_csv(path)
    # Filter to our 5 leagues
    games = games[games["competition_id"].isin(TM_LEAGUE_IDS)].copy()
    logger.info("Loaded %d TM games for our 5 leagues", len(games))
    return games


def load_tm_lineups(dest_dir: Optional[str] = None) -> pd.DataFrame:
    """Load the TM game_lineups table.

    Returns a DataFrame with columns: game_id, player_id, club_id,
    player_name, type (starting_lineup/substitutes), position, number,
    team_captain.
    """
    dest = dest_dir or TM_DATASETS_DIR
    path = os.path.join(dest, "game_lineups.csv.gz")
    if not os.path.exists(path):
        logger.error("TM game_lineups.csv.gz not found at %s", path)
        return pd.DataFrame()

    lineups = pd.read_csv(path, low_memory=False)
    logger.info("Loaded %d TM game_lineups rows", len(lineups))
    return lineups


def load_tm_appearances(dest_dir: Optional[str] = None) -> pd.DataFrame:
    """Load the TM appearances table.

    Returns a DataFrame with player-level per-match data including
    minutes_played, goals, assists, yellow/red cards, and critically
    player_club_id (the club the player was at during the match — not
    their current club).
    """
    dest = dest_dir or TM_DATASETS_DIR
    path = os.path.join(dest, "appearances.csv.gz")
    if not os.path.exists(path):
        logger.error("TM appearances.csv.gz not found at %s", path)
        return pd.DataFrame()

    appearances = pd.read_csv(path)
    logger.info("Loaded %d TM appearances rows", len(appearances))
    return appearances


def load_tm_transfers(dest_dir: Optional[str] = None) -> pd.DataFrame:
    """Load the TM transfers table.

    Returns a DataFrame with player transfers including transfer_date,
    from_club_id, to_club_id — used for determining which club a player
    was at on a specific historical date.
    """
    dest = dest_dir or TM_DATASETS_DIR
    path = os.path.join(dest, "transfers.csv.gz")
    if not os.path.exists(path):
        logger.error("TM transfers.csv.gz not found at %s", path)
        return pd.DataFrame()

    transfers = pd.read_csv(path)
    logger.info("Loaded %d TM transfers rows", len(transfers))
    return transfers


def build_tm_match_mapping(session) -> Dict[int, int]:
    """Match TM game_ids to our Match.id via (date + home_team + away_team).

    For each TM game in our 5 leagues:
      1. Map TM home_club_name → canonical DB name via TRANSFERMARKT_TEAM_MAP
      2. Map TM away_club_name → canonical DB name via TRANSFERMARKT_TEAM_MAP
      3. Look up Team.id for both home and away
      4. Find Match where (date, home_team_id, away_team_id) matches

    Returns
    -------
    dict
        Mapping of ``{tm_game_id: our_match_id}`` for all successfully matched
        games.  Unmatched games are logged as warnings.
    """
    from src.database.models import Match, Team

    # Load TM games
    tm_games = load_tm_games()
    if tm_games.empty:
        return {}

    # Build team name → list of team_ids lookup from our DB.
    # Some teams have duplicate entries (e.g., Burnley id=22 AND id=57 from
    # different data sources / seasons).  We need to try ALL IDs for matching.
    all_teams = session.query(Team.id, Team.name).all()
    team_name_to_ids: Dict[str, List[int]] = {}
    for tid, name in all_teams:
        team_name_to_ids.setdefault(name, []).append(tid)

    mapping: Dict[int, int] = {}
    unmatched_teams: Dict[str, int] = {}  # tm_name → count
    unmatched_matches = 0
    already_mapped = 0

    # Pre-fetch all matches with their date + team IDs for fast lookup
    all_matches = session.query(
        Match.id, Match.date, Match.home_team_id, Match.away_team_id,
        Match.transfermarkt_game_id,
    ).all()

    # Build a lookup: (date, home_team_id, away_team_id) → match_id
    match_lookup: Dict[tuple, int] = {}
    for mid, mdate, htid, atid, tm_gid in all_matches:
        match_lookup[(mdate, htid, atid)] = mid
        # Track already-mapped games
        if tm_gid is not None:
            already_mapped += 1

    logger.info(
        "Building TM match mapping: %d TM games, %d DB matches, %d already mapped",
        len(tm_games), len(all_matches), already_mapped,
    )

    for _, row in tm_games.iterrows():
        tm_game_id = int(row["game_id"])
        tm_date = str(row["date"])[:10]  # YYYY-MM-DD

        # Map TM names → canonical names
        home_tm = row.get("home_club_name", "")
        away_tm = row.get("away_club_name", "")

        if pd.isna(home_tm) or pd.isna(away_tm):
            continue

        home_canonical = TRANSFERMARKT_TEAM_MAP.get(home_tm, home_tm)
        away_canonical = TRANSFERMARKT_TEAM_MAP.get(away_tm, away_tm)

        # Look up team IDs — try ALL IDs for teams with duplicates
        home_ids = team_name_to_ids.get(home_canonical, [])
        away_ids = team_name_to_ids.get(away_canonical, [])

        if not home_ids:
            unmatched_teams[home_tm] = unmatched_teams.get(home_tm, 0) + 1
            continue
        if not away_ids:
            unmatched_teams[away_tm] = unmatched_teams.get(away_tm, 0) + 1
            continue

        # Try all combinations of home/away IDs to find the matching DB entry.
        # Most teams have a single ID so this is O(1) in 95% of cases.
        match_id = None
        for hid in home_ids:
            for aid in away_ids:
                match_id = match_lookup.get((tm_date, hid, aid))
                if match_id is not None:
                    break
            if match_id is not None:
                break

        if match_id is None:
            unmatched_matches += 1
            continue

        mapping[tm_game_id] = match_id

    # Log results
    total_tm = len(tm_games)
    matched = len(mapping)
    logger.info(
        "TM match mapping complete: %d/%d matched (%.1f%%), "
        "%d unmatched (teams not in DB or match not found)",
        matched, total_tm, (matched / total_tm * 100) if total_tm else 0,
        total_tm - matched,
    )

    if unmatched_teams:
        for tm_name, count in sorted(
            unmatched_teams.items(), key=lambda x: -x[1]
        )[:10]:
            logger.warning(
                "TM team not in DB: '%s' (%d games) — canonical: '%s'",
                tm_name, count,
                TRANSFERMARKT_TEAM_MAP.get(tm_name, "UNMAPPED"),
            )

    if unmatched_matches > 0:
        logger.info(
            "TM games with valid teams but no DB match: %d "
            "(likely outside our 2020+ date range or Championship)",
            unmatched_matches,
        )

    return mapping


def persist_tm_match_mapping(session, mapping: Dict[int, int]) -> int:
    """Store the TM game_id → match_id mapping in the Match table.

    Updates ``Match.transfermarkt_game_id`` for all matched games.
    Idempotent — re-running with the same mapping is a no-op.

    Returns
    -------
    int
        Number of matches updated.
    """
    from src.database.models import Match

    # Build reverse lookup: match_id → tm_game_id
    match_to_tm: Dict[int, int] = {mid: tmid for tmid, mid in mapping.items()}

    if not match_to_tm:
        logger.info("No matches to update with TM game IDs")
        return 0

    # Batch update
    updated = 0
    batch_size = 500
    match_ids = list(match_to_tm.keys())

    for i in range(0, len(match_ids), batch_size):
        batch = match_ids[i: i + batch_size]
        matches = session.query(Match).filter(Match.id.in_(batch)).all()

        for match in matches:
            tm_gid = match_to_tm[match.id]
            if match.transfermarkt_game_id != tm_gid:
                match.transfermarkt_game_id = tm_gid
                updated += 1

        session.flush()

    session.commit()
    logger.info(
        "Persisted TM game IDs: %d matches updated (out of %d mapped)",
        updated, len(mapping),
    )
    return updated


# ---------------------------------------------------------------------------
# E40-02: Position mapping — TM detailed positions → our 4-letter codes
# ---------------------------------------------------------------------------

# Transfermarkt uses granular position names like "Centre-Back",
# "Defensive Midfield", "Right Winger", etc.  Our MatchLineup model uses
# four standard codes: GK, DF, MF, FW.  This mapping collapses the
# detailed TM positions into our codes for feature engineering.
TM_POSITION_MAP: Dict[str, str] = {
    # Goalkeeper
    "Goalkeeper": "GK",
    # Defenders
    "Centre-Back": "DF",
    "Left-Back": "DF",
    "Right-Back": "DF",
    "Defender": "DF",
    "Sweeper": "DF",
    # Midfielders
    "Central Midfield": "MF",
    "Defensive Midfield": "MF",
    "Attacking Midfield": "MF",
    "Left Midfield": "MF",
    "Right Midfield": "MF",
    "Midfield": "MF",
    "midfield": "MF",
    # Forwards / Wingers
    "Centre-Forward": "FW",
    "Left Winger": "FW",
    "Right Winger": "FW",
    "Second Striker": "FW",
    "Attack": "FW",
}


def backfill_lineups_from_tm(session) -> Dict[str, int]:
    """Backfill the ``match_lineups`` table from TM ``game_lineups.csv.gz``.

    For each matched game (via ``transfermarkt_game_id`` on Match), this
    function loads the TM lineup rows, maps club_id → our team_id,
    maps TM position names → our 4-letter codes (GK/DF/MF/FW), and
    inserts MatchLineup rows.

    The function is **idempotent**: it checks for existing rows via the
    unique constraint ``(match_id, team_id, player_name)`` and skips
    duplicates.  Batch-commits every 500 games to control memory.

    Parameters
    ----------
    session : SQLAlchemy session
        Active database session.

    Returns
    -------
    dict
        Stats dict with keys: ``inserted``, ``skipped``, ``games_processed``,
        ``games_with_lineups``, ``errors``.
    """
    from src.database.models import Match, MatchLineup

    stats = {
        "inserted": 0,
        "skipped": 0,
        "games_processed": 0,
        "games_with_lineups": 0,
        "errors": 0,
    }

    # 1. Load TM datasets
    tm_lineups = load_tm_lineups()
    if tm_lineups.empty:
        logger.error("No TM lineup data available — aborting backfill")
        return stats

    tm_games = load_tm_games()
    if tm_games.empty:
        logger.error("No TM games data available — aborting backfill")
        return stats

    # 2. Get all matches that have a transfermarkt_game_id (from E40-01)
    matched_records = (
        session.query(
            Match.id, Match.transfermarkt_game_id,
            Match.home_team_id, Match.away_team_id,
        )
        .filter(Match.transfermarkt_game_id.isnot(None))
        .all()
    )

    if not matched_records:
        logger.warning("No matches have transfermarkt_game_id set — "
                        "run persist_tm_match_mapping first")
        return stats

    # Build lookups:
    # tm_game_id → (match_id, home_team_id, away_team_id)
    tm_to_match: Dict[int, tuple] = {}
    for mid, tm_gid, htid, atid in matched_records:
        tm_to_match[tm_gid] = (mid, htid, atid)

    # Build TM game club lookup: game_id → (home_club_id, away_club_id)
    # This tells us which TM club_id is home and which is away
    tm_game_clubs: Dict[int, tuple] = {}
    relevant_game_ids = set(tm_to_match.keys())
    relevant_tm_games = tm_games[tm_games["game_id"].isin(relevant_game_ids)]
    for _, row in relevant_tm_games.iterrows():
        gid = int(row["game_id"])
        tm_game_clubs[gid] = (int(row["home_club_id"]), int(row["away_club_id"]))

    logger.info(
        "Lineup backfill: %d matched games, %d with TM game club info",
        len(tm_to_match), len(tm_game_clubs),
    )

    # 3. Filter TM lineups to only our matched games
    lineup_game_ids = set(tm_to_match.keys())
    our_lineups = tm_lineups[tm_lineups["game_id"].isin(lineup_game_ids)].copy()

    if our_lineups.empty:
        logger.warning("No TM lineups found for our matched games")
        return stats

    logger.info("Filtering to %d TM lineup rows for %d matched games",
                len(our_lineups), our_lineups["game_id"].nunique())

    # 4. Pre-fetch existing lineup entries for dedup check.
    # Uses in-memory set of (match_id, team_id, player_name) for O(1) lookups
    # instead of per-row DB queries (avoids N+1 problem on 390K+ rows).
    existing_keys: set = set()
    existing_records = (
        session.query(
            MatchLineup.match_id, MatchLineup.team_id,
            MatchLineup.player_name,
        )
        .all()
    )
    for emid, etid, epname in existing_records:
        existing_keys.add((emid, etid, epname))

    logger.info("Pre-fetched %d existing lineup entries for dedup", len(existing_keys))

    # 5. Process lineups grouped by game_id for batch commits
    grouped = our_lineups.groupby("game_id")
    batch_count = 0
    batch_size = 500  # Commit every 500 games to control memory

    for tm_game_id, game_lineup_df in grouped:
        tm_game_id = int(tm_game_id)
        stats["games_processed"] += 1

        # Look up our match info
        match_info = tm_to_match.get(tm_game_id)
        if match_info is None:
            continue

        match_id, home_team_id, away_team_id = match_info

        # Look up TM club IDs for this game to map club_id → team_id.
        # The TM games table tells us which club_id was home and which was
        # away; we map those to our Match.home_team_id / away_team_id.
        club_info = tm_game_clubs.get(tm_game_id)
        if club_info is None:
            logger.debug("No TM club info for game %d — skipping", tm_game_id)
            stats["errors"] += 1
            continue

        tm_home_club_id, tm_away_club_id = club_info
        game_had_rows = False

        for _, row in game_lineup_df.iterrows():
            player_name = row.get("player_name", "")
            if pd.isna(player_name) or not player_name:
                continue

            # Map TM club_id → our team_id via home/away context
            raw_club_id = row.get("club_id")
            if pd.isna(raw_club_id):
                stats["errors"] += 1
                continue
            tm_club_id = int(raw_club_id)
            if tm_club_id == tm_home_club_id:
                team_id = home_team_id
            elif tm_club_id == tm_away_club_id:
                team_id = away_team_id
            else:
                # Club doesn't match either side — rare edge case
                # (e.g., TM data error or neutral-venue game)
                logger.debug(
                    "Club ID %d not home (%d) or away (%d) for game %d",
                    tm_club_id, tm_home_club_id, tm_away_club_id, tm_game_id,
                )
                stats["errors"] += 1
                continue

            # Dedup check against existing rows
            key = (match_id, team_id, str(player_name))
            if key in existing_keys:
                stats["skipped"] += 1
                continue

            # Map TM position (e.g., "Centre-Back") → our code (e.g., "DF")
            tm_position = row.get("position", "")
            if pd.isna(tm_position):
                tm_position = ""
            position = TM_POSITION_MAP.get(str(tm_position), None)

            # Map type → is_starter (1 = starting XI, 0 = bench/substitute)
            tm_type = row.get("type", "")
            is_starter = 1 if tm_type == "starting_lineup" else 0

            # Map shirt number (TM 'number' column, stored as string)
            shirt_number = None
            raw_number = row.get("number")
            if pd.notna(raw_number):
                try:
                    shirt_number = int(float(raw_number))
                except (ValueError, TypeError):
                    pass

            lineup_entry = MatchLineup(
                match_id=match_id,
                team_id=team_id,
                player_name=str(player_name),
                position=position,
                is_starter=is_starter,
                shirt_number=shirt_number,
            )
            session.add(lineup_entry)
            existing_keys.add(key)
            stats["inserted"] += 1
            game_had_rows = True

        if game_had_rows:
            stats["games_with_lineups"] += 1

        # Batch commit every N games to control memory usage
        batch_count += 1
        if batch_count % batch_size == 0:
            try:
                session.flush()
                session.commit()
                logger.info(
                    "Lineup backfill progress: %d/%d games, %d inserted, "
                    "%d skipped",
                    stats["games_processed"], len(tm_to_match),
                    stats["inserted"], stats["skipped"],
                )
            except Exception as e:
                logger.error("Batch commit failed at game %d: %s",
                             batch_count, e)
                session.rollback()
                stats["errors"] += 1

    # Final commit for remaining rows
    try:
        session.commit()
    except Exception as e:
        logger.error("Final commit failed: %s", e)
        session.rollback()
        stats["errors"] += 1

    logger.info(
        "Lineup backfill complete: %d games processed, %d with lineups, "
        "%d rows inserted, %d skipped (existing), %d errors",
        stats["games_processed"], stats["games_with_lineups"],
        stats["inserted"], stats["skipped"], stats["errors"],
    )

    return stats


# ---------------------------------------------------------------------------
# E40-03: Formation Backfill from TM games table
# ---------------------------------------------------------------------------

def backfill_formations_from_tm(session) -> Dict[str, int]:
    """Backfill ``Match.home_formation`` and ``Match.away_formation`` from TM.

    The TM ``games.csv.gz`` table has ``home_club_formation`` and
    ``away_club_formation`` for ~90% of matches.  These are strings like
    "4-2-3-1", "4-3-3 Attacking", "3-5-2 flat", etc.  The
    ``formation_changed`` feature (E39-10) compares consecutive match
    formations — this backfill provides the data it needs.

    Only updates NULL formations — never overwrites data already populated
    by other sources (e.g., Soccerdata evening pipeline).  This makes the
    function **idempotent** and safe to re-run.

    Parameters
    ----------
    session : SQLAlchemy session
        Active database session.

    Returns
    -------
    dict
        Stats dict with keys: ``updated``, ``skipped_null_tm``,
        ``skipped_already_set``, ``games_processed``, ``errors``.
    """
    from src.database.models import Match

    stats = {
        "updated": 0,
        "skipped_null_tm": 0,
        "skipped_already_set": 0,
        "games_processed": 0,
        "errors": 0,
    }

    # 1. Load TM games
    tm_games = load_tm_games()
    if tm_games.empty:
        logger.error("No TM games data available — aborting formation backfill")
        return stats

    # 2. Get all matches with transfermarkt_game_id
    matched_records = (
        session.query(
            Match.id, Match.transfermarkt_game_id,
            Match.home_formation, Match.away_formation,
        )
        .filter(Match.transfermarkt_game_id.isnot(None))
        .all()
    )

    if not matched_records:
        logger.warning("No matches have transfermarkt_game_id — "
                        "run persist_tm_match_mapping first")
        return stats

    # Build lookup: tm_game_id → match record tuple
    tm_to_match: Dict[int, tuple] = {}
    for mid, tm_gid, hform, aform in matched_records:
        tm_to_match[tm_gid] = (mid, hform, aform)

    # 3. Build TM game formation lookup: game_id → (home_formation, away_formation)
    relevant_ids = set(tm_to_match.keys())
    relevant_games = tm_games[tm_games["game_id"].isin(relevant_ids)]

    tm_formations: Dict[int, tuple] = {}
    for _, row in relevant_games.iterrows():
        gid = int(row["game_id"])
        hf = row.get("home_club_formation")
        af = row.get("away_club_formation")
        # Only store non-NaN formations
        hf_str = str(hf).strip() if pd.notna(hf) and str(hf).strip() else None
        af_str = str(af).strip() if pd.notna(af) and str(af).strip() else None
        tm_formations[gid] = (hf_str, af_str)

    logger.info(
        "Formation backfill: %d matched games, %d with TM formation data",
        len(tm_to_match), len(tm_formations),
    )

    # 4. Update matches in batches
    batch_count = 0
    batch_size = 500
    match_ids_to_update = []

    for tm_gid, (match_id, existing_hform, existing_aform) in tm_to_match.items():
        stats["games_processed"] += 1

        tm_data = tm_formations.get(tm_gid)
        if tm_data is None:
            stats["skipped_null_tm"] += 1
            continue

        tm_hform, tm_aform = tm_data

        # Only update NULL formations — don't overwrite existing data
        needs_update = False

        if not existing_hform and tm_hform:
            needs_update = True
        if not existing_aform and tm_aform:
            needs_update = True

        if not needs_update:
            # Both already set or TM has nothing new
            if existing_hform or existing_aform:
                stats["skipped_already_set"] += 1
            else:
                stats["skipped_null_tm"] += 1
            continue

        match_ids_to_update.append((match_id, tm_hform, tm_aform, existing_hform, existing_aform))

    # Now do the actual DB updates in batches
    logger.info("Updating %d matches with formation data", len(match_ids_to_update))

    for i in range(0, len(match_ids_to_update), batch_size):
        batch = match_ids_to_update[i: i + batch_size]
        batch_mid_list = [mid for mid, _, _, _, _ in batch]

        matches_by_id = {
            m.id: m
            for m in session.query(Match).filter(Match.id.in_(batch_mid_list)).all()
        }

        for mid, tm_hform, tm_aform, existing_hform, existing_aform in batch:
            match = matches_by_id.get(mid)
            if match is None:
                stats["errors"] += 1
                continue

            if not existing_hform and tm_hform:
                match.home_formation = tm_hform
            if not existing_aform and tm_aform:
                match.away_formation = tm_aform
            stats["updated"] += 1

        try:
            session.flush()
            session.commit()
        except Exception as e:
            logger.error("Formation batch commit failed: %s", e)
            session.rollback()
            stats["errors"] += 1

        batch_count += 1
        if batch_count % 5 == 0:
            logger.info(
                "Formation backfill progress: %d/%d matches updated",
                min(i + batch_size, len(match_ids_to_update)),
                len(match_ids_to_update),
            )

    logger.info(
        "Formation backfill complete: %d updated, %d skipped (TM null), "
        "%d skipped (already set), %d errors",
        stats["updated"], stats["skipped_null_tm"],
        stats["skipped_already_set"], stats["errors"],
    )

    return stats


# ---------------------------------------------------------------------------
# E40-04: Manager Backfill from TM games table
# ---------------------------------------------------------------------------

def backfill_managers_from_tm(session) -> Dict[str, int]:
    """Backfill ``Match.home_manager_name`` and ``Match.away_manager_name``.

    The TM ``games.csv.gz`` table has ``home_club_manager_name`` and
    ``away_club_manager_name`` with 100% coverage across all 5 leagues.
    This data enables the manager features in E40-05: new_manager_flag,
    manager_tenure_days, manager_win_pct, and manager_change_count.

    Only updates NULL values — never overwrites manager names already
    populated from other sources.  This makes the function **idempotent**.

    Parameters
    ----------
    session : SQLAlchemy session
        Active database session.

    Returns
    -------
    dict
        Stats dict with keys: ``updated``, ``skipped_null_tm``,
        ``skipped_already_set``, ``games_processed``, ``errors``.
    """
    from src.database.models import Match

    stats = {
        "updated": 0,
        "skipped_null_tm": 0,
        "skipped_already_set": 0,
        "games_processed": 0,
        "errors": 0,
    }

    # 1. Load TM games
    tm_games = load_tm_games()
    if tm_games.empty:
        logger.error("No TM games data available — aborting manager backfill")
        return stats

    # 2. Get all matches with transfermarkt_game_id
    matched_records = (
        session.query(
            Match.id, Match.transfermarkt_game_id,
            Match.home_manager_name, Match.away_manager_name,
        )
        .filter(Match.transfermarkt_game_id.isnot(None))
        .all()
    )

    if not matched_records:
        logger.warning("No matches have transfermarkt_game_id — "
                        "run persist_tm_match_mapping first")
        return stats

    # Build lookup: tm_game_id → (match_id, existing home/away manager)
    tm_to_match: Dict[int, tuple] = {}
    for mid, tm_gid, hm, am in matched_records:
        tm_to_match[tm_gid] = (mid, hm, am)

    # 3. Build TM manager lookup: game_id → (home_manager, away_manager)
    relevant_ids = set(tm_to_match.keys())
    relevant_games = tm_games[tm_games["game_id"].isin(relevant_ids)]

    tm_managers: Dict[int, tuple] = {}
    for _, row in relevant_games.iterrows():
        gid = int(row["game_id"])
        hm = row.get("home_club_manager_name")
        am = row.get("away_club_manager_name")
        # Clean manager names — strip whitespace, reject empty/NaN
        hm_str = str(hm).strip() if pd.notna(hm) and str(hm).strip() else None
        am_str = str(am).strip() if pd.notna(am) and str(am).strip() else None
        tm_managers[gid] = (hm_str, am_str)

    logger.info(
        "Manager backfill: %d matched games, %d with TM manager data",
        len(tm_to_match), len(tm_managers),
    )

    # 4. Identify matches needing updates
    match_ids_to_update = []

    for tm_gid, (match_id, existing_hm, existing_am) in tm_to_match.items():
        stats["games_processed"] += 1

        tm_data = tm_managers.get(tm_gid)
        if tm_data is None:
            stats["skipped_null_tm"] += 1
            continue

        tm_hm, tm_am = tm_data

        # Only update NULL values — don't overwrite existing data
        needs_update = False
        if not existing_hm and tm_hm:
            needs_update = True
        if not existing_am and tm_am:
            needs_update = True

        if not needs_update:
            if existing_hm or existing_am:
                stats["skipped_already_set"] += 1
            else:
                stats["skipped_null_tm"] += 1
            continue

        match_ids_to_update.append(
            (match_id, tm_hm, tm_am, existing_hm, existing_am)
        )

    # 5. DB updates in batches
    batch_size = 500
    logger.info("Updating %d matches with manager data", len(match_ids_to_update))

    for i in range(0, len(match_ids_to_update), batch_size):
        batch = match_ids_to_update[i: i + batch_size]
        batch_mid_list = [mid for mid, _, _, _, _ in batch]

        matches_by_id = {
            m.id: m
            for m in session.query(Match).filter(Match.id.in_(batch_mid_list)).all()
        }

        for mid, tm_hm, tm_am, existing_hm, existing_am in batch:
            match = matches_by_id.get(mid)
            if match is None:
                stats["errors"] += 1
                continue

            if not existing_hm and tm_hm:
                match.home_manager_name = tm_hm
            if not existing_am and tm_am:
                match.away_manager_name = tm_am
            stats["updated"] += 1

        try:
            session.flush()
            session.commit()
        except Exception as e:
            logger.error("Manager batch commit failed: %s", e)
            session.rollback()
            stats["errors"] += 1

    logger.info(
        "Manager backfill complete: %d updated, %d skipped (TM null), "
        "%d skipped (already set), %d errors",
        stats["updated"], stats["skipped_null_tm"],
        stats["skipped_already_set"], stats["errors"],
    )

    return stats
