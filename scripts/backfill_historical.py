#!/usr/bin/env python3
"""
BetVector — Historical Data Backfill (E23-01 through E23-05)
=================================================================
Loads historical match results, odds, xG data, and Elo ratings for EPL
seasons that are missing from the database, then recomputes all features.
Uses the same scrapers, loaders, and feature engineer that the daily
pipeline uses, so all team name normalisation, odds parsing, deduplication,
and feature computation logic is shared.

Usage::

    # Load matches + odds for empty seasons (E23-01)
    python scripts/backfill_historical.py matches

    # Load Understat xG + advanced stats (E23-02)
    python scripts/backfill_historical.py understat

    # Load shot-level set-piece vs open-play xG breakdown (E23-03)
    python scripts/backfill_historical.py shot-xg

    # Backfill ClubElo ratings for historical seasons (E23-04)
    python scripts/backfill_historical.py clubelo

    # Recompute features for all 6 seasons (E23-05)
    python scripts/backfill_historical.py features

    # Run all five in sequence
    python scripts/backfill_historical.py all

    # Override seasons
    python scripts/backfill_historical.py matches --seasons 2022-23 2023-24

    # Dry-run: download data but don't load into DB
    python scripts/backfill_historical.py understat --dry-run

The script is fully idempotent — re-running it produces zero
duplicate records.  All loaders check for existing records
before inserting.  Feature recomputation uses force_recompute=True
to ensure all features reflect the latest data.

Expected output for a clean DB:
  - matches: 4 seasons × 380 = 1,520 Match records + ~22,800 Odds
  - understat: 5 seasons × 380 × 2 = ~3,800 MatchStat records
  - shot-xg: ~3,800 MatchStat rows updated with set_piece_xg/open_play_xg
    (slowest step: ~60 minutes for 5 seasons due to per-match API calls)
  - clubelo: ~600 unique dates × ~23 EPL teams ≈ ~13,000 ClubElo records
  - features: 6 seasons × 380 × 2 = ~4,560 Feature rows
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on PYTHONPATH so ``from src.x import y`` works
# even when running the script directly (not via ``python -m``).
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from src.config import BetVectorConfig  # noqa: E402
from src.database.db import get_session  # noqa: E402
from src.database.models import League, Season  # noqa: E402
from src.scrapers.football_data import FootballDataScraper  # noqa: E402
from src.scrapers.loader import (  # noqa: E402
    load_matches, load_odds, load_understat_stats, load_understat_shot_xg,
    load_clubelo_ratings,
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_historical")

# ---------------------------------------------------------------------------
# Default season lists for each backfill type
# ---------------------------------------------------------------------------

# E23-01: Match + odds backfill — seasons with zero match data
DEFAULT_MATCH_SEASONS = [
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
]

# E23-02: Understat xG backfill — seasons with zero or incomplete MatchStats.
# Includes 2024-25 which has Match records but zero MatchStats from Understat.
# 2025-26 already has 562 MatchStat rows so it's excluded.
DEFAULT_UNDERSTAT_SEASONS = [
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
]

# E23-03: Shot-level xG breakdown — populates set_piece_xg and open_play_xg
# on existing MatchStat records.  Same seasons as E23-02.
# 2025-26 already has this data (populated during daily pipeline).
# NOTE: This is the slowest backfill step (~60 min) because each match
# requires its own API call for shot-level data.
DEFAULT_SHOT_XG_SEASONS = [
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
]

# E23-04: ClubElo backfill — fetch Elo ratings for all match dates in the
# 4 historical seasons that had zero data.  ClubElo API is free, no auth.
# 2024-25 and 2025-26 already have Elo data from daily pipeline.
DEFAULT_CLUBELO_SEASONS = [
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
]

# E23-05: Recompute features for ALL seasons.  After backfilling match data,
# xG stats, shot-level xG, and ClubElo, we need to recompute every Feature
# row so rolling windows, Elo, referee stats, and market features use the
# now-complete data.  This covers all 6 seasons including current.
DEFAULT_FEATURE_SEASONS = [
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
    "2025-26",
]


# ============================================================================
# Shared Helpers
# ============================================================================

def _get_league_id(short_name: str = "EPL") -> int:
    """Look up the database ID for a league by short_name.

    The league must already exist in the DB (created during initial setup
    by ``run_pipeline.py setup`` or ``seed.py``).
    """
    with get_session() as session:
        league = session.query(League).filter_by(short_name=short_name).first()
        if league is None:
            raise RuntimeError(
                f"League '{short_name}' not found in the database. "
                f"Run 'python run_pipeline.py setup' first to seed leagues."
            )
        return league.id


def _ensure_season_exists(league_id: int, season: str) -> None:
    """Make sure a Season row exists for this league + season.

    The seasons table stores metadata about each season (start/end dates,
    is_loaded flag).  If a row doesn't exist yet, create one so foreign
    key relationships are happy.
    """
    with get_session() as session:
        existing = session.query(Season).filter_by(
            league_id=league_id,
            season=season,
        ).first()
        if existing is None:
            new_season = Season(
                league_id=league_id,
                season=season,
                is_loaded=0,
            )
            session.add(new_season)
            logger.info("Created Season record for %s", season)


def _mark_season_loaded(league_id: int, season: str, start_date: str, end_date: str) -> None:
    """Update the Season row with date range and mark as loaded.

    Called after matches are successfully loaded.  The start/end dates
    come from the first and last match dates in the CSV.
    """
    with get_session() as session:
        season_row = session.query(Season).filter_by(
            league_id=league_id,
            season=season,
        ).first()
        if season_row:
            season_row.start_date = start_date
            season_row.end_date = end_date
            season_row.is_loaded = 1
            logger.info(
                "Marked season %s as loaded (%s to %s)",
                season, start_date, end_date,
            )


# ============================================================================
# E23-01: Match + Odds Backfill
# ============================================================================

def backfill_season_matches(
    scraper: FootballDataScraper,
    league_config: object,
    league_id: int,
    season: str,
    dry_run: bool = False,
) -> dict:
    """Backfill one historical season: scrape CSV, load matches, load odds.

    Parameters
    ----------
    scraper : FootballDataScraper
        Reusable scraper instance (handles rate limiting).
    league_config : ConfigNamespace
        League config from ``config.get_active_leagues()``.
    league_id : int
        Database ID for this league.
    season : str
        Season identifier, e.g. "2022-23".
    dry_run : bool
        If True, download and parse the CSV but skip DB inserts.

    Returns
    -------
    dict
        Summary with keys: season, matches_new, matches_skipped,
        odds_new, odds_skipped, errors.
    """
    result = {
        "season": season,
        "matches_new": 0,
        "matches_skipped": 0,
        "odds_new": 0,
        "odds_skipped": 0,
        "errors": [],
    }

    # --- 1. Scrape the CSV ------------------------------------------------
    try:
        df = scraper.scrape(league_config=league_config, season=season)
        logger.info("Season %s: Downloaded %d matches from CSV", season, len(df))
    except Exception as exc:
        error_msg = f"Season {season}: Scrape failed — {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)
        return result

    if df.empty:
        result["errors"].append(f"Season {season}: Empty CSV returned")
        return result

    if dry_run:
        logger.info(
            "Season %s: DRY RUN — %d matches parsed, skipping DB load",
            season, len(df),
        )
        teams = sorted(set(df["home_team"]) | set(df["away_team"]))
        logger.info("Season %s teams: %s", season, teams)
        return result

    # --- 2. Ensure Season row exists --------------------------------------
    _ensure_season_exists(league_id, season)

    # --- 3. Load matches --------------------------------------------------
    try:
        match_summary = load_matches(df, league_id, season)
        result["matches_new"] = match_summary["new"]
        result["matches_skipped"] = match_summary["skipped"]
        logger.info(
            "Season %s: Matches — %d new, %d skipped",
            season, match_summary["new"], match_summary["skipped"],
        )
    except Exception as exc:
        error_msg = f"Season {season}: Match loading failed — {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)
        return result  # Skip odds if matches failed

    # --- 4. Load odds -----------------------------------------------------
    try:
        odds_summary = load_odds(df, league_id)
        result["odds_new"] = odds_summary["new"]
        result["odds_skipped"] = odds_summary["skipped"]
        logger.info(
            "Season %s: Odds — %d new, %d skipped",
            season, odds_summary["new"], odds_summary["skipped"],
        )
    except Exception as exc:
        error_msg = f"Season {season}: Odds loading failed — {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)

    # --- 5. Update Season metadata ----------------------------------------
    if result["matches_new"] > 0:
        dates = sorted(df["date"].dropna().unique())
        if dates:
            _mark_season_loaded(league_id, season, dates[0], dates[-1])

    return result


# ============================================================================
# E23-02: Understat xG + Advanced Stats Backfill
# ============================================================================

def backfill_season_understat(
    league_config: object,
    league_id: int,
    season: str,
    dry_run: bool = False,
) -> dict:
    """Backfill Understat xG + advanced stats for one season.

    Downloads match-level xG, NPxG, PPDA, deep completions from Understat
    and loads them as MatchStat records.  Each match produces two rows
    (home team + away team).

    Rate limiting is handled by the UnderstatScraper (2s minimum between
    requests to understat.com).

    Parameters
    ----------
    league_config : ConfigNamespace
        League config with ``understat_league`` attribute.
    league_id : int
        Database ID for this league.
    season : str
        Season identifier, e.g. "2022-23".
    dry_run : bool
        If True, download data but skip DB inserts.

    Returns
    -------
    dict
        Summary with keys: season, stats_new, stats_skipped,
        stats_updated, stats_not_found, errors.
    """
    from src.scrapers.understat_scraper import UnderstatScraper

    result = {
        "season": season,
        "stats_new": 0,
        "stats_skipped": 0,
        "stats_updated": 0,
        "stats_not_found": 0,
        "errors": [],
    }

    # --- 1. Scrape Understat -----------------------------------------------
    scraper = UnderstatScraper()
    try:
        df = scraper.scrape(league_config=league_config, season=season)
        if df.empty:
            result["errors"].append(f"Season {season}: No Understat data returned")
            return result
        # Count finished matches (those with xG data)
        finished = df[df["home_xg"].notna()]
        logger.info(
            "Season %s: Understat returned %d matches (%d with xG)",
            season, len(df), len(finished),
        )
    except Exception as exc:
        error_msg = f"Season {season}: Understat scrape failed — {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)
        return result

    if dry_run:
        logger.info(
            "Season %s: DRY RUN — %d Understat matches parsed, skipping DB load",
            season, len(df),
        )
        # Show team names for verification
        teams = sorted(set(df["home_team"]) | set(df["away_team"]))
        logger.info("Season %s Understat teams: %s", season, teams)
        return result

    # --- 2. Load into match_stats table -----------------------------------
    try:
        stats_summary = load_understat_stats(df, league_id)
        result["stats_new"] = stats_summary["new"]
        result["stats_skipped"] = stats_summary["skipped"]
        result["stats_updated"] = stats_summary.get("updated", 0)
        result["stats_not_found"] = stats_summary.get("not_found", 0)
        logger.info(
            "Season %s: MatchStats — %d new, %d skipped, %d updated, "
            "%d not found in DB",
            season,
            stats_summary["new"],
            stats_summary["skipped"],
            stats_summary.get("updated", 0),
            stats_summary.get("not_found", 0),
        )
    except Exception as exc:
        error_msg = f"Season {season}: Understat loading failed — {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)

    return result


# ============================================================================
# E23-03: Shot-Level xG Breakdown Backfill
# ============================================================================

def backfill_season_shot_xg(
    league_config: object,
    league_id: int,
    season: str,
    dry_run: bool = False,
) -> dict:
    """Backfill shot-level set-piece vs open-play xG for one season.

    Uses ``UnderstatScraper.fetch_shot_xg_for_season()`` which makes one
    API call per finished match to get individual shot data, then aggregates
    into set_piece_xg (corners + free kicks + set pieces) and open_play_xg.

    This is the slowest backfill operation because of the per-match API calls.
    ~380 matches × 2s rate limit ≈ ~13 minutes per season.

    The loader only updates MatchStat rows where ``set_piece_xg IS NULL``,
    so it's safe to interrupt and restart — it picks up where it left off.

    Parameters
    ----------
    league_config : ConfigNamespace
        League config with ``understat_league`` attribute.
    league_id : int
        Database ID for this league.
    season : str
        Season identifier, e.g. "2022-23".
    dry_run : bool
        If True, download data but skip DB updates.

    Returns
    -------
    dict
        Summary with keys: season, updated, skipped, not_found, errors.
    """
    from src.scrapers.understat_scraper import UnderstatScraper

    result = {
        "season": season,
        "updated": 0,
        "skipped": 0,
        "not_found": 0,
        "errors": [],
    }

    # --- 1. Fetch shot-level xG for all matches in this season --------
    scraper = UnderstatScraper()
    season_start = time.time()

    try:
        df = scraper.fetch_shot_xg_for_season(
            league_config=league_config, season=season,
        )
        if df.empty:
            result["errors"].append(
                f"Season {season}: No shot xG data returned from Understat"
            )
            return result

        logger.info(
            "Season %s: Shot xG fetched for %d matches (%.1fs)",
            season, len(df), time.time() - season_start,
        )
    except Exception as exc:
        error_msg = f"Season {season}: Shot xG scrape failed — {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)
        return result

    if dry_run:
        logger.info(
            "Season %s: DRY RUN — %d matches with shot xG, skipping DB update",
            season, len(df),
        )
        return result

    # --- 2. Update MatchStat rows with set_piece_xg / open_play_xg ----
    try:
        shot_summary = load_understat_shot_xg(df, league_id)
        result["updated"] = shot_summary.get("updated", 0)
        result["skipped"] = shot_summary.get("skipped", 0)
        result["not_found"] = shot_summary.get("not_found", 0)
        logger.info(
            "Season %s: Shot xG — %d updated, %d skipped, %d not found",
            season,
            result["updated"],
            result["skipped"],
            result["not_found"],
        )
    except Exception as exc:
        error_msg = f"Season {season}: Shot xG loading failed — {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)

    return result


# ============================================================================
# E23-04: ClubElo Backfill
# ============================================================================

def backfill_clubelo(
    league_id: int,
    seasons: list,
    dry_run: bool = False,
) -> dict:
    """Backfill ClubElo ratings for all match dates in the given seasons.

    Queries the DB for all distinct match dates in the target seasons,
    then fetches Elo ratings for each date from the ClubElo API and
    loads them via ``load_clubelo_ratings()``.

    The ClubElo API is free, no auth required.  We use 1-2s delays
    between requests to be polite (inherited from BaseScraper rate limiter).

    Parameters
    ----------
    league_id : int
        Database ID for this league.
    seasons : list[str]
        List of season strings to backfill, e.g. ["2020-21", "2023-24"].
    dry_run : bool
        If True, show dates but skip API calls and DB inserts.

    Returns
    -------
    dict
        Summary with keys: dates_fetched, records_new, records_skipped,
        records_errors, errors.
    """
    from src.scrapers.clubelo_scraper import ClubEloScraper

    result = {
        "dates_fetched": 0,
        "records_new": 0,
        "records_skipped": 0,
        "records_errors": 0,
        "errors": [],
    }

    # --- 1. Get all distinct match dates for the target seasons -----------
    with get_session() as session:
        from src.database.models import Match
        dates_query = (
            session.query(Match.date)
            .filter(Match.season.in_(seasons))
            .filter(Match.date.isnot(None))
            .distinct()
            .order_by(Match.date)
        )
        match_dates = sorted([row[0] for row in dates_query.all()])

    if not match_dates:
        result["errors"].append("No match dates found for the given seasons")
        return result

    logger.info(
        "ClubElo backfill: %d unique match dates across seasons %s",
        len(match_dates), ", ".join(seasons),
    )

    if dry_run:
        logger.info("DRY RUN — first 5 dates: %s", match_dates[:5])
        logger.info("DRY RUN — last 5 dates: %s", match_dates[-5:])
        result["dates_fetched"] = len(match_dates)
        return result

    # --- 2. Fetch Elo ratings for all dates (with rate limiting) ----------
    scraper = ClubEloScraper()
    all_dfs = []

    for i, d in enumerate(match_dates):
        try:
            df = scraper.fetch_ratings_for_date(d)
            if not df.empty:
                all_dfs.append(df)
                result["dates_fetched"] += 1
        except Exception as exc:
            logger.warning("ClubElo: failed for date %s: %s", d, exc)

        # Progress log every 50 dates
        if (i + 1) % 50 == 0:
            logger.info(
                "ClubElo backfill progress: %d/%d dates fetched",
                i + 1, len(match_dates),
            )

    if not all_dfs:
        result["errors"].append("No Elo data returned from any date")
        return result

    # Combine all date DataFrames into one
    import pandas as pd
    combined_df = pd.concat(all_dfs, ignore_index=True)
    logger.info(
        "ClubElo backfill: %d total records fetched across %d dates",
        len(combined_df), result["dates_fetched"],
    )

    # --- 3. Load into DB --------------------------------------------------
    try:
        load_result = load_clubelo_ratings(combined_df, league_id)
        result["records_new"] = load_result.get("new", 0)
        result["records_skipped"] = load_result.get("skipped", 0)
        result["records_errors"] = load_result.get("errors", 0)
        logger.info(
            "ClubElo backfill loaded: %d new, %d skipped, %d errors",
            result["records_new"],
            result["records_skipped"],
            result["records_errors"],
        )
    except Exception as exc:
        error_msg = f"ClubElo loading failed: {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)

    return result


# ============================================================================
# Main Entry Point
# ============================================================================

def run_matches_backfill(args, league_cfg, league_id) -> list:
    """Run E23-01 match + odds backfill."""
    seasons = args.seasons or DEFAULT_MATCH_SEASONS
    print("=" * 70)
    print("E23-01 — Match + Odds Backfill")
    print("=" * 70)
    print(f"Seasons: {', '.join(seasons)}")
    print()

    scraper = FootballDataScraper()
    results = []

    for i, season in enumerate(seasons, 1):
        print(f"[{i}/{len(seasons)}] Backfilling matches: {season}...")
        season_result = backfill_season_matches(
            scraper=scraper,
            league_config=league_cfg,
            league_id=league_id,
            season=season,
            dry_run=args.dry_run,
        )
        results.append(season_result)
        print(
            f"  → Matches: {season_result['matches_new']} new, "
            f"{season_result['matches_skipped']} skipped"
        )
        print(
            f"  → Odds: {season_result['odds_new']} new, "
            f"{season_result['odds_skipped']} skipped"
        )
        if season_result["errors"]:
            for err in season_result["errors"]:
                print(f"  ⚠ {err}")
        print()

    # Summary
    total_matches = sum(r["matches_new"] for r in results)
    total_odds = sum(r["odds_new"] for r in results)
    total_errors = sum(len(r["errors"]) for r in results)

    print(f"Match backfill: {total_matches} matches, {total_odds} odds, "
          f"{total_errors} errors")
    return results


def run_understat_backfill(args, league_cfg, league_id) -> list:
    """Run E23-02 Understat xG backfill."""
    seasons = args.seasons or DEFAULT_UNDERSTAT_SEASONS
    print("=" * 70)
    print("E23-02 — Understat xG + Advanced Stats Backfill")
    print("=" * 70)
    print(f"Seasons: {', '.join(seasons)}")
    print()

    results = []

    for i, season in enumerate(seasons, 1):
        print(f"[{i}/{len(seasons)}] Backfilling Understat: {season}...")
        season_result = backfill_season_understat(
            league_config=league_cfg,
            league_id=league_id,
            season=season,
            dry_run=args.dry_run,
        )
        results.append(season_result)
        print(
            f"  → Stats: {season_result['stats_new']} new, "
            f"{season_result['stats_skipped']} skipped, "
            f"{season_result['stats_updated']} updated"
        )
        if season_result["stats_not_found"] > 0:
            print(f"  → Not found in DB: {season_result['stats_not_found']}")
        if season_result["errors"]:
            for err in season_result["errors"]:
                print(f"  ⚠ {err}")
        print()

    # Summary
    total_new = sum(r["stats_new"] for r in results)
    total_updated = sum(r["stats_updated"] for r in results)
    total_errors = sum(len(r["errors"]) for r in results)

    print(f"Understat backfill: {total_new} new stats, {total_updated} updated, "
          f"{total_errors} errors")
    return results


def run_shot_xg_backfill(args, league_cfg, league_id) -> list:
    """Run E23-03 shot-level xG breakdown backfill."""
    seasons = args.seasons or DEFAULT_SHOT_XG_SEASONS
    print("=" * 70)
    print("E23-03 — Shot-Level xG Breakdown Backfill")
    print("=" * 70)
    print(f"Seasons: {', '.join(seasons)}")
    print(f"⏱  This is the slowest step (~13 min/season, ~60 min total)")
    print()

    results = []

    for i, season in enumerate(seasons, 1):
        season_start = time.time()
        print(f"[{i}/{len(seasons)}] Backfilling shot xG: {season}...")
        season_result = backfill_season_shot_xg(
            league_config=league_cfg,
            league_id=league_id,
            season=season,
            dry_run=args.dry_run,
        )
        results.append(season_result)
        elapsed_s = time.time() - season_start
        print(
            f"  → Updated: {season_result['updated']}, "
            f"Skipped: {season_result['skipped']}, "
            f"Not found: {season_result['not_found']} "
            f"({elapsed_s:.0f}s)"
        )
        if season_result["errors"]:
            for err in season_result["errors"]:
                print(f"  ⚠ {err}")
        print()

    # Summary
    total_updated = sum(r["updated"] for r in results)
    total_errors = sum(len(r["errors"]) for r in results)

    print(f"Shot xG backfill: {total_updated} stats updated, "
          f"{total_errors} errors")
    return results


def run_clubelo_backfill(args, league_cfg, league_id) -> dict:
    """Run E23-04 ClubElo backfill."""
    seasons = args.seasons or DEFAULT_CLUBELO_SEASONS
    print("=" * 70)
    print("E23-04 — ClubElo Ratings Backfill")
    print("=" * 70)
    print(f"Seasons: {', '.join(seasons)}")
    print()

    start = time.time()
    result = backfill_clubelo(
        league_id=league_id,
        seasons=seasons,
        dry_run=args.dry_run,
    )
    elapsed = time.time() - start

    print(f"  → Dates fetched: {result['dates_fetched']}")
    print(f"  → Records new: {result['records_new']}")
    print(f"  → Records skipped: {result['records_skipped']}")
    print(f"  → Records errors: {result['records_errors']}")
    print(f"  → Elapsed: {elapsed:.0f}s")
    if result["errors"]:
        for err in result["errors"]:
            print(f"  ⚠ {err}")
    print()

    print(f"ClubElo backfill: {result['records_new']} new records, "
          f"{len(result['errors'])} errors")
    return result


# ============================================================================
# E23-05: Feature Recomputation
# ============================================================================

def backfill_features(
    league_id: int,
    season: str,
    dry_run: bool = False,
) -> dict:
    """Recompute all features for one season with force_recompute=True.

    This deletes existing Feature rows for the season first, then calls
    ``compute_all_features()`` to rebuild them from scratch.  This ensures
    all features reflect the now-complete data (xG, Elo, referee, etc.).

    Parameters
    ----------
    league_id : int
        Database ID for this league.
    season : str
        Season identifier, e.g. "2022-23".
    dry_run : bool
        If True, count existing features but skip recomputation.

    Returns
    -------
    dict
        Summary with keys: season, features_computed, features_total,
        completeness (dict of feature -> % non-null), errors.
    """
    from src.features.engineer import compute_all_features

    result = {
        "season": season,
        "features_computed": 0,
        "features_total": 0,
        "completeness": {},
        "errors": [],
    }

    # --- 1. Count existing features before deletion -----------------------
    with get_session() as session:
        from src.database.models import Feature, Match
        existing = (
            session.query(Feature)
            .join(Match, Feature.match_id == Match.id)
            .filter(
                Match.season == season,
                Match.league_id == league_id,
            )
            .count()
        )
    logger.info("Season %s: %d existing Feature rows", season, existing)

    if dry_run:
        logger.info("DRY RUN — would recompute features for %s", season)
        result["features_total"] = existing
        return result

    # --- 2. Delete existing features for fresh recomputation --------------
    # We delete rather than using force_recompute=True because the latter
    # updates in-place, which can leave stale columns from old computations.
    # A fresh insert ensures all features are computed from the latest data.
    # IMPORTANT: filter by league_id so we don't wipe other leagues' features
    # for the same season (Championship, La Liga, and EPL all share seasons
    # like "2024-25" but are independent leagues).
    if existing > 0:
        with get_session() as session:
            from src.database.models import Feature, Match
            # Get match IDs for THIS season AND THIS league only
            match_ids = [
                row[0] for row in
                session.query(Match.id).filter(
                    Match.season == season,
                    Match.league_id == league_id,
                ).all()
            ]
            if match_ids:
                deleted = session.query(Feature).filter(
                    Feature.match_id.in_(match_ids)
                ).delete(synchronize_session="fetch")
                logger.info(
                    "Season %s: deleted %d old Feature rows for fresh recompute",
                    season, deleted,
                )

    # --- 3. Recompute features for all matches in this season -------------
    try:
        season_start = time.time()
        df = compute_all_features(league_id, season, force_recompute=False)
        elapsed = time.time() - season_start

        result["features_computed"] = len(df) if df is not None and not df.empty else 0
        logger.info(
            "Season %s: %d feature rows computed in %.1fs",
            season, result["features_computed"], elapsed,
        )
    except Exception as exc:
        error_msg = f"Season {season}: Feature computation failed — {exc}"
        logger.error(error_msg)
        result["errors"].append(error_msg)
        return result

    # --- 4. Count final features and compute completeness -----------------
    with get_session() as session:
        from src.database.models import Feature, Match
        final_count = (
            session.query(Feature)
            .join(Match, Feature.match_id == Match.id)
            .filter(
                Match.season == season,
                Match.league_id == league_id,
            )
            .count()
        )
        result["features_total"] = final_count

        # Sample feature completeness: check key columns for non-null %
        # Query a sample of features to check completeness
        key_features = [
            "form_5", "xg_5", "npxg_5", "ppda_5", "deep_5",
            "set_piece_xg_5", "open_play_xg_5",
            "elo_rating", "elo_diff",
            "ref_avg_goals", "ref_home_win_pct",
            "days_since_last_match", "is_congested",
            "pinnacle_home_prob", "ah_line",
        ]
        features_all = (
            session.query(Feature)
            .join(Match, Feature.match_id == Match.id)
            .filter(
                Match.season == season,
                Match.league_id == league_id,
            )
            .all()
        )
        if features_all:
            for col_name in key_features:
                non_null = sum(
                    1 for f in features_all
                    if getattr(f, col_name, None) is not None
                )
                pct = (non_null / len(features_all)) * 100
                result["completeness"][col_name] = round(pct, 1)

    return result


def run_features_backfill(args, league_cfg, league_id) -> list:
    """Run E23-05 feature recomputation."""
    seasons = args.seasons or DEFAULT_FEATURE_SEASONS
    print("=" * 70)
    print("E23-05 — Recompute All Features")
    print("=" * 70)
    print(f"Seasons: {', '.join(seasons)}")
    print()

    results = []

    for i, season in enumerate(seasons, 1):
        season_start = time.time()
        print(f"[{i}/{len(seasons)}] Recomputing features: {season}...")
        season_result = backfill_features(
            league_id=league_id,
            season=season,
            dry_run=args.dry_run,
        )
        results.append(season_result)
        elapsed = time.time() - season_start

        print(f"  → Feature rows: {season_result['features_total']}")
        print(f"  → Elapsed: {elapsed:.0f}s")

        # Show completeness for key features
        if season_result["completeness"]:
            print("  → Completeness:")
            for feat, pct in sorted(season_result["completeness"].items()):
                indicator = "✅" if pct >= 80 else "⚠️" if pct >= 50 else "❌"
                print(f"      {indicator} {feat}: {pct}%")

        if season_result["errors"]:
            for err in season_result["errors"]:
                print(f"  ⚠ {err}")
        print()

    # Summary
    total_features = sum(r["features_total"] for r in results)
    total_errors = sum(len(r["errors"]) for r in results)

    print(f"Feature recomputation: {total_features} total feature rows, "
          f"{total_errors} errors")
    return results


def main() -> None:
    """Main entry point for the historical backfill script."""
    parser = argparse.ArgumentParser(
        description="BetVector Historical Data Backfill (E23-01 through E23-05)",
    )
    parser.add_argument(
        "command",
        choices=["matches", "understat", "shot-xg", "clubelo", "features", "all"],
        help=(
            "What to backfill: "
            "'matches' = E23-01 (match results + odds from Football-Data.co.uk), "
            "'understat' = E23-02 (xG + NPxG + PPDA from Understat), "
            "'shot-xg' = E23-03 (set-piece vs open-play xG breakdown), "
            "'clubelo' = E23-04 (ClubElo ratings for match dates), "
            "'features' = E23-05 (recompute all features for all seasons), "
            "'all' = all five in sequence"
        ),
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=None,
        help=(
            "Override seasons to backfill. "
            "Default for matches/clubelo: 2020-21 through 2023-24. "
            "Default for understat/shot-xg: 2020-21 through 2024-25. "
            "Default for features: all 6 seasons (2020-21 through 2025-26). "
            "Format: YYYY-YY (e.g. 2022-23)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download data and show parsed output without writing to DB.",
    )
    parser.add_argument(
        "--league",
        default=None,
        help=(
            "Short name of the league to backfill (e.g. 'EPL', 'Championship'). "
            "Default: first active league in config/leagues.yaml. "
            "Added in E36-01 to support multi-league backfills."
        ),
    )
    args = parser.parse_args()

    print("=" * 70)
    print("BetVector — Historical Data Backfill")
    print("=" * 70)
    print(f"Command: {args.command}")
    print(f"Dry run: {args.dry_run}")
    print()

    # --- Load config and resolve league -----------------------------------
    config = BetVectorConfig()
    active_leagues = config.get_active_leagues()
    if not active_leagues:
        print("ERROR: No active leagues in config/leagues.yaml")
        sys.exit(1)

    # E36-01: Support explicit --league selection for multi-league backfills.
    # Without --league, defaults to the first active league (EPL) for
    # backward compatibility with the original E23 backfill usage.
    if args.league:
        league_cfg = next(
            (lc for lc in active_leagues if lc.short_name == args.league),
            None,
        )
        if league_cfg is None:
            active_names = [lc.short_name for lc in active_leagues]
            print(
                f"ERROR: League '{args.league}' not found or not active. "
                f"Active leagues: {', '.join(active_names)}"
            )
            sys.exit(1)
    else:
        league_cfg = active_leagues[0]

    league_name = league_cfg.short_name
    league_id = _get_league_id(league_name)
    print(f"League: {league_cfg.name} (ID={league_id})")
    print()

    # --- Run requested backfill(s) ----------------------------------------
    start_time = time.time()
    all_results = []
    has_errors = False

    if args.command in ("matches", "all"):
        match_results = run_matches_backfill(args, league_cfg, league_id)
        all_results.extend(match_results)
        if any(r["errors"] for r in match_results):
            has_errors = True
        print()

    if args.command in ("understat", "all"):
        understat_results = run_understat_backfill(args, league_cfg, league_id)
        all_results.extend(understat_results)
        if any(r["errors"] for r in understat_results):
            has_errors = True
        print()

    if args.command in ("shot-xg", "all"):
        shot_xg_results = run_shot_xg_backfill(args, league_cfg, league_id)
        all_results.extend(shot_xg_results)
        if any(r["errors"] for r in shot_xg_results):
            has_errors = True
        print()

    if args.command in ("clubelo", "all"):
        clubelo_result = run_clubelo_backfill(args, league_cfg, league_id)
        if clubelo_result["errors"]:
            has_errors = True
        print()

    if args.command in ("features", "all"):
        feature_results = run_features_backfill(args, league_cfg, league_id)
        all_results.extend(feature_results)
        if any(r["errors"] for r in feature_results):
            has_errors = True
        print()

    elapsed = time.time() - start_time

    # --- Final summary ----------------------------------------------------
    print("=" * 70)
    print(f"COMPLETE — Elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print("=" * 70)

    if has_errors:
        print("\n⚠️  Some seasons had errors — check the log output above.")
        sys.exit(1)
    else:
        print("\n✅ All backfill operations completed successfully.")


if __name__ == "__main__":
    main()
