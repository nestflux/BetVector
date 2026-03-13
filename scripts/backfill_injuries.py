"""
BetVector — Historical Injury Backfill Script (E39-04)
======================================================
Downloads injury data from salimt/football-datasets on GitHub and loads
it into the ``team_injuries`` table for historical feature computation.

**Data source:** salimt/football-datasets (Transfermarkt-sourced)
  - 143K+ injury records across 34K+ players
  - Dates from 2013 to present
  - All major European leagues covered

**Important limitation:**
  The player profiles CSV only has each player's *current* club, not
  historical clubs.  If a player transferred between clubs, their
  historical injuries may be mapped to the wrong team.  This is an
  acceptable trade-off — the data still provides significant value for
  the injury features, and the vast majority of injuries for current
  squad players occurred at their current clubs.

**Usage:**
  python scripts/backfill_injuries.py [--league EPL] [--from-season 2020]
  python scripts/backfill_injuries.py --all

Master Plan refs: MP §5 (Data Sources), MP §6 (team_injuries schema)
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd
import requests

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.database.db import get_session
from src.database.models import League, PlayerValue, Team, TeamInjury

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================================
# Data source URLs (salimt/football-datasets on GitHub)
# ============================================================================
INJURY_CSV_URL = (
    "https://raw.githubusercontent.com/salimt/football-datasets/main/"
    "datalake/transfermarkt/player_injuries/player_injuries.csv"
)

# Transfermarkt CDN players CSV (same one used by TransfermarktScraper)
# Provides player_id → current_club_name + current_club_domestic_competition_id
PLAYERS_CDN_URL = (
    "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/players.csv.gz"
)

# ============================================================================
# Team Name Mapping — Transfermarkt CDN ``current_club_name`` → canonical DB names
# ============================================================================
# The CDN uses full formal club names (e.g. "Manchester United Football Club")
# which differ from both the short names in our DB (e.g. "Manchester United")
# and the abbreviated names used by Football-Data.co.uk.
SALIMT_TEAM_MAP: Dict[str, str] = {
    # --- EPL (GB1) — DB uses Football-Data.co.uk full names ---
    "Arsenal Football Club": "Arsenal",
    "Association Football Club Bournemouth": "AFC Bournemouth",
    "Aston Villa Football Club": "Aston Villa",
    "Brentford Football Club": "Brentford",
    "Brighton and Hove Albion Football Club": "Brighton & Hove Albion",
    "Burnley Football Club": "Burnley",
    "Chelsea Football Club": "Chelsea",
    "Crystal Palace Football Club": "Crystal Palace",
    "Everton Football Club": "Everton",
    "Fulham Football Club": "Fulham",
    "Ipswich Town": "Ipswich Town",
    "Leeds United Association Football Club": "Leeds United",
    "Leicester City": "Leicester City",
    "Liverpool Football Club": "Liverpool",
    "Luton Town": "Luton Town",
    "Manchester City Football Club": "Manchester City",
    "Manchester United Football Club": "Manchester United",
    "Newcastle United Football Club": "Newcastle United",
    "Norwich City": "Norwich City",
    "Nottingham Forest Football Club": "Nottingham Forest",
    "Sheffield United": "Sheffield United",
    "Southampton FC": "Southampton",
    "Sunderland Association Football Club": "Sunderland",
    "Tottenham Hotspur Football Club": "Tottenham Hotspur",
    "Watford FC": "Watford",
    "West Bromwich Albion": "West Bromwich Albion",
    "West Ham United Football Club": "West Ham United",
    "Wolverhampton Wanderers Football Club": "Wolverhampton Wanderers",
    # EPL historical / cross-league (CDN competition=GB1 but now in lower leagues)
    "Cardiff City": "Cardiff",
    "Huddersfield Town": "Huddersfield",
    "Hull City": "Hull",
    "Middlesbrough FC": "Middlesbrough",
    "Queens Park Rangers": "QPR",
    "Reading FC": "Reading",
    "Stoke City": "Stoke",
    "Swansea City": "Swansea",
    "Wigan Athletic": "Wigan",

    # --- La Liga (ES1) ---
    "Athletic Club Bilbao": "Ath Bilbao",
    "Club Atlético de Madrid S.A.D.": "Ath Madrid",
    "Futbol Club Barcelona": "Barcelona",
    "Real Madrid Club de Fútbol": "Real Madrid",
    "Sevilla Fútbol Club S.A.D.": "Sevilla",
    "Valencia Club de Fútbol S. A. D.": "Valencia",
    "Villarreal Club de Fútbol S.A.D.": "Villarreal",
    "Real Sociedad de Fútbol S.A.D.": "Sociedad",
    "Real Betis Balompié S.A.D.": "Betis",
    "Real Club Celta de Vigo S. A. D.": "Celta",
    "Getafe Club de Fútbol S. A. D. Team Dubai": "Getafe",
    "Club Atlético Osasuna": "Osasuna",
    "Real Club Deportivo Mallorca S.A.D.": "Mallorca",
    "Rayo Vallecano de Madrid S. A. D.": "Vallecano",
    "CD Leganés": "Leganes",
    "UD Las Palmas": "Las Palmas",
    "Girona Fútbol Club S. A. D.": "Girona",
    "Reial Club Deportiu Espanyol de Barcelona S.A.D.": "Espanol",
    "Real Valladolid CF": "Valladolid",
    "Deportivo Alavés S. A. D.": "Alaves",
    "Cádiz CF": "Cadiz",
    "UD Almería": "Almeria",
    "SD Eibar": "Eibar",
    "SD Huesca": "Huesca",
    "Elche Club de Fútbol S.A.D.": "Elche",
    "Granada CF": "Granada",
    "Levante Unión Deportiva S.A.D.": "Levante",
    "Real Oviedo S.A.D.": "Oviedo",

    # --- Ligue 1 (FR1) ---
    "Paris Saint-Germain Football Club": "Paris SG",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "Association sportive de Monaco Football Club": "Monaco",
    "AS Saint-Étienne": "St Etienne",
    "Stade Rennais Football Club": "Rennes",
    "Stade Reims": "Reims",
    "Racing Club de Strasbourg Alsace": "Strasbourg",
    "Racing Club de Lens": "Lens",
    "Olympique Gymnaste Club Nice Côte d\u2019Azur": "Nice",
    "Olympique Gymnaste Club Nice C\u00f4te d'Azur": "Nice",
    "Football Club de Nantes": "Nantes",
    "Le Havre Athletic Club": "Le Havre",
    "Association de la Jeunesse auxerroise": "Auxerre",
    "Angers Sporting Club de l\u2019Ouest": "Angers",
    "Angers Sporting Club de l'Ouest": "Angers",
    "Toulouse Football Club": "Toulouse",
    "Montpellier HSC": "Montpellier",
    "Stade brestois 29": "Brest",
    "Lille Olympique Sporting Club": "Lille",
    "Clermont Foot 63": "Clermont",
    "Football Club Lorient-Bretagne Sud": "Lorient",
    "Football Club de Metz": "Metz",
    "FC Girondins Bordeaux": "Bordeaux",
    "ESTAC Troyes": "Troyes",
    "Dijon FCO": "Dijon",
    "Nîmes Olympique": "Nimes",
    "AC Ajaccio": "Ajaccio",
    "Paris Football Club": "Paris FC",

    # --- Bundesliga (L1) ---
    "FC Bayern München": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "RasenBallsport Leipzig": "RB Leipzig",
    "Bayer 04 Leverkusen Fußball": "Leverkusen",
    "Eintracht Frankfurt Fußball AG": "Ein Frankfurt",
    "Verein für Leibesübungen Wolfsburg": "Wolfsburg",
    "Borussia Verein für Leibesübungen 1900 Mönchengladbach": "M'gladbach",
    "Sport-Club Freiburg": "Freiburg",
    "1. Fußball- und Sportverein Mainz 05": "Mainz",
    "Fußball-Club Augsburg 1907": "Augsburg",
    "Verein für Bewegungsspiele Stuttgart 1893": "Stuttgart",
    "1. Fußballclub Union Berlin": "Union Berlin",
    "1. Fußballclub Heidenheim 1846": "Heidenheim",
    "Sportverein Werder Bremen von 1899": "Werder Bremen",
    "Turn- und Sportgemeinschaft 1899 Hoffenheim Fußball-Spielbetriebs": "Hoffenheim",
    "Holstein Kiel": "Holstein Kiel",
    "Fußball-Club St. Pauli von 1910": "St Pauli",
    "Hertha BSC": "Hertha",
    "1. Fußball-Club Köln": "FC Koln",
    "FC Schalke 04": "Schalke 04",
    "Arminia Bielefeld": "Bielefeld",
    "VfL Bochum": "Bochum",
    "SV Darmstadt 98": "Darmstadt",
    "SpVgg Greuther Fürth": "Greuther Furth",
    "Hamburger Sport Verein": "Hamburg",
    # Bundesliga historical (not in our DB but prevents not_found noise)
    "1.FC Nuremberg": "Nuremberg",
    "Eintracht Braunschweig": "Braunschweig",
    "FC Ingolstadt 04": "Ingolstadt",
    "Fortuna Düsseldorf": "Dusseldorf",
    "Hannover 96": "Hannover",
    "SC Paderborn 07": "Paderborn",

    # --- Serie A (IT1) ---
    "Associazione Calcio Milan": "Milan",
    "Football Club Internazionale Milano S.p.A.": "Inter",
    "Associazione Sportiva Roma": "Roma",
    "Società Sportiva Lazio S.p.A.": "Lazio",
    "Società Sportiva Calcio Napoli": "Napoli",
    "Associazione Calcio Fiorentina": "Fiorentina",
    "Atalanta Bergamasca Calcio S.p.a.": "Atalanta",
    "Torino Calcio": "Torino",
    "Bologna Football Club 1909": "Bologna",
    "Unione Sportiva Lecce": "Lecce",
    "Cagliari Calcio": "Cagliari",
    "Genoa Cricket and Football Club": "Genoa",
    "Verona Hellas Football Club": "Verona",
    "Udinese Calcio": "Udinese",
    "Unione Sportiva Sassuolo Calcio": "Sassuolo",
    "FC Empoli": "Empoli",
    "Parma Calcio 1913": "Parma",
    "AC Monza": "Monza",
    "Calcio Como": "Como",
    "Venezia FC": "Venezia",
    "UC Sampdoria": "Sampdoria",
    "Spezia Calcio": "Spezia",
    "US Salernitana 1919": "Salernitana",
    "Juventus Football Club": "Juventus",
    "Frosinone Calcio": "Frosinone",
    "Benevento Calcio": "Benevento",
    "FC Crotone": "Crotone",
    "Unione Sportiva Cremonese S.p.A.": "Cremonese",
    "Pisa Sporting Club": "Pisa",
}

# Competition ID → league short_name mapping (Transfermarkt CDN IDs)
COMPETITION_TO_LEAGUE: Dict[str, str] = {
    "GB1": "EPL",
    "GB2": "Championship",
    "ES1": "LaLiga",
    "FR1": "Ligue1",
    "L1": "Bundesliga",
    "IT1": "SerieA",
}

# Config short_name → DB League.name mapping
# (DB names come from Football-Data.co.uk; config short_names are abbreviated)
SHORT_NAME_TO_DB: Dict[str, str] = {
    "EPL": "English Premier League",
    "Championship": "Championship",
    "LaLiga": "La Liga",
    "Ligue1": "Ligue 1",
    "Bundesliga": "Bundesliga",
    "SerieA": "Serie A",
}


def _map_team_name(cdn_name: str) -> str:
    """Map a Transfermarkt CDN club name to our canonical DB name."""
    mapped = SALIMT_TEAM_MAP.get(cdn_name)
    if mapped:
        return mapped
    # Fallback: strip common suffixes
    for suffix in [" FC", " AFC", " CF"]:
        if cdn_name.endswith(suffix):
            stripped = cdn_name[:-len(suffix)].strip()
            if stripped in SALIMT_TEAM_MAP.values():
                return stripped
    return cdn_name


def _season_to_year(season_name: str) -> Optional[int]:
    """Convert '20/21' or '2020/21' to start year 2020.
    Also handles '24/25' → 2024.
    """
    try:
        parts = season_name.strip().split("/")
        if len(parts) == 2:
            first = int(parts[0])
            if first < 100:
                # Two-digit year: '20' → 2020, '99' → 1999
                first = 2000 + first if first < 50 else 1900 + first
            return first
    except (ValueError, IndexError):
        pass
    return None


def download_data() -> tuple:
    """Download injury CSV and players CSV from GitHub/CDN.

    Returns (injuries_df, players_df) or raises on failure.
    """
    logger.info("Downloading injury CSV from salimt/football-datasets...")
    r_inj = requests.get(INJURY_CSV_URL, timeout=120)
    r_inj.raise_for_status()
    injuries_df = pd.read_csv(io.StringIO(r_inj.text))
    logger.info(f"  Injury CSV: {len(injuries_df)} records")

    logger.info("Downloading players CSV from Transfermarkt CDN...")
    r_players = requests.get(PLAYERS_CDN_URL, timeout=120)
    r_players.raise_for_status()
    players_df = pd.read_csv(io.BytesIO(r_players.content), compression="gzip")
    logger.info(f"  Players CSV: {len(players_df)} records")

    return injuries_df, players_df


def process_injuries(
    injuries_df: pd.DataFrame,
    players_df: pd.DataFrame,
    league_filter: Optional[str] = None,
    from_season: int = 2020,
) -> pd.DataFrame:
    """Join injury data with player→team mapping and filter.

    Parameters
    ----------
    injuries_df : pd.DataFrame
        Raw injury CSV data.
    players_df : pd.DataFrame
        Transfermarkt CDN players CSV.
    league_filter : str, optional
        If set, only include injuries for this league's short_name.
    from_season : int
        Only include injuries from this season onwards (start year).

    Returns
    -------
    pd.DataFrame
        Columns: team_name, player_name, injury_type, from_date, end_date,
        days_missed, games_missed, competition_id.
    """
    # Filter players to our 6 leagues
    valid_competitions = set(COMPETITION_TO_LEAGUE.keys())
    league_players = players_df[
        players_df["current_club_domestic_competition_id"].isin(valid_competitions)
    ].copy()

    if league_filter:
        # Find competition_id for the target league
        comp_id = None
        for cid, short in COMPETITION_TO_LEAGUE.items():
            if short == league_filter:
                comp_id = cid
                break
        if comp_id:
            league_players = league_players[
                league_players["current_club_domestic_competition_id"] == comp_id
            ]

    # Build player_id → (player_name, team_name, competition_id) lookup
    player_lookup = {}
    for _, row in league_players.iterrows():
        pid = row["player_id"]
        player_lookup[pid] = {
            "player_name": row["name"],
            "team_name": _map_team_name(str(row["current_club_name"])),
            "competition_id": row["current_club_domestic_competition_id"],
        }

    logger.info(f"  Players in target leagues: {len(player_lookup)}")

    # Filter injuries to our players and date range
    injuries_df = injuries_df.copy()
    injuries_df["start_year"] = injuries_df["season_name"].apply(_season_to_year)
    injuries_df = injuries_df[
        (injuries_df["player_id"].isin(player_lookup)) &
        (injuries_df["start_year"].notna()) &
        (injuries_df["start_year"] >= from_season)
    ]

    logger.info(f"  Injuries matching filters: {len(injuries_df)}")

    # Build output DataFrame
    rows = []
    for _, row in injuries_df.iterrows():
        pinfo = player_lookup.get(row["player_id"])
        if not pinfo:
            continue
        rows.append({
            "team_name": pinfo["team_name"],
            "player_name": pinfo["player_name"],
            "injury_type": str(row["injury_reason"]) if pd.notna(row["injury_reason"]) else None,
            "from_date": str(row["from_date"]) if pd.notna(row["from_date"]) else None,
            "end_date": str(row["end_date"]) if pd.notna(row["end_date"]) else None,
            "days_missed": int(row["days_missed"]) if pd.notna(row["days_missed"]) else None,
            "games_missed": int(row["games_missed"]) if pd.notna(row["games_missed"]) else None,
            "competition_id": pinfo["competition_id"],
        })

    result = pd.DataFrame(rows)
    logger.info(f"  Processed injuries: {len(result)}")
    return result


def load_historical_injuries(
    df: pd.DataFrame,
    league_id: int,
) -> Dict[str, int]:
    """Load historical injury data into the team_injuries table.

    Maps team names to DB records and inserts injury entries.
    Deduplication via (team_id, player_name, reported_at) — the
    ``reported_at`` field is set to ``from_date``.

    Parameters
    ----------
    df : pd.DataFrame
        Processed injury DataFrame with team_name, player_name,
        injury_type, from_date, end_date, days_missed columns.
    league_id : int
        Database league ID.

    Returns
    -------
    dict
        Keys: new, skipped, not_found, total.
    """
    if df is None or df.empty:
        return {"new": 0, "skipped": 0, "not_found": 0, "total": 0}

    new_count = 0
    skipped_count = 0
    not_found_teams: Set[str] = set()

    with get_session() as session:
        # Build team name → id lookup
        teams = session.query(Team).filter_by(league_id=league_id).all()
        name_to_id: Dict[str, int] = {t.name: t.id for t in teams}
        name_lower_map: Dict[str, int] = {
            t.name.lower(): t.id for t in teams
        }

        # Load PlayerValue for market_value lookup
        pv_lookup: Dict[tuple, float] = {}
        pvs = session.query(PlayerValue).filter(
            PlayerValue.team_id.in_([t.id for t in teams])
        ).all()
        for pv in pvs:
            key = (pv.team_id, pv.player_name.lower().strip())
            pv_lookup[key] = pv.market_value_eur

        for _, row in df.iterrows():
            team_name = str(row.get("team_name", "")).strip()
            player_name = str(row.get("player_name", "")).strip()
            from_date = str(row.get("from_date", "")).strip()
            end_date = str(row.get("end_date", "")).strip() or None
            injury_type = row.get("injury_type")
            days_missed = row.get("days_missed")

            if (not team_name or not player_name or not from_date
                    or from_date in ("nan", "None", "NaT")):
                continue

            # Find team in DB
            team_id = name_to_id.get(team_name)
            if not team_id:
                team_id = name_lower_map.get(team_name.lower())
            if not team_id:
                not_found_teams.add(team_name)
                continue

            # Get player market value for the record
            pv_key = (team_id, player_name.lower().strip())
            market_value = pv_lookup.get(pv_key)

            # Check for existing record (dedup)
            existing = session.query(TeamInjury).filter_by(
                team_id=team_id,
                player_name=player_name,
                reported_at=from_date,
            ).first()

            if existing is not None:
                skipped_count += 1
                continue

            # Determine status based on end_date
            status = "returned" if end_date else "injured"

            injury = TeamInjury(
                team_id=team_id,
                player_name=player_name,
                injury_type=str(injury_type) if injury_type else None,
                days_out=int(days_missed) if pd.notna(days_missed) else None,
                player_market_value=market_value,
                status=status,
                reported_at=from_date,
                expected_return=end_date,
                source="salimt_football_datasets",
            )
            session.add(injury)
            new_count += 1

            # Commit in batches of 500 to avoid memory issues
            if new_count % 500 == 0:
                session.commit()
                logger.info(f"    Committed {new_count} records...")

        session.commit()

    if not_found_teams:
        logger.warning(
            "  %d teams not found: %s",
            len(not_found_teams), sorted(not_found_teams)[:10],
        )

    return {
        "new": new_count,
        "skipped": skipped_count,
        "not_found": len(not_found_teams),
        "total": new_count + skipped_count,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical injury data from salimt/football-datasets"
    )
    parser.add_argument(
        "--league", type=str, default=None,
        help="League short_name to backfill (e.g., EPL, LaLiga). Default: all leagues."
    )
    parser.add_argument(
        "--from-season", type=int, default=2020,
        help="Start year for injuries (default: 2020 = 2020-21 season onwards)"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Backfill all 6 leagues"
    )
    args = parser.parse_args()

    # Download data
    injuries_df, players_df = download_data()

    # Get league configs
    leagues = config.get_active_leagues()
    if args.league and not args.all:
        leagues = [lg for lg in leagues if lg.short_name == args.league]
        if not leagues:
            print(f"ERROR: League '{args.league}' not found in config")
            sys.exit(1)

    total_loaded = 0
    for lg in leagues:
        league_name = lg.short_name
        print(f"\n{'='*60}")
        print(f"  {league_name}")
        print(f"{'='*60}")

        # Get league_id from DB using our short_name → DB name mapping
        db_name = SHORT_NAME_TO_DB.get(league_name)
        with get_session() as session:
            db_league = None
            if db_name:
                db_league = session.query(League).filter_by(
                    name=db_name,
                ).first()
            if not db_league:
                # Fallback: substring match
                for l in session.query(League).all():
                    if league_name.lower() in l.name.lower():
                        db_league = l
                        break
            league_id = db_league.id if db_league else None

        if not league_id:
            print(f"  SKIP: League '{league_name}' not in DB")
            continue

        # Process injuries for this league
        processed = process_injuries(
            injuries_df, players_df,
            league_filter=league_name,
            from_season=args.from_season,
        )

        if processed.empty:
            print(f"  No injuries found for {league_name}")
            continue

        # Load into DB
        result = load_historical_injuries(processed, league_id)
        print(f"  Result: {result}")
        total_loaded += result["new"]

    print(f"\n{'='*60}")
    print(f"  TOTAL: {total_loaded} new injury records loaded")
    print(f"{'='*60}")

    # Final count
    with get_session() as session:
        total = session.query(TeamInjury).count()
        print(f"  DB total: {total} TeamInjury rows")


if __name__ == "__main__":
    main()
