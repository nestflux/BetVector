"""
BetVector — Pipeline Orchestrator (E8-01)
==========================================
Chains all modules together for the three daily runs plus backtesting.

Three Daily Runs
----------------
BetVector operates on a three-run-per-day schedule (times are in UTC):

1. **Morning (06:00)** — Full pipeline:
   scrape data → load into DB → compute features → run predictions →
   find value bets → log system picks.
   This is the "what should we bet on today?" run.

2. **Midday (13:00)** — Odds update:
   Re-fetch odds → recalculate edges → update value_bets table.
   Odds move throughout the day as money comes in.  This run captures
   those movements and updates our edge calculations accordingly.

3. **Evening (22:00)** — Results:
   Scrape results → resolve pending bets → calculate P&L → update
   bankroll → generate performance metrics.
   This is the "how did we do today?" run.

Pipeline Resilience
-------------------
Each run is wrapped in step-level try/except handling.  If one step fails
(e.g., FBref returns 403, or odds scraping times out), the error is logged
and subsequent steps still attempt to run.  A single scraper failure should
never prevent predictions from being made with available data.

Each run creates a ``pipeline_runs`` record in the database with:
- run_type (morning/midday/evening/manual/backtest)
- status (running → completed or failed)
- counts (matches_scraped, predictions_made, value_bets_found)
- duration_seconds
- error_message (if any step failed)

Master Plan refs: MP §5 Architecture → Scheduling, MP §7 Pipeline Orchestrator
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from src.config import config
from src.database.db import get_session, init_db
from src.database.models import (
    Feature, League, Match, MatchStat, PipelineRun, Prediction, Weather,
)
from sqlalchemy import func as sa_func
from src.database.seed import seed_all

logger = logging.getLogger(__name__)

# Path for persisting The Odds API budget between pipeline runs.
# The morning pipeline saves the remaining request count from API response
# headers, and the midday pipeline reads it to decide whether to skip
# The Odds API and use odds-api.io instead (budget-aware fallback).
import json
import os

_BUDGET_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "logs", "odds_api_budget.json",
)


def _persist_budget(remaining: int) -> None:
    """Save The Odds API remaining request count to a JSON file.

    Called after each Odds API request in both morning and midday pipelines.
    The midday pipeline reads this to decide if it should skip The Odds API
    and use odds-api.io instead (see skip_midday_below in settings.yaml).
    """
    try:
        os.makedirs(os.path.dirname(_BUDGET_FILE), exist_ok=True)
        with open(_BUDGET_FILE, "w") as f:
            json.dump({
                "remaining": remaining,
                "updated_at": datetime.utcnow().isoformat(),
            }, f)
    except OSError as e:
        logger.warning("[pipeline] Could not persist budget: %s", e)


def _read_persisted_budget() -> Optional[int]:
    """Read The Odds API remaining request count from the persisted file.

    Returns None if the file doesn't exist or can't be read (e.g., first
    run ever, or file was deleted).  Caller should treat None as "unknown"
    and proceed with the API call.
    """
    try:
        with open(_BUDGET_FILE, "r") as f:
            data = json.load(f)
        return int(data.get("remaining", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


# ============================================================================
# Pipeline Result Dataclass
# ============================================================================

@dataclass
class PipelineResult:
    """Summary of a pipeline run.

    Returned by each run_* method so the caller (CLI, scheduler, tests)
    can inspect what happened without querying the database.
    """
    run_type: str
    status: str = "completed"           # completed | failed
    matches_scraped: int = 0
    predictions_made: int = 0
    value_bets_found: int = 0
    emails_sent: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    pipeline_run_id: Optional[int] = None


# ============================================================================
# Pipeline Orchestrator
# ============================================================================

class Pipeline:
    """Orchestrates the BetVector daily pipeline.

    Chains scrapers, loaders, feature engineers, models, value finders,
    and bet trackers together in the correct order for each run type.

    Smart Resume (PC-09)
    --------------------
    When the morning pipeline is restarted (e.g. after a GitHub Actions
    timeout), it checks which leagues were already fully processed today
    and skips them.  A league is "fully processed" if it has predictions
    created today for upcoming matches — this means scraping, loading,
    features, AND predictions all completed successfully.

    Additionally, the Understat scraper is skipped when all finished
    matches in the current season already have xG stats in the database.

    Usage::

        pipeline = Pipeline()
        result = pipeline.run_morning()
        print(f"Found {result.value_bets_found} value bets")
    """

    # -------------------------------------------------------------------
    # Smart Resume: League Checkpoint Methods
    # -------------------------------------------------------------------

    @staticmethod
    def _league_processed_today(league_id: int) -> bool:
        """Check if this league was already fully processed today.

        A league is considered "processed today" if EITHER:
        1. There are predictions created today for that league's matches
           (the primary signal — means scrape + load + features + predict
           all completed successfully), OR
        2. There are features created today AND no upcoming scheduled
           matches (off-season or mid-week gap — no predictions needed
           but scrape + features still ran).

        This enables smart resume: if the pipeline timed out after
        processing 3 of 6 leagues, the next run skips the 3 done leagues
        and picks up from league 4.
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        try:
            with get_session() as session:
                # Primary check: predictions created today
                pred_count = (
                    session.query(sa_func.count(Prediction.id))
                    .join(Match, Prediction.match_id == Match.id)
                    .filter(
                        Match.league_id == league_id,
                        Prediction.created_at.like(f"{today}%"),
                    )
                    .scalar()
                ) or 0

                if pred_count > 0:
                    return True

                # Fallback: if no upcoming matches exist for this league
                # but features were updated today, the league was processed.
                # This handles off-season / mid-week gaps where there are
                # no scheduled matches to predict.
                scheduled_count = (
                    session.query(sa_func.count(Match.id))
                    .filter(
                        Match.league_id == league_id,
                        Match.status == "scheduled",
                    )
                    .scalar()
                ) or 0

                if scheduled_count == 0:
                    # No upcoming matches — check if features were computed today.
                    # Feature model uses computed_at (not created_at).
                    feature_today = (
                        session.query(sa_func.count(Feature.id))
                        .join(Match, Feature.match_id == Match.id)
                        .filter(
                            Match.league_id == league_id,
                            Feature.computed_at.like(f"{today}%"),
                        )
                        .scalar()
                    ) or 0
                    return feature_today > 0

                return False
        except Exception as e:
            logger.warning(
                "Could not check league checkpoint (league_id=%d): %s",
                league_id, e,
            )
            return False  # If check fails, process the league to be safe

    @staticmethod
    def _understat_already_current(league_id: int, season: str) -> bool:
        """Check if Understat stats are up-to-date for this league-season.

        Compares the number of finished matches to the number of matches
        with MatchStat rows.  If every finished match already has stats,
        we can skip the Understat API calls entirely.

        This is the biggest single optimization: Understat's ``scrape()``
        makes 2 API calls per league-season, and the loader iterates
        through every match to check for duplicates.  Skipping this
        when data is already current saves both HTTP time and DB I/O.
        """
        try:
            with get_session() as session:
                finished_count = (
                    session.query(sa_func.count(Match.id))
                    .filter(
                        Match.league_id == league_id,
                        Match.season == season,
                        Match.status == "finished",
                    )
                    .scalar()
                ) or 0

                if finished_count == 0:
                    return False  # No finished matches → nothing to skip

                # Count distinct matches that have at least one MatchStat row
                matches_with_stats = (
                    session.query(
                        sa_func.count(sa_func.distinct(MatchStat.match_id))
                    )
                    .join(Match, MatchStat.match_id == Match.id)
                    .filter(
                        Match.league_id == league_id,
                        Match.season == season,
                    )
                    .scalar()
                ) or 0

                return matches_with_stats >= finished_count
        except Exception as e:
            logger.warning(
                "Could not check Understat freshness (league_id=%d): %s",
                league_id, e,
            )
            return False  # If check fails, fetch to be safe

    @staticmethod
    def _features_already_current(league_id: int, season: str) -> bool:
        """Check if features are up-to-date for this league-season.

        Compares the number of finished matches to the number of matches
        with Feature rows (each match should have 2 feature rows: home
        and away).  If all finished matches have features, we can skip
        the feature computation step entirely.
        """
        try:
            with get_session() as session:
                finished_count = (
                    session.query(sa_func.count(Match.id))
                    .filter(
                        Match.league_id == league_id,
                        Match.season == season,
                        Match.status == "finished",
                    )
                    .scalar()
                ) or 0

                if finished_count == 0:
                    return False

                # Feature rows: 2 per match (home + away)
                feature_count = (
                    session.query(sa_func.count(Feature.id))
                    .join(Match, Feature.match_id == Match.id)
                    .filter(
                        Match.league_id == league_id,
                        Match.season == season,
                    )
                    .scalar()
                ) or 0

                # Each match should have 2 feature rows
                expected = finished_count * 2
                return feature_count >= expected
        except Exception as e:
            logger.warning(
                "Could not check feature freshness (league_id=%d): %s",
                league_id, e,
            )
            return False

    def run_morning(self) -> PipelineResult:
        """Full morning pipeline: scrape → load → features → predict → value → log → email.

        This is the primary daily run that:
        1. Downloads latest match data and odds from all sources
        2. Loads scraped data into the database
        3. Computes features for all matches
        4. Generates model predictions for upcoming matches
        5. Compares predictions to bookmaker odds to find value bets
        6. Auto-logs value bets as system picks for tracking
        7. Sends morning picks emails to all users with notifications enabled

        Returns
        -------
        PipelineResult
            Summary of the run including counts and any errors.
        """
        start_time = time.time()
        result = PipelineResult(run_type="morning")
        run_id = self._create_pipeline_run("morning")
        result.pipeline_run_id = run_id

        errors: List[str] = []
        total_matches_scraped = 0
        total_predictions = 0
        total_value_bets = 0

        leagues = config.get_active_leagues()
        if not leagues:
            errors.append("No active leagues configured")
            self._complete_run(run_id, "failed", errors=errors,
                               duration=time.time() - start_time)
            result.status = "failed"
            result.errors = errors
            result.duration_seconds = time.time() - start_time
            return result

        for league_cfg in leagues:
            league_name = league_cfg.short_name
            league_id = self._get_league_id(league_cfg.short_name)
            if league_id is None:
                errors.append(f"League {league_name} not found in database")
                continue

            # Get the current season (last in the list)
            current_season = league_cfg.seasons[-1] if league_cfg.seasons else None
            if current_season is None:
                errors.append(f"No seasons configured for {league_name}")
                continue

            # --- Smart Resume (PC-09): Skip leagues already processed today ---
            # If this league was fully processed today (predictions exist),
            # skip it entirely.  This enables the pipeline to resume from
            # where it left off after a timeout/restart.
            if self._league_processed_today(league_id):
                print(
                    f"\n{'='*60}\n"
                    f"⏭  {league_name}: Already processed today — SKIPPING\n"
                    f"{'='*60}"
                )
                continue

            # --- Step 1: Scrape data ---
            print(f"[Step 1/7] Scraping data for {league_name} {current_season}...")
            matches_scraped = 0

            # 1a. Football-Data.co.uk (match results + odds)
            try:
                from src.scrapers.football_data import FootballDataScraper
                scraper = FootballDataScraper()
                fd_df = scraper.scrape(league_config=league_cfg, season=current_season)
                if not fd_df.empty:
                    print(f"  → Football-Data: {len(fd_df)} matches downloaded")
                else:
                    print("  → Football-Data: No data returned")
            except Exception as e:
                err = f"Football-Data scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Football-Data: FAILED ({e})")
                fd_df = None

            # 1a-ii. Football-Data.org API (near-real-time fixtures + results)
            # Fills the freshness gap between Football-Data.co.uk CSV updates.
            # The CSV only refreshes ~2x/week, but this API has results within
            # minutes of final whistle.  Uses 1 API call per league-season.
            fd_org_df = None
            try:
                from src.scrapers.football_data_org import FootballDataOrgScraper
                fd_org_scraper = FootballDataOrgScraper()
                fd_org_df = fd_org_scraper.scrape(
                    league_config=league_cfg, season=current_season,
                )
                if fd_org_df is not None and not fd_org_df.empty:
                    finished = fd_org_df[fd_org_df["status"] == "finished"]
                    scheduled = fd_org_df[fd_org_df["status"] == "scheduled"]
                    print(f"  → Football-Data.org API: {len(finished)} results, "
                          f"{len(scheduled)} scheduled")
                else:
                    print("  → Football-Data.org API: No data returned")
            except Exception as e:
                err = f"Football-Data.org API scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Football-Data.org API: FAILED ({e})")

            # 1b. FBref (advanced stats — xG, possession, etc.)
            try:
                from src.scrapers.fbref_scraper import FBrefScraper
                fbref_scraper = FBrefScraper()
                fbref_df = fbref_scraper.scrape(
                    league_config=league_cfg, season=current_season,
                )
                if not fbref_df.empty:
                    print(f"  → FBref: {len(fbref_df)} stat rows downloaded")
                else:
                    print("  → FBref: No data returned (may be blocked)")
            except Exception as e:
                err = f"FBref scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → FBref: FAILED ({e})")
                fbref_df = None

            # 1c. API-Football (real-time fixtures + odds + injuries)
            # Solves the Football-Data.co.uk CSV delay problem — gives us
            # fixtures and results within minutes of events happening.
            api_football_df = None
            api_football_odds = None
            api_football_injuries = None
            try:
                from src.scrapers.api_football import APIFootballScraper
                api_scraper = APIFootballScraper()

                # Fixtures/results (1 request)
                api_football_df = api_scraper.scrape(
                    league_config=league_cfg, season=current_season,
                )
                if api_football_df is not None and not api_football_df.empty:
                    print(f"  → API-Football: {len(api_football_df)} fixtures downloaded")
                else:
                    print("  → API-Football: No fixture data returned")

                # Odds (~5 requests for paginated results)
                api_football_odds = api_scraper.scrape_odds(
                    league_config=league_cfg, season=current_season,
                )
                if api_football_odds:
                    print(f"  → API-Football odds: {len(api_football_odds)} records")
                else:
                    print("  → API-Football odds: No data returned")

                # Injuries (1 request)
                api_football_injuries = api_scraper.scrape_injuries(
                    league_config=league_cfg, season=current_season,
                )
                if api_football_injuries is not None and not api_football_injuries.empty:
                    # PC-14-03: Store injuries in DB (previously printed and discarded)
                    from src.scrapers.loader import load_injuries
                    inj_result = load_injuries(api_football_injuries, league_id)
                    print(
                        f"  → API-Football injuries: {len(api_football_injuries)} records "
                        f"({inj_result['new']} new, {inj_result['skipped']} skipped)"
                    )
                else:
                    print("  → API-Football injuries: No data returned")

            except Exception as e:
                err = f"API-Football scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → API-Football: FAILED ({e})")

            # 1c-ii. Soccerdata — live sidelined/injured player data (E39-03)
            # Primary injury source — replaces API-Football (free tier blocks
            # current-season injury data).  Uses 1 request per league from
            # the 75/day free tier budget.  Impact ratings are auto-computed
            # from PlayerValue percentiles loaded in E39-01.
            soccerdata_injuries_df = None
            try:
                from src.scrapers.soccerdata import SoccerdataScraper
                from src.scrapers.loader import load_soccerdata_injuries

                sd_scraper = SoccerdataScraper()
                soccerdata_injuries_df = sd_scraper.scrape_injuries(
                    league_config=league_cfg, season=current_season,
                )
                if (soccerdata_injuries_df is not None
                        and not soccerdata_injuries_df.empty):
                    sd_inj_result = load_soccerdata_injuries(
                        soccerdata_injuries_df, league_id,
                    )
                    print(
                        f"  → Soccerdata injuries: "
                        f"{len(soccerdata_injuries_df)} sidelined "
                        f"({sd_inj_result['new']} new, "
                        f"{sd_inj_result['updated']} updated)"
                    )
                else:
                    print("  → Soccerdata injuries: No data "
                          "(no matches today or API unavailable)")

            except Exception as e:
                err = f"Soccerdata injury scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Soccerdata injuries: FAILED ({e})")

            # 1d. Understat (xG data — replaces blocked FBref)
            # Smart skip (PC-09): if all finished matches already have
            # MatchStat rows, skip the Understat API calls entirely.
            # This saves ~6 seconds per league (2 API calls × 3s rate limit).
            understat_df = None
            if self._understat_already_current(league_id, current_season):
                print("  → Understat: All matches have stats — SKIPPED")
            else:
                try:
                    from src.scrapers.understat_scraper import UnderstatScraper
                    us_scraper = UnderstatScraper()
                    understat_df = us_scraper.scrape(
                        league_config=league_cfg, season=current_season,
                    )
                    if understat_df is not None and not understat_df.empty:
                        finished = understat_df[understat_df["home_xg"].notna()]
                        print(f"  → Understat: {len(finished)} matches with xG data")
                    else:
                        print("  → Understat: No data returned")
                except Exception as e:
                    err = f"Understat scrape failed for {league_name}: {e}"
                    logger.error(err)
                    errors.append(err)
                    print(f"  → Understat: FAILED ({e})")

            # 1e-pre. Odds sources — dual source with automatic fallback
            # Primary: The Odds API (the-odds-api.com) — 500 req/month free tier
            # Fallback: odds-api.io — 100 req/hour free tier (no monthly cap)
            # If primary returns empty (budget exhausted), fallback activates.
            the_odds_api_df = None
            odds_source_used = None
            try:
                from src.scrapers.odds_api import TheOddsAPIScraper
                odds_api_scraper = TheOddsAPIScraper()
                the_odds_api_df = odds_api_scraper.scrape(
                    league_config=league_cfg, season=current_season,
                )
                # Persist budget remaining for midday budget-aware skip.
                # Response headers populate _requests_remaining after the call.
                if odds_api_scraper._requests_remaining is not None:
                    _persist_budget(odds_api_scraper._requests_remaining)
                if the_odds_api_df is not None and not the_odds_api_df.empty:
                    odds_source_used = "The Odds API"
                    print(
                        f"  → The Odds API: {len(the_odds_api_df)} odds records "
                        f"from {the_odds_api_df['bookmaker'].nunique()} bookmakers"
                    )
                else:
                    print("  → The Odds API: No odds data (budget may be exhausted)")
            except Exception as e:
                err = f"The Odds API scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → The Odds API: FAILED ({e})")

            # Fallback to odds-api.io if The Odds API returned nothing
            if the_odds_api_df is None or the_odds_api_df.empty:
                try:
                    from src.scrapers.odds_api_io import OddsApiIoScraper
                    fallback_scraper = OddsApiIoScraper()
                    the_odds_api_df = fallback_scraper.scrape(
                        league_config=league_cfg, season=current_season,
                    )
                    if the_odds_api_df is not None and not the_odds_api_df.empty:
                        odds_source_used = "odds-api.io"
                        print(
                            f"  → odds-api.io (fallback): {len(the_odds_api_df)} odds records "
                            f"from {the_odds_api_df['bookmaker'].nunique()} bookmakers"
                        )
                    else:
                        print("  → odds-api.io (fallback): No odds data returned")
                except Exception as e:
                    err = f"odds-api.io fallback failed for {league_name}: {e}"
                    logger.error(err)
                    errors.append(err)
                    print(f"  → odds-api.io (fallback): FAILED ({e})")

            if odds_source_used:
                logger.info(
                    "[pipeline] Odds source for %s: %s",
                    league_name, odds_source_used,
                )

            # 1f. ClubElo ratings (daily Elo ratings for all clubs)
            # Elo captures long-term team quality beyond rolling form.
            # Free API, no auth — one request returns all clubs' ratings.
            clubelo_df = None
            try:
                from src.scrapers.clubelo_scraper import ClubEloScraper
                elo_scraper = ClubEloScraper()
                clubelo_df = elo_scraper.scrape()
                if clubelo_df is not None and not clubelo_df.empty:
                    print(f"  → ClubElo: {len(clubelo_df)} team ratings fetched")
                else:
                    print("  → ClubElo: No ratings returned")
            except Exception as e:
                err = f"ClubElo scrape failed: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → ClubElo: FAILED ({e})")

            # --- Step 2: Load into database ---
            print(f"[Step 2/7] Loading data into database...")
            try:
                from src.scrapers.loader import (
                    load_matches, load_odds, load_match_stats,
                    load_odds_api_football, load_odds_the_odds_api,
                    load_understat_stats,
                    update_match_results, update_team_api_names,
                )

                # Football-Data.co.uk matches + odds
                if fd_df is not None and not fd_df.empty:
                    match_result = load_matches(fd_df, league_id, current_season)
                    matches_scraped = match_result.get("new", 0)
                    print(f"  → Matches (Football-Data): {match_result}")

                    odds_result = load_odds(fd_df, league_id)
                    print(f"  → Odds (Football-Data): {odds_result}")

                # Football-Data.org API fixtures + results
                # Insert new scheduled fixtures and update with fresh results
                if fd_org_df is not None and not fd_org_df.empty:
                    fd_org_match_result = load_matches(
                        fd_org_df, league_id, current_season,
                    )
                    matches_scraped += fd_org_match_result.get("new", 0)
                    print(f"  → Matches (Football-Data.org): {fd_org_match_result}")

                    # Update scheduled matches that now have results
                    fd_org_update_result = update_match_results(
                        fd_org_df, league_id,
                    )
                    print(f"  → Results update (Football-Data.org): {fd_org_update_result}")

                # API-Football fixtures + results + odds
                if api_football_df is not None and not api_football_df.empty:
                    # Insert new matches (scheduled + finished)
                    af_match_result = load_matches(
                        api_football_df, league_id, current_season,
                    )
                    matches_scraped += af_match_result.get("new", 0)
                    print(f"  → Matches (API-Football): {af_match_result}")

                    # Update scheduled → finished for matches with results
                    af_update_result = update_match_results(
                        api_football_df, league_id,
                    )
                    print(f"  → Results updated: {af_update_result}")

                    # Update team API-Football IDs and names
                    update_team_api_names(api_football_df, league_id)

                if api_football_odds:
                    af_odds_result = load_odds_api_football(
                        api_football_odds, league_id,
                    )
                    print(f"  → Odds (API-Football): {af_odds_result}")

                # The Odds API — live pre-match odds (50+ bookmakers)
                if the_odds_api_df is not None and not the_odds_api_df.empty:
                    oa_odds_result = load_odds_the_odds_api(
                        the_odds_api_df, league_id,
                    )
                    print(f"  → Odds (The Odds API): {oa_odds_result}")

                # FBref match stats
                if fbref_df is not None and not fbref_df.empty:
                    stats_result = load_match_stats(fbref_df, league_id)
                    print(f"  → Match stats (FBref): {stats_result}")

                # Understat xG stats (fills gaps where FBref is blocked)
                if understat_df is not None and not understat_df.empty:
                    us_result = load_understat_stats(understat_df, league_id)
                    print(f"  → xG stats (Understat): {us_result}")

                # ClubElo ratings (long-term team quality via Elo system)
                if clubelo_df is not None and not clubelo_df.empty:
                    from src.scrapers.loader import load_clubelo_ratings
                    elo_result = load_clubelo_ratings(clubelo_df, league_id)
                    print(f"  → ClubElo ratings: {elo_result}")

            except Exception as e:
                err = f"Data loading failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Loading: FAILED ({e})")

            total_matches_scraped += matches_scraped

            # 1e. Weather (match-day conditions from Open-Meteo)
            # Fetched after loading so we can look up match_ids in the DB
            try:
                from src.scrapers.weather_scraper import WeatherScraper
                from src.scrapers.loader import load_weather
                from src.database.models import Match as _Match, Team as _Team

                weather_scraper = WeatherScraper()

                # Get matches that need weather data (finished matches
                # without weather + upcoming scheduled matches)
                with get_session() as session:
                    matches_needing_weather = session.query(_Match).filter(
                        _Match.league_id == league_id,
                        _Match.season == current_season,
                    ).outerjoin(
                        Weather, Weather.match_id == _Match.id,
                    ).filter(
                        Weather.id.is_(None),
                    ).order_by(_Match.date.desc()).limit(50).all()

                    match_list = []
                    for m in matches_needing_weather:
                        home_team = session.query(_Team).filter_by(
                            id=m.home_team_id,
                        ).first()
                        if home_team:
                            match_list.append({
                                "match_id": m.id,
                                "date": m.date,
                                "home_team": home_team.name,
                            })

                if match_list:
                    weather_df = weather_scraper.scrape_for_matches(
                        match_list, league_short_name=league_name,
                    )
                    if not weather_df.empty:
                        weather_result = load_weather(weather_df)
                        print(f"  → Weather: {weather_result}")
                    else:
                        print("  → Weather: No data returned")
                else:
                    print("  → Weather: All matches already have weather data")

            except Exception as e:
                err = f"Weather scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Weather: FAILED ({e})")

            # --- Step 3: Compute features ---
            print(f"[Step 3/7] Computing features for {league_name}...")
            try:
                from src.features.engineer import compute_all_features
                features_df = compute_all_features(league_id, current_season)
                print(f"  → {len(features_df)} match feature sets computed")
            except Exception as e:
                err = f"Feature computation failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Features: FAILED ({e})")
                continue  # Can't predict without features

            # --- Step 4: Generate predictions ---
            print(f"[Step 4/7] Generating predictions...")
            try:
                predictions = self._generate_predictions(
                    league_id, current_season, features_df,
                    league_short_name=league_name,
                )
                total_predictions += len(predictions)
                print(f"  → {len(predictions)} predictions generated")
            except Exception as e:
                err = f"Prediction failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Predictions: FAILED ({e})")
                continue  # Can't find value bets without predictions

            # --- Step 5: Find value bets ---
            print(f"[Step 5/7] Finding value bets...")
            try:
                from src.betting.value_finder import (
                    ValueFinder, clear_value_bets_for_scheduled,
                )
                finder = ValueFinder()

                # PC-09-03: Clear stale value bets for scheduled matches
                # before recalculating.  This prevents duplicate accumulation
                # across pipeline runs (the VB unique constraint includes
                # detected_at, so each run would create new rows otherwise).
                cleared = clear_value_bets_for_scheduled()
                if cleared:
                    print(f"  → Cleared {cleared} stale value bets")

                # Per-league edge threshold (PC-24-01): Each league has its own
                # optimal threshold based on market efficiency and backtest sweep.
                # Falls back to the global default if no league override is set.
                global_threshold = config.settings.value_betting.edge_threshold
                edge_threshold = getattr(
                    league_cfg, "edge_threshold_override", None,
                ) or global_threshold

                # PC-25-01: Per-league strategy profile.  Each league can have
                # its own sharp_only setting (e.g., LaLiga/Ligue1 use Pinnacle-
                # only filtering for +21-22pp ROI improvement).  Reads from the
                # league's strategy block in leagues.yaml with safe fallback.
                strategy = getattr(league_cfg, "strategy", None)
                sharp_only = (
                    getattr(strategy, "sharp_only", False)
                    if strategy else False
                )
                sharp_bookmaker = config.settings.value_betting.sharp_bookmaker

                all_value_bets = []
                for pred in predictions:
                    vbs = finder.find_value_bets(
                        match_id=pred.match_id,
                        edge_threshold=edge_threshold,
                        model_name=pred.model_name,
                        sharp_only=sharp_only,
                        sharp_bookmaker=sharp_bookmaker,
                    )
                    all_value_bets.extend(vbs)

                if all_value_bets:
                    save_result = finder.save_value_bets(all_value_bets)
                    total_value_bets += save_result.get("new", 0)
                    sharp_str = " (Pinnacle-only)" if sharp_only else ""
                    print(f"  → {len(all_value_bets)} value bets found{sharp_str}, "
                          f"{save_result.get('new', 0)} new")
                else:
                    print("  → No value bets found above threshold")

            except Exception as e:
                err = f"Value bet detection failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Value bets: FAILED ({e})")
                all_value_bets = []

            # --- Step 6: Log system picks ---
            print(f"[Step 6/7] Logging system picks...")
            try:
                if all_value_bets:
                    from src.betting.tracker import log_system_picks
                    user_id = self._get_default_user_id()
                    if user_id:
                        pick_result = log_system_picks(all_value_bets, user_id)
                        print(f"  → System picks: {pick_result}")
                    else:
                        print("  → No default user found, skipping system pick logging")
                else:
                    print("  → No value bets to log")
            except Exception as e:
                err = f"System pick logging failed: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → System picks: FAILED ({e})")

        # --- Step 7: Send morning picks emails ---
        emails_sent = self._send_emails("morning", run_id, errors)
        result.emails_sent = emails_sent

        # --- Finalize ---
        duration = time.time() - start_time
        # Pipeline is "completed" unless there were critical errors that
        # prevented any processing.  Zero new matches/predictions is normal
        # when data is already up-to-date (all duplicates skipped).
        has_critical_errors = any(
            "Scraping failed" in e and "Loading failed" in e
            for e in errors
        )
        status = "failed" if has_critical_errors else "completed"

        self._complete_run(
            run_id, status,
            matches_scraped=total_matches_scraped,
            predictions_made=total_predictions,
            value_bets_found=total_value_bets,
            emails_sent=emails_sent,
            duration=duration,
            errors=errors,
        )

        result.status = status
        result.matches_scraped = total_matches_scraped
        result.predictions_made = total_predictions
        result.value_bets_found = total_value_bets
        result.duration_seconds = round(duration, 2)
        result.errors = errors

        print(f"\nMorning pipeline complete in {duration:.1f}s")
        print(f"  Matches scraped: {total_matches_scraped}")
        print(f"  Predictions: {total_predictions}")
        print(f"  Value bets: {total_value_bets}")
        print(f"  Emails sent: {emails_sent}")
        if errors:
            print(f"  Warnings/errors: {len(errors)}")
            for err in errors:
                print(f"    - {err}")

        return result

    def run_midday(self) -> PipelineResult:
        """Midday odds update: re-fetch odds → recalculate edges.

        Bookmaker odds shift throughout the day as money comes in.  This run
        re-downloads the latest odds and recalculates which bets still have
        positive expected value.

        Does NOT re-scrape match results or re-train the model — only odds
        are refreshed and edges recalculated.

        Returns
        -------
        PipelineResult
            Summary of the run.
        """
        start_time = time.time()
        result = PipelineResult(run_type="midday")
        run_id = self._create_pipeline_run("midday")
        result.pipeline_run_id = run_id

        errors: List[str] = []
        total_value_bets = 0

        leagues = config.get_active_leagues()

        for league_cfg in leagues:
            league_name = league_cfg.short_name
            league_id = self._get_league_id(league_cfg.short_name)
            if league_id is None:
                errors.append(f"League {league_name} not found in database")
                continue

            current_season = league_cfg.seasons[-1] if league_cfg.seasons else None
            if current_season is None:
                continue

            # --- Step 1: Re-fetch odds ---
            print(f"[Step 1/3] Re-fetching odds for {league_name}...")

            # 1a. Football-Data.co.uk odds
            try:
                from src.scrapers.football_data import FootballDataScraper
                from src.scrapers.loader import load_odds

                scraper = FootballDataScraper()
                fd_df = scraper.scrape(league_config=league_cfg, season=current_season)
                if not fd_df.empty:
                    odds_result = load_odds(fd_df, league_id)
                    print(f"  → Odds (Football-Data): {odds_result}")
                else:
                    print("  → Football-Data: No odds data returned")
            except Exception as e:
                err = f"Football-Data odds re-fetch failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Football-Data odds: FAILED ({e})")

            # 1b. API-Football targeted odds refresh (upcoming fixtures only)
            # More precise than Football-Data — fetches odds for specific
            # upcoming matches that we have predictions for.
            try:
                from src.scrapers.api_football import APIFootballScraper
                from src.scrapers.loader import load_odds_api_football

                api_scraper = APIFootballScraper()
                api_odds = api_scraper.scrape_odds(
                    league_config=league_cfg, season=current_season,
                )
                if api_odds:
                    af_odds_result = load_odds_api_football(api_odds, league_id)
                    print(f"  → Odds (API-Football): {af_odds_result}")
                else:
                    print("  → API-Football: No odds data returned")
            except Exception as e:
                err = f"API-Football odds refresh failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → API-Football odds: FAILED ({e})")

            # 1c. Odds refresh — dual source with budget-aware fallback
            # PC-15-03: At midday, check The Odds API budget. If below
            # skip_midday_below threshold, skip it entirely and go straight
            # to odds-api.io (which has no monthly cap). This preserves
            # The Odds API budget for morning calls which are higher priority.
            oa_df = None
            midday_odds_source = None
            skip_midday_threshold = 200
            try:
                skip_midday_threshold = int(getattr(
                    getattr(config.settings.scraping, "the_odds_api", None),
                    "skip_midday_below", 200,
                ))
            except (AttributeError, TypeError, ValueError):
                pass

            # Check if The Odds API has enough budget for midday calls.
            # Budget is persisted to a JSON file by the morning pipeline after
            # each Odds API call.  A fresh TheOddsAPIScraper() instance has
            # _requests_remaining=None (only populated from response headers),
            # so we read the persisted budget instead of creating a new instance.
            midday_skip_primary = False
            try:
                from src.scrapers.odds_api import TheOddsAPIScraper
                from src.scrapers.loader import load_odds_the_odds_api

                # Read persisted budget from morning pipeline run
                persisted_remaining = _read_persisted_budget()
                if (persisted_remaining is not None
                        and persisted_remaining < skip_midday_threshold):
                    midday_skip_primary = True
                    print(
                        f"  → The Odds API: Skipping midday (budget {persisted_remaining} "
                        f"< threshold {skip_midday_threshold}) — using odds-api.io instead"
                    )
                    logger.info(
                        "[pipeline] Skipping midday Odds API for %s (budget %d < %d)",
                        league_name, persisted_remaining,
                        skip_midday_threshold,
                    )
                else:
                    odds_api_scraper = TheOddsAPIScraper()
                    oa_df = odds_api_scraper.scrape(
                        league_config=league_cfg, season=current_season,
                    )
                    # Persist updated budget after the call
                    if odds_api_scraper._requests_remaining is not None:
                        _persist_budget(odds_api_scraper._requests_remaining)
                    if oa_df is not None and not oa_df.empty:
                        midday_odds_source = "The Odds API"
                        oa_result = load_odds_the_odds_api(oa_df, league_id)
                        print(f"  → Odds (The Odds API): {oa_result}")
                    else:
                        print("  → The Odds API: No odds data (budget may be exhausted)")
            except Exception as e:
                err = f"The Odds API refresh failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → The Odds API odds: FAILED ({e})")

            # Fallback to odds-api.io if The Odds API was skipped or returned nothing
            if midday_skip_primary or oa_df is None or oa_df.empty:
                try:
                    from src.scrapers.odds_api_io import OddsApiIoScraper
                    from src.scrapers.loader import load_odds_the_odds_api

                    fallback_scraper = OddsApiIoScraper()
                    oa_df = fallback_scraper.scrape(
                        league_config=league_cfg, season=current_season,
                    )
                    if oa_df is not None and not oa_df.empty:
                        midday_odds_source = "odds-api.io"
                        oa_result = load_odds_the_odds_api(oa_df, league_id)
                        print(f"  → odds-api.io (fallback): {oa_result}")
                    else:
                        print("  → odds-api.io (fallback): No odds data returned")
                except Exception as e:
                    err = f"odds-api.io midday fallback failed for {league_name}: {e}"
                    logger.error(err)
                    errors.append(err)
                    print(f"  → odds-api.io (fallback): FAILED ({e})")

            if midday_odds_source:
                logger.info(
                    "[pipeline] Midday odds source for %s: %s",
                    league_name, midday_odds_source,
                )

            # --- Step 2: Recalculate edges ---
            print(f"[Step 2/3] Recalculating value bets for {league_name}...")
            try:
                from src.betting.value_finder import (
                    ValueFinder, clear_value_bets_for_scheduled,
                )
                from src.models.storage import get_latest_predictions

                finder = ValueFinder()

                # PC-09-03: Clear stale value bets for scheduled matches
                # before recalculating with latest odds.  Prevents duplicate
                # accumulation across pipeline runs.
                cleared = clear_value_bets_for_scheduled()
                if cleared:
                    print(f"  → Cleared {cleared} stale value bets")

                # Per-league edge threshold (PC-24-01): Each league has its own
                # optimal threshold based on market efficiency and backtest sweep.
                global_threshold = config.settings.value_betting.edge_threshold
                edge_threshold = getattr(
                    league_cfg, "edge_threshold_override", None,
                ) or global_threshold

                # PC-25-01: Per-league sharp-only filtering from strategy profile.
                strategy = getattr(league_cfg, "strategy", None)
                sharp_only = (
                    getattr(strategy, "sharp_only", False)
                    if strategy else False
                )
                sharp_bookmaker = config.settings.value_betting.sharp_bookmaker

                # Get existing predictions for upcoming matches
                predictions = get_latest_predictions(league_id=league_id)
                all_value_bets = []

                for pred in predictions:
                    vbs = finder.find_value_bets(
                        match_id=pred.match_id,
                        edge_threshold=edge_threshold,
                        model_name=pred.model_name,
                        sharp_only=sharp_only,
                        sharp_bookmaker=sharp_bookmaker,
                    )
                    all_value_bets.extend(vbs)

                if all_value_bets:
                    save_result = finder.save_value_bets(all_value_bets)
                    total_value_bets += save_result.get("new", 0)
                    sharp_str = " (Pinnacle-only)" if sharp_only else ""
                    print(f"  → {len(all_value_bets)} value bets{sharp_str}, "
                          f"{save_result.get('new', 0)} new")
                else:
                    print("  → No value bets above threshold")

            except Exception as e:
                err = f"Edge recalculation failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Recalculation: FAILED ({e})")

            # --- Step 3: Update system picks ---
            print(f"[Step 3/3] Updating system picks...")
            try:
                if all_value_bets:
                    from src.betting.tracker import log_system_picks
                    user_id = self._get_default_user_id()
                    if user_id:
                        pick_result = log_system_picks(all_value_bets, user_id)
                        print(f"  → System picks: {pick_result}")
                else:
                    print("  → No new picks to log")
            except Exception as e:
                err = f"System pick logging failed: {e}"
                logger.error(err)
                errors.append(err)

        duration = time.time() - start_time
        status = "completed"

        self._complete_run(
            run_id, status,
            value_bets_found=total_value_bets,
            duration=duration,
            errors=errors,
        )

        result.status = status
        result.value_bets_found = total_value_bets
        result.duration_seconds = round(duration, 2)
        result.errors = errors

        print(f"\nMidday pipeline complete in {duration:.1f}s")
        print(f"  Value bets found: {total_value_bets}")
        if errors:
            print(f"  Warnings/errors: {len(errors)}")

        return result

    def run_evening(self) -> PipelineResult:
        """Evening results pipeline: resolve bets → P&L → metrics → recalibrate.

        After the day's matches are finished:
        1. Scrape latest results to update match scores
        2. Resolve pending bets (determine won/lost, calculate P&L)
        3. Generate updated performance metrics
        4. Check automatic recalibration (MP §11.1)

        Returns
        -------
        PipelineResult
            Summary of the run.
        """
        start_time = time.time()
        result = PipelineResult(run_type="evening")
        run_id = self._create_pipeline_run("evening")
        result.pipeline_run_id = run_id

        errors: List[str] = []
        total_matches_scraped = 0

        leagues = config.get_active_leagues()

        for league_cfg in leagues:
            league_name = league_cfg.short_name
            league_id = self._get_league_id(league_cfg.short_name)
            if league_id is None:
                errors.append(f"League {league_name} not found in database")
                continue

            current_season = league_cfg.seasons[-1] if league_cfg.seasons else None
            if current_season is None:
                continue

            # --- Step 1: Scrape latest results ---
            print(f"[Step 1/3] Scraping results for {league_name}...")

            # 1a. API-Football results (fastest — available within minutes)
            try:
                from src.scrapers.api_football import APIFootballScraper
                from src.scrapers.loader import (
                    load_matches as _load_matches,
                    update_match_results as _update_results,
                )

                api_scraper = APIFootballScraper()
                api_df = api_scraper.scrape(
                    league_config=league_cfg, season=current_season,
                )
                if api_df is not None and not api_df.empty:
                    # Insert any new matches
                    af_result = _load_matches(api_df, league_id, current_season)
                    total_matches_scraped += af_result.get("new", 0)
                    print(f"  → API-Football matches: {af_result}")

                    # Update scheduled → finished
                    af_update = _update_results(api_df, league_id)
                    print(f"  → API-Football results: {af_update}")
                else:
                    print("  → API-Football: No data returned")
            except Exception as e:
                err = f"API-Football results failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → API-Football: FAILED ({e})")

            # 1a-ii. Football-Data.org API results (near-real-time, fills CSV gap)
            try:
                from src.scrapers.football_data_org import FootballDataOrgScraper
                from src.scrapers.loader import (
                    load_matches as _load_matches_org,
                    update_match_results as _update_results_org,
                )

                fd_org_scraper = FootballDataOrgScraper()
                fd_org_df = fd_org_scraper.scrape(
                    league_config=league_cfg, season=current_season,
                )
                if fd_org_df is not None and not fd_org_df.empty:
                    fd_org_result = _load_matches_org(
                        fd_org_df, league_id, current_season,
                    )
                    total_matches_scraped += fd_org_result.get("new", 0)
                    print(f"  → Football-Data.org matches: {fd_org_result}")

                    fd_org_update = _update_results_org(fd_org_df, league_id)
                    print(f"  → Football-Data.org results: {fd_org_update}")
                else:
                    print("  → Football-Data.org API: No data returned")
            except Exception as e:
                err = f"Football-Data.org results failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Football-Data.org API: FAILED ({e})")

            # 1b. Football-Data.co.uk results (may have newer data too)
            try:
                from src.scrapers.football_data import FootballDataScraper
                from src.scrapers.loader import load_matches, load_odds

                scraper = FootballDataScraper()
                fd_df = scraper.scrape(league_config=league_cfg, season=current_season)
                if not fd_df.empty:
                    match_result = load_matches(fd_df, league_id, current_season)
                    total_matches_scraped += match_result.get("new", 0)
                    print(f"  → Football-Data matches: {match_result}")

                    odds_result = load_odds(fd_df, league_id)
                    print(f"  → Football-Data odds: {odds_result}")
                else:
                    print("  → Football-Data: No data returned")
            except Exception as e:
                err = f"Football-Data results failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Football-Data: FAILED ({e})")

            # 1c. Understat xG for today's finished matches
            try:
                from src.scrapers.understat_scraper import UnderstatScraper
                from src.scrapers.loader import load_understat_stats

                us_scraper = UnderstatScraper()
                us_df = us_scraper.scrape(
                    league_config=league_cfg, season=current_season,
                )
                if us_df is not None and not us_df.empty:
                    us_result = load_understat_stats(us_df, league_id)
                    print(f"  → Understat xG: {us_result}")
                else:
                    print("  → Understat: No data returned")
            except Exception as e:
                err = f"Understat scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Understat: FAILED ({e})")

            # 1d. Soccerdata lineups — post-match starting XI + bench (E39-08)
            # Fetches actual lineups for today's finished matches.
            # Formation data is stored on the Match record, player entries
            # in match_lineups.  Feeds squad rotation (E39-09), formation
            # change (E39-10), and bench strength (E39-11) features.
            try:
                from src.scrapers.soccerdata import SoccerdataScraper
                from src.scrapers.loader import load_match_lineups

                sd_scraper = SoccerdataScraper()
                sd_lineups_df = sd_scraper.scrape_lineups(
                    league_config=league_cfg,
                    match_date=datetime.now().strftime("%Y-%m-%d"),
                )
                if (sd_lineups_df is not None
                        and not sd_lineups_df.empty):
                    lu_result = load_match_lineups(
                        sd_lineups_df, league_id,
                    )
                    print(
                        f"  → Soccerdata lineups: "
                        f"{lu_result['new']} new players, "
                        f"{lu_result['matches_updated']} matches updated"
                    )
                else:
                    print("  → Soccerdata lineups: No data "
                          "(no matches today or API unavailable)")
            except Exception as e:
                err = f"Soccerdata lineup scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Soccerdata lineups: FAILED ({e})")

            # --- Step 2: Resolve pending bets ---
            print(f"[Step 2/3] Resolving pending bets...")
            try:
                from src.betting.tracker import resolve_bets
                # Get all finished matches that might have pending bets
                resolved_matches = self._get_recently_finished_matches(league_id)
                total_resolved = 0
                total_won = 0
                total_lost = 0

                for match_id in resolved_matches:
                    res = resolve_bets(match_id)
                    total_resolved += res.get("resolved", 0)
                    total_won += res.get("won", 0)
                    total_lost += res.get("lost", 0)

                print(f"  → Resolved {total_resolved} bets "
                      f"({total_won} won, {total_lost} lost)")
            except Exception as e:
                err = f"Bet resolution failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Resolution: FAILED ({e})")

            # --- Step 3: Update performance metrics ---
            print(f"[Step 3/3] Updating performance metrics...")
            try:
                from src.evaluation.metrics import generate_performance_report
                today = datetime.now().strftime("%Y-%m-%d")
                # Generate a daily performance report for the active model
                active_models = config.settings.models.active_models
                for model_name in active_models:
                    report = generate_performance_report(
                        model_name=model_name,
                        period_type="daily",
                        period_start=today,
                        period_end=today,
                    )
                    if report:
                        print(f"  → {model_name}: ROI={report.get('roi', 'N/A')}%, "
                              f"Brier={report.get('brier_score', 'N/A')}")
                    else:
                        print(f"  → {model_name}: No data for today")
            except Exception as e:
                err = f"Metrics update failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Metrics: FAILED ({e})")

        # --- CLV Backfill (E19-04) ---
        # Now that all leagues have had their closing odds loaded (step 1b)
        # and bets resolved (step 2), backfill CLV on any BetLog entries
        # that are settled but still missing closing_odds.
        #
        # CLV = (1/closing_odds) - (1/placement_odds)
        # This is the single best predictor of long-term profitability (MP §12).
        # The Model Health dashboard CLV section auto-populates once data exists.
        print(f"\n[CLV] Backfilling closing odds and CLV...")
        try:
            from src.scrapers.loader import backfill_closing_odds

            clv_result = backfill_closing_odds()
            clv_updated = clv_result.get("updated", 0)
            clv_missing = clv_result.get("no_closing_odds", 0)
            clv_total = clv_result.get("total_checked", 0)

            if clv_total > 0:
                print(f"  → CLV backfilled: {clv_updated}/{clv_total} entries updated "
                      f"({clv_missing} missing closing odds)")
            else:
                print("  → CLV: No entries need backfilling")
        except Exception as e:
            err = f"CLV backfill failed: {e}"
            logger.error(err)
            errors.append(err)
            print(f"  → CLV: FAILED ({e})")

        # --- Step 4: Automatic recalibration check (MP §11.1) ---
        # After resolving bets, check if any model's probabilities have
        # drifted and need recalibration.  Also checks whether an existing
        # calibration should be rolled back if it's making things worse.
        print(f"\n[Recalibration] Checking automatic recalibration...")
        try:
            from src.self_improvement.calibration import (
                check_and_recalibrate,
                check_rollback,
            )
            active_models = config.settings.models.active_models
            for model_name in active_models:
                print(f"  Model: {model_name}")

                # First check if an existing calibration should be rolled back
                rolled_back = check_rollback(model_name)
                if rolled_back:
                    print(f"  → Rolled back calibration for {model_name}")

                # Then check if a new recalibration is needed
                cal = check_and_recalibrate(model_name)
                if cal:
                    print(f"  → New {cal.calibration_method} calibration applied "
                          f"(MAE {cal.mean_abs_error_before:.4f} → "
                          f"{cal.mean_abs_error_after:.4f})")
                else:
                    print(f"  → No recalibration needed for {model_name}")
        except Exception as e:
            err = f"Recalibration check failed: {e}"
            logger.error(err)
            errors.append(err)
            print(f"  → Recalibration: FAILED ({e})")

        # --- Step 5: Retrain trigger check (MP §11.5) ---
        # Check if any model's rolling Brier score has degraded enough
        # to trigger an automatic retrain.  Also checks whether a recent
        # retrain should be rolled back if the new model is worse.
        print(f"\n[Retrain] Checking re-training triggers...")
        try:
            from src.self_improvement.retrain_trigger import (
                check_retrain_needed,
                check_post_retrain_rollback,
            )
            active_models = config.settings.models.active_models
            for model_name in active_models:
                print(f"  Model: {model_name}")

                # First check if a recent retrain should be rolled back
                rolled_back = check_post_retrain_rollback(model_name)
                if rolled_back:
                    print(f"  → Rolled back retrain for {model_name}")

                # Then check if a new retrain is needed
                retrain = check_retrain_needed(model_name)
                if retrain:
                    print(f"  → Retrain triggered for {model_name} "
                          f"(Brier before: {retrain.brier_before:.4f})")
                else:
                    print(f"  → No retrain needed for {model_name}")
        except Exception as e:
            err = f"Retrain trigger check failed: {e}"
            logger.error(err)
            errors.append(err)
            print(f"  → Retrain check: FAILED ({e})")

        # --- Send evening review emails ---
        emails_sent = self._send_emails("evening", run_id, errors)

        # --- Weekly tasks (Sundays only) ---
        if datetime.utcnow().weekday() == 6:  # 6 = Sunday

            # --- Weekly: Market Performance & Strategy Review (PC-25-11) ---
            # Recomputes league × market tiers using all resolved bets,
            # detects tier transitions from the previous period, and
            # generates strategy suggestions.  These are stored for the
            # weekly summary email — NEVER auto-applied.
            print("\n  Weekly: Market performance & strategy review")
            try:
                from src.self_improvement.market_feedback import (
                    update_market_performance,
                    detect_tier_transitions,
                    generate_strategy_suggestions,
                )

                # 1. Recompute all league × market tiers
                mp_records = update_market_performance()
                print(f"    → {len(mp_records)} league×market combos assessed")

                # 2. Detect tier transitions (compares to previous period)
                transitions = detect_tier_transitions()
                if transitions:
                    for t in transitions:
                        print(f"    → TIER CHANGE: {t['league']} {t['detail']}")
                else:
                    print("    → No tier transitions detected")

                # 3. Generate strategy suggestions (never auto-applied)
                suggestions = generate_strategy_suggestions(transitions)
                if suggestions:
                    for s in suggestions:
                        print(f"    → SUGGESTION: {s['suggestion']}")
                else:
                    print("    → No strategy suggestions")

                # Store transitions + suggestions for weekly email pickup
                self._weekly_tier_transitions = transitions
                self._weekly_strategy_suggestions = suggestions

            except Exception as e:
                err = f"Weekly strategy review failed: {e}"
                logger.error(err)
                errors.append(err)
                print(f"    → FAILED ({e})")

            # --- Weekly: Refresh Transfermarkt squad market values ---
            # Market values change slowly (weekly updates from Transfermarkt).
            # Running on Sunday evening aligns with the self-improvement cycle.
            # Market value ratio is a strong predictor — richer squads generally
            # outperform poorer ones (long-term squad quality signal).
            print("\n  Weekly: Transfermarkt market value refresh")
            try:
                from src.scrapers.transfermarkt import TransfermarktScraper
                from src.scrapers.loader import load_market_values

                tm_scraper = TransfermarktScraper()
                for lg in leagues:
                    lg_id = self._get_league_id(lg.short_name)
                    lg_season = lg.seasons[-1] if lg.seasons else None
                    if lg_id is None or lg_season is None:
                        continue

                    tm_df = tm_scraper.scrape(
                        league_config=lg,
                        season=lg_season,
                    )
                    if tm_df is not None and not tm_df.empty:
                        mv_result = load_market_values(tm_df, lg_id)
                        print(f"    → {lg.short_name} market values: "
                              f"{mv_result['new']} new, "
                              f"{mv_result['skipped']} skipped, "
                              f"{mv_result['not_found']} not found")
                    else:
                        print(f"    → {lg.short_name}: no data returned")

                    # E39-03: Also refresh player-level values (for injury
                    # impact_rating auto-computation and bench_strength feature)
                    try:
                        from src.scrapers.loader import load_player_values
                        pv_df = tm_scraper.scrape_players(
                            league_config=lg, season=lg_season,
                        )
                        if pv_df is not None and not pv_df.empty:
                            pv_result = load_player_values(pv_df, lg_id)
                            print(f"    → {lg.short_name} player values: "
                                  f"{pv_result['new']} new, "
                                  f"{pv_result['skipped']} skipped")
                        else:
                            print(f"    → {lg.short_name} player values: "
                                  f"no data returned")
                    except Exception as pv_e:
                        logger.warning(
                            "Player value refresh failed for %s: %s",
                            lg.short_name, pv_e,
                        )
                        print(f"    → {lg.short_name} player values: "
                              f"FAILED ({pv_e})")

            except Exception as e:
                err = f"Transfermarkt market value refresh failed: {e}"
                logger.error(err)
                errors.append(err)
                print(f"    → Transfermarkt: FAILED ({e})")

            # --- Weekly: Send weekly summary email ---
            weekly_sent = self._send_emails("weekly", run_id, errors)
            emails_sent += weekly_sent

        result.emails_sent = emails_sent

        # --- E40-09: Weekly TM datasets refresh (Sunday evening) ---
        # Downloads the latest transfermarkt-datasets ZIP (updated every
        # Monday), maps new games, and loads lineups/formations/managers.
        # Config-driven: check transfermarkt_datasets.refresh_enabled and
        # refresh_day in settings.yaml.
        try:
            from datetime import datetime as _dt

            # Read config with safe defaults if section not yet added
            tm_ds = getattr(
                getattr(config.settings, "scraping", None),
                "transfermarkt_datasets", None,
            )
            tm_enabled = getattr(tm_ds, "refresh_enabled", True) if tm_ds else True
            tm_day = getattr(tm_ds, "refresh_day", 6) if tm_ds else 6
            today_weekday = _dt.today().weekday()

            if tm_enabled and today_weekday == tm_day:
                print(f"\n[TM Refresh] Running weekly Transfermarkt datasets refresh...")
                from src.scrapers.transfermarkt import refresh_transfermarkt_datasets
                with get_session() as tm_session:
                    tm_stats = refresh_transfermarkt_datasets(tm_session)
                print(
                    f"  → TM weekly refresh: downloaded={tm_stats['downloaded']}, "
                    f"new_mappings={tm_stats['new_mappings']}, "
                    f"lineups={tm_stats['lineups']}, "
                    f"formations={tm_stats['formations']}, "
                    f"managers={tm_stats['managers']}"
                )
            elif tm_enabled:
                logger.debug(
                    "TM refresh skipped: today is weekday %d, refresh_day=%d",
                    today_weekday, tm_day,
                )
        except Exception as e:
            err = f"TM datasets refresh failed: {e}"
            logger.error(err)
            errors.append(err)
            print(f"  → TM refresh: FAILED ({e})")

        duration = time.time() - start_time
        status = "completed"

        self._complete_run(
            run_id, status,
            matches_scraped=total_matches_scraped,
            emails_sent=emails_sent,
            duration=duration,
            errors=errors,
        )

        result.status = status
        result.matches_scraped = total_matches_scraped
        result.duration_seconds = round(duration, 2)
        result.errors = errors

        print(f"\nEvening pipeline complete in {duration:.1f}s")
        print(f"  Matches updated: {total_matches_scraped}")
        print(f"  Emails sent: {emails_sent}")
        if errors:
            print(f"  Warnings/errors: {len(errors)}")

        return result

    def run_train(self, model_key: str = "xgboost_v1") -> PipelineResult:
        """Train a model on the combined multi-league dataset and save to disk.

        E37-01: XGBoost on Multi-League Dataset
        ----------------------------------------
        Loads Feature rows and Match results from ALL active leagues, combines
        them into a single training DataFrame (~9,000+ matches across EPL,
        Championship, La Liga), trains the model, and saves to
        ``data/models/{model_key}.pkl``.

        Why multi-league training?
          - EPL alone provides ~1,900 training matches → XGBoost overfits (E25-03)
          - Three leagues combined → ~9,000+ matches → enough for reliable splits
          - Cross-league patterns (home advantage, promotion effects) generalise
            better when the model has seen multiple league contexts

        Parameters
        ----------
        model_key : str
            Config key for the model to train.  Supported: "xgboost_v1".
            Defaults to "xgboost_v1" (the only non-Poisson model currently active).

        Returns
        -------
        PipelineResult
            Contains training sample count in predictions_made field.
        """
        import os
        import time as time_mod

        import pandas as pd

        from src.config import config as cfg
        from src.database.db import get_session
        from src.database.models import Match
        from src.features.engineer import compute_all_features

        t0 = time_mod.time()
        errors: List[str] = []

        logger.info("run_train: training model '%s' on multi-league dataset", model_key)

        # --- Instantiate model ---
        model = self._create_model(model_key)
        if model is None:
            msg = f"Unknown model key: {model_key!r}. Supported: xgboost_v1"
            logger.error(msg)
            return PipelineResult(run_type="train", status="failed", errors=[msg])

        # --- Load features + results from ALL active leagues ---
        all_feature_dfs: List[pd.DataFrame] = []
        all_results_rows: List[dict] = []

        active_leagues = cfg.get_active_leagues()
        for league_cfg in active_leagues:
            league_id = self._get_league_id(league_cfg.short_name)
            if league_id is None:
                logger.warning("League not found in DB: %s", league_cfg.short_name)
                continue

            # Load all historical seasons for this league.
            # Tag each row with league short name so we can apply
            # per-league training_weight later (PC-26-06).
            for season in getattr(league_cfg, "seasons", []):
                try:
                    feat_df = compute_all_features(league_id, season)
                    if feat_df.empty:
                        continue
                    feat_df["_league"] = league_cfg.short_name
                    all_feature_dfs.append(feat_df)
                    logger.debug(
                        "Loaded %d feature rows for %s %s",
                        len(feat_df), league_cfg.short_name, season,
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not load features for %s %s: %s",
                        league_cfg.short_name, season, exc,
                    )

            # Load match results for this league
            try:
                with get_session() as session:
                    finished = (
                        session.query(Match)
                        .filter(
                            Match.league_id == league_id,
                            Match.status == "finished",
                        )
                        .all()
                    )
                    for m in finished:
                        if m.home_goals is not None and m.away_goals is not None:
                            all_results_rows.append({
                                "match_id": m.id,
                                "home_goals": m.home_goals,
                                "away_goals": m.away_goals,
                            })
            except Exception as exc:
                msg = f"Could not load results for {league_cfg.short_name}: {exc}"
                logger.error(msg)
                errors.append(msg)

        if not all_feature_dfs:
            msg = "No feature rows found across any active league — cannot train"
            logger.error(msg)
            return PipelineResult(run_type="train", status="failed", errors=[msg])

        combined_features = pd.concat(all_feature_dfs, ignore_index=True)
        results_df = pd.DataFrame(all_results_rows)

        logger.info(
            "run_train: combined %d feature rows, %d result rows across %d leagues",
            len(combined_features), len(results_df), len(active_leagues),
        )

        # --- Build per-league sample weights (PC-26-06) ---
        # Each league's model_params.training_weight controls how much
        # emphasis its data gets during XGBoost training.  Championship
        # gets 2.0× (market inefficiency → richer signal), La Liga 1.5×
        # (sharp-only filtering shrinks sample), others 1.0× (standard).
        # The _league column was added during feature loading above.
        league_weight_map: Dict[str, float] = {}
        for league_cfg in active_leagues:
            tw = 1.0
            mp = getattr(league_cfg, "model_params", None)
            if mp is not None:
                tw = float(getattr(mp, "training_weight", 1.0))
            league_weight_map[league_cfg.short_name] = tw

        sample_weight = None
        if "_league" in combined_features.columns:
            sample_weight = combined_features["_league"].map(league_weight_map).fillna(1.0)
            non_default = {k: v for k, v in league_weight_map.items() if v != 1.0}
            if non_default:
                logger.info(
                    "Per-league training weights: %s (others 1.0×)",
                    ", ".join(f"{k}={v}×" for k, v in non_default.items()),
                )

        # --- Train the model ---
        try:
            model.train(combined_features, results_df, sample_weight=sample_weight)
        except ValueError as exc:
            msg = f"Training failed: {exc}"
            logger.error(msg)
            return PipelineResult(run_type="train", status="failed", errors=[msg])
        except Exception as exc:
            msg = f"Unexpected training error: {exc}"
            logger.error(msg)
            errors.append(msg)
            return PipelineResult(run_type="train", status="failed", errors=errors)

        # --- Save to disk ---
        model_dir = "data/models"
        os.makedirs(model_dir, exist_ok=True)
        model_path = f"{model_dir}/{model_key}.pkl"

        try:
            from pathlib import Path
            model.save(Path(model_path))
            logger.info("Saved trained model to %s", model_path)
        except Exception as exc:
            msg = f"Could not save model to {model_path}: {exc}"
            logger.error(msg)
            errors.append(msg)

        duration = time_mod.time() - t0
        n_train = len(combined_features[
            combined_features["match_id"].isin(results_df["match_id"])
        ]) if not results_df.empty else 0

        print(f"\nTrain pipeline complete in {duration:.1f}s")
        print(f"  Model: {model_key}")
        print(f"  Training matches: {n_train}")
        print(f"  Saved to: {model_path}")
        if errors:
            print(f"  Errors: {len(errors)}")

        status = "failed" if errors else "completed"
        return PipelineResult(
            run_type="train",
            status=status,
            predictions_made=n_train,
            errors=errors,
        )

    def run_backtest(
        self,
        league: str = "EPL",
        season: str = "2024-25",
        training_seasons: Optional[List[str]] = None,
        model_name: str = "poisson",
    ) -> PipelineResult:
        """Run a walk-forward backtest via the backtester module.

        Delegates to ``src.evaluation.backtester.run_backtest()`` and wraps
        the result in a PipelineResult for consistent tracking.

        Multi-Season Training (E23-06)
        ------------------------------
        When ``training_seasons`` is provided, all specified seasons' features
        are loaded for training.  This allows the model to train on 5+ seasons
        of historical data instead of just the target season, dramatically
        improving calibration and early-season prediction accuracy.

        If not provided, the method automatically discovers all seasons from
        ``config/leagues.yaml`` that are before or equal to the target season.

        Model Selection (E37-02)
        ------------------------
        ``model_name`` selects which prediction model is used for each
        walk-forward iteration:
          - ``"poisson"`` (default) — Poisson GLM (production model, E20)
          - ``"xgboost"`` — XGBoost regressors trained on multi-league data (E37)

        XGBoost requires ≥ 500 training samples (from ``config.yaml``).
        With multi-season pre-loading, this is satisfied from day 1 of 2024-25
        since 2020-21 through 2023-24 (~1,520+ matches) are always available.

        Parameters
        ----------
        league : str
            Short name of the league (e.g. "EPL").
        season : str
            Season identifier to evaluate (e.g. "2024-25").
        training_seasons : list[str] or None
            Seasons to include in training.  If None, auto-discovers from
            league config — all seasons up to and including ``season``.
        model_name : str
            Model key to use: "poisson" or "xgboost" (default: "poisson").

        Returns
        -------
        PipelineResult
            Summary including the BacktestResult attached via errors list
            (for simplicity — the full result is printed to console).
        """
        start_time = time.time()
        result = PipelineResult(run_type="backtest")
        run_id = self._create_pipeline_run("backtest")
        result.pipeline_run_id = run_id

        errors: List[str] = []

        league_id = self._get_league_id(league)
        if league_id is None:
            err = f"League '{league}' not found in database"
            errors.append(err)
            self._complete_run(run_id, "failed", errors=errors,
                               duration=time.time() - start_time)
            result.status = "failed"
            result.errors = errors
            return result

        # Auto-discover training seasons from config if not provided.
        # Include all seasons up to and including the target season so
        # the model benefits from maximum historical training data.
        if training_seasons is None:
            training_seasons = self._get_training_seasons(league, season)

        # Map the short model key ("poisson" / "xgboost") to the versioned
        # DB key ("poisson_v1" / "xgboost_v1") used in model_performance.
        _model_key_map = {
            "poisson": "poisson_v1",
            "xgboost": "xgboost_v1",
        }
        _model_version_key = _model_key_map.get(model_name, "poisson_v1")

        print(f"Running walk-forward backtest: {league} {season} [{_model_version_key}]")
        print(f"  Training on {len(training_seasons)} season(s)")
        try:
            from src.evaluation.backtester import (
                run_backtest as bt_run,
                save_backtest_to_model_performance,
            )
            from src.evaluation.reporter import (
                print_backtest_report,
                save_backtest_report,
                plot_backtest_results,
            )
            from src.models.poisson import PoissonModel

            # Select model class based on model_name (E37-02).
            # Poisson is the default; XGBoost is used for comparison backtests.
            if model_name == "xgboost":
                from src.models.xgboost_model import XGBoostModel
                model_class = XGBoostModel
            else:
                model_class = PoissonModel

            # Read staking config
            bankroll_cfg = config.settings.bankroll
            # Per-league edge threshold (PC-24-01): Each league has its own
            # optimal threshold based on market efficiency and backtest sweep.
            global_threshold = config.settings.value_betting.edge_threshold
            bt_league_cfg = next(
                (lg for lg in config.leagues if lg.short_name == league), None,
            )
            edge_threshold = (
                getattr(bt_league_cfg, "edge_threshold_override", None) or global_threshold
                if bt_league_cfg else global_threshold
            )

            # PC-25-01: Per-league sharp-only filtering from strategy profile.
            # When enabled, backtester only compares model against Pinnacle odds.
            bt_strategy = (
                getattr(bt_league_cfg, "strategy", None)
                if bt_league_cfg else None
            )
            bt_sharp_only = (
                getattr(bt_strategy, "sharp_only", False)
                if bt_strategy else False
            )
            bt_sharp_bookmaker = config.settings.value_betting.sharp_bookmaker

            # For XGBoost, train on ALL active leagues to mirror production.
            # EPL's local SQLite only has 2024-25 data; Championship and La
            # Liga provide 2,000+ pre-season matches that are temporally safe.
            # Temporal integrity is enforced inside bt_run via
            # _get_match_ids_before_date_multi(all_league_ids, matchday_date).
            training_league_ids = None
            if model_name == "xgboost":
                training_league_ids = self._get_all_active_league_ids()

            bt_result = bt_run(
                league_id=league_id,
                season=season,
                model_class=model_class,
                edge_threshold=edge_threshold,
                staking_method=bankroll_cfg.staking_method,
                stake_percentage=bankroll_cfg.stake_percentage,
                starting_bankroll=bankroll_cfg.starting_amount,
                training_seasons=training_seasons,
                training_league_ids=training_league_ids,
                sharp_only=bt_sharp_only,
                sharp_bookmaker=bt_sharp_bookmaker,
            )

            # Print and save the report.
            # Include the model name in the filename so XGBoost and Poisson
            # reports can coexist in data/predictions/ without overwriting.
            _safe_league = league.replace(" ", "_").replace("/", "_")
            _model_suffix = (
                f"xgb" if model_name == "xgboost" else "poisson"
            )
            _report_path = (
                f"data/predictions/backtest_report_{_model_suffix}_{_safe_league}_{season}.json"
            )
            print_backtest_report(bt_result)
            save_backtest_report(bt_result, filepath=_report_path)
            plot_backtest_results(bt_result)

            # Save results to model_performance table for dashboard display.
            # Using the versioned key (e.g. "xgboost_v1") so the Model Health
            # page can find calibration data for the right model.
            save_backtest_to_model_performance(
                bt_result, season,
                model_name=_model_version_key,
                training_seasons=training_seasons,
            )

            result.predictions_made = bt_result.total_predicted
            result.value_bets_found = bt_result.total_value_bets

        except Exception as e:
            err = f"Backtest failed: {e}"
            logger.error(err, exc_info=True)
            errors.append(err)
            print(f"Backtest FAILED: {e}")

        duration = time.time() - start_time
        status = "completed" if not errors else "failed"

        self._complete_run(
            run_id, status,
            predictions_made=result.predictions_made,
            value_bets_found=result.value_bets_found,
            duration=duration,
            errors=errors,
        )

        result.status = status
        result.duration_seconds = round(duration, 2)
        result.errors = errors

        return result

    # ========================================================================
    # Internal helpers
    # ========================================================================

    def _generate_predictions(
        self,
        league_id: int,
        season: str,
        features_df: Any,
        league_short_name: Optional[str] = None,
    ) -> list:
        """Train active models and generate predictions.

        E25-02: Ensemble support — trains both Poisson and XGBoost (if enabled),
        generates predictions from each, then combines their scoreline matrices
        via weighted average to produce the ensemble prediction.

        Trains on ALL finished matches across ALL seasons (not just the
        current season) to maximise the training set.
        (MP §4: walk-forward uses all data up to the prediction date.)

        The pipeline stores up to 3 prediction records per match:
        - "poisson_v1": individual Poisson prediction
        - "xgboost_v1": individual XGBoost prediction (if enabled)
        - "ensemble_v1": weighted combination (if ensemble enabled)

        Returns a list of MatchPrediction objects (the primary predictions).
        """
        import pandas as pd

        from src.database.db import get_session
        from src.database.models import BetLog, Match, Prediction, ValueBet
        from src.models.base_model import (
            MatchPrediction,
            derive_market_probabilities,
        )
        from src.models.poisson import PoissonModel
        from src.models.storage import load_active_models, save_predictions
        from src.self_improvement.ensemble_weights import get_current_weights

        # Build results DataFrame for training from ALL historical seasons
        # (not just the current season).  More training data = better model.
        with get_session() as session:
            finished = (
                session.query(Match)
                .filter(
                    Match.league_id == league_id,
                    Match.status == "finished",
                )
                .all()
            )
            results_data = [
                {
                    "match_id": m.id,
                    "home_goals": m.home_goals,
                    "away_goals": m.away_goals,
                }
                for m in finished
                if m.home_goals is not None
            ]

            # Collect distinct historical seasons that have data
            hist_seasons = sorted(set(
                m.season for m in finished if m.season != season
            ))

        if len(results_data) < 20:
            logger.info("Not enough finished matches to train (%d < 20)", len(results_data))
            return []

        results_df = pd.DataFrame(results_data)

        # Build training features from ALL seasons.
        # The current season's features_df is passed in.  For historical
        # seasons, use load_features_bulk() which reads ALL pre-computed
        # features in 2 DB queries total (PC-10-03).  Previously this
        # called compute_all_features() per season, which made 5 queries
        # per match (~65,000 queries per league × 6 leagues = ~330,000
        # total).  Now it's 2 queries per league = ~12 total.
        all_features = features_df
        if hist_seasons:
            logger.info(
                "Loading historical features for training: %s",
                ", ".join(hist_seasons),
            )
            from src.features.engineer import load_features_bulk
            hist_df = load_features_bulk(league_id, hist_seasons)
            if not hist_df.empty:
                all_features = pd.concat(
                    [features_df, hist_df], ignore_index=True,
                )

        # Filter features to finished matches only for training
        all_finished_ids = set(results_df["match_id"].tolist())
        train_features = all_features[all_features["match_id"].isin(all_finished_ids)]
        current_count = len(features_df[features_df["match_id"].isin(all_finished_ids)])
        hist_count = len(train_features) - current_count
        logger.info(
            "Training on %d matches (%d current season + %d historical)",
            len(train_features), current_count, hist_count,
        )

        # ---- Determine which models to run (E37-03) ----
        # Read active models and ensemble flag from config.
        # load_active_models() handles XGBoost pkl loading / fallback.
        try:
            active_models = list(config.settings.models.active_models)
        except (AttributeError, TypeError):
            active_models = ["poisson_v1"]

        try:
            ensemble_enabled = bool(config.settings.models.ensemble_enabled)
        except (AttributeError, TypeError):
            ensemble_enabled = False

        # Load all active models.
        # - Poisson: always instantiated fresh (trained below).
        # - XGBoost: loaded from data/models/xgboost_v1.pkl (pre-trained).
        #   If pkl missing → logged as WARNING and excluded from loaded_models,
        #   so the pipeline falls back to Poisson-only gracefully (MP §11.3).
        loaded_models = load_active_models()

        # If ensemble was requested but XGBoost didn't load, disable ensemble
        # for this run — no silent degradation, just Poisson-only behaviour.
        loaded_keys = list(loaded_models.keys())
        if ensemble_enabled and len(loaded_keys) < 2:
            logger.warning(
                "Ensemble requested but only %d model(s) loaded (%s). "
                "Falling back to single-model mode for this run.",
                len(loaded_keys), loaded_keys,
            )
            print(
                f"  ⚠ Ensemble disabled this run: only {loaded_keys} available"
            )
            ensemble_enabled = False

        # ---- Train and predict from each loaded model ----
        # model_predictions maps model_name → list of MatchPrediction
        model_predictions = {}

        for model_key in active_models:
            model = loaded_models.get(model_key)
            if model is None:
                # Model was not loaded (e.g., XGBoost pkl missing) — already warned
                logger.info("Skipping '%s' — not loaded", model_key)
                continue

            # Check which matches still need predictions from this model.
            #
            # PC-09-02: Scheduled (upcoming) matches always get fresh
            # predictions because the model retrains daily with new data and
            # features may have changed (recent form, updated odds).  Only
            # FINISHED match predictions are cached — they're historical
            # records that don't change.
            with get_session() as session:
                # IDs of finished matches that already have predictions
                existing_pred_ids = set(
                    r[0] for r in session.query(Prediction.match_id)
                    .join(Match, Match.id == Prediction.match_id)
                    .filter(
                        Prediction.model_name == model.name,
                        Prediction.model_version == model.version,
                        Match.status == "finished",
                    )
                    .all()
                )

                # Delete stale predictions for SCHEDULED matches so they
                # get regenerated with the freshly-trained model.
                stale_scheduled = (
                    session.query(Prediction)
                    .join(Match, Match.id == Prediction.match_id)
                    .filter(
                        Prediction.model_name == model.name,
                        Prediction.model_version == model.version,
                        Match.status == "scheduled",
                    )
                    .all()
                )
                if stale_scheduled:
                    stale_count = len(stale_scheduled)
                    stale_pred_ids = [sp.id for sp in stale_scheduled]

                    # PC-11-01: Delete child rows BEFORE parent predictions
                    # to avoid ForeignKeyViolation on PostgreSQL (Neon).
                    #
                    # FK chain: BetLog.value_bet_id → ValueBet.prediction_id
                    #           → Prediction.id
                    # Must delete in reverse order: BetLog refs → VBs → Preds.

                    # Step 1: Find VB IDs that will be deleted
                    vb_ids_to_delete = [
                        vb_id for (vb_id,) in
                        session.query(ValueBet.id)
                        .filter(ValueBet.prediction_id.in_(stale_pred_ids))
                        .all()
                    ]

                    if vb_ids_to_delete:
                        # Step 2: Nullify BetLog.value_bet_id references
                        # (nullable FK — set to NULL, don't delete the log)
                        bl_nullified = (
                            session.query(BetLog)
                            .filter(BetLog.value_bet_id.in_(vb_ids_to_delete))
                            .update(
                                {BetLog.value_bet_id: None},
                                synchronize_session="fetch",
                            )
                        )

                        # Step 3: Delete the value bets
                        vb_deleted = (
                            session.query(ValueBet)
                            .filter(ValueBet.prediction_id.in_(stale_pred_ids))
                            .delete(synchronize_session="fetch")
                        )
                        logger.info(
                            "Cleared %d value bets (%d bet_log refs nullified) "
                            "for %d stale scheduled predictions",
                            vb_deleted, bl_nullified, stale_count,
                        )

                    # Step 4: Now safe to delete the predictions
                    for sp in stale_scheduled:
                        session.delete(sp)
                    session.commit()
                    logger.info(
                        "Refreshing predictions for %d scheduled matches "
                        "(deleted stale %s predictions)",
                        stale_count, model.name,
                    )

            predict_features = features_df[
                ~features_df["match_id"].isin(existing_pred_ids)
            ]
            if predict_features.empty:
                logger.info(
                    "All matches already have predictions from %s", model.name,
                )
                # Still need existing predictions for ensemble combining
                model_predictions[model.name] = []
                continue

            # Train the model on the full historical dataset — unless it was
            # pre-loaded from disk.  Poisson is always retrained (< 1 s).
            # XGBoost loaded from pkl is already trained; skip retrain to
            # preserve the pkl's weights (retrain only via `run train`).
            already_trained = getattr(model, "_is_trained", False)
            if not already_trained:
                try:
                    model.train(train_features, results_df)
                except Exception as e:
                    logger.error("Failed to train %s: %s", model.name, e)
                    continue
            else:
                logger.info(
                    "Using pre-loaded %s model (skipping retrain)", model.name,
                )

            # Generate predictions
            # PC-26-03: Pass league short name so per-league lambda clamps
            # from leagues.yaml are applied (Bundesliga [0.3, 4.0], etc.)
            try:
                preds = model.predict(predict_features, league=league_short_name)
            except TypeError:
                # Model doesn't accept league kwarg (e.g., older XGBoost pkl)
                preds = model.predict(predict_features)
            except Exception as e:
                logger.error("Failed to predict with %s: %s", model.name, e)
                continue

            # Save individual model predictions to DB (idempotent upsert)
            if preds:
                save_predictions(preds)
                logger.info(
                    "Generated %d predictions from %s", len(preds), model.name,
                )

            model_predictions[model.name] = preds

        # ---- Ensemble combination (E25-02) ----
        # If ensemble is enabled and we have predictions from 2+ models,
        # combine their scoreline matrices into an ensemble prediction.
        if ensemble_enabled and len(model_predictions) >= 2:
            ensemble_preds = self._combine_ensemble(
                model_predictions, active_models, features_df,
            )
            if ensemble_preds:
                save_predictions(ensemble_preds)
                logger.info(
                    "Generated %d ensemble predictions", len(ensemble_preds),
                )
                return ensemble_preds

        # Single-model mode: return the first model's predictions
        for model_key in active_models:
            preds = model_predictions.get(model_key, [])
            if preds:
                return preds

        return []

    @staticmethod
    def _create_model(model_key: str):
        """Instantiate a model class from its config key.

        Maps config strings like "poisson_v1" and "xgboost_v1" to their
        corresponding model classes.  Returns None for unknown keys.
        """
        from src.models.poisson import PoissonModel
        from src.models.xgboost_model import XGBoostModel

        model_map = {
            "poisson_v1": PoissonModel,
            "xgboost_v1": XGBoostModel,
        }
        cls = model_map.get(model_key)
        return cls() if cls else None

    def _combine_ensemble(
        self,
        model_predictions: dict,
        active_models: list,
        features_df: Any,
    ) -> list:
        """Combine predictions from multiple models into an ensemble.

        For each match, takes the weighted average of the scoreline matrices
        from all models, then derives market probabilities from the combined
        matrix.  Weights come from the ensemble_weights module (inverse Brier
        weighting with guardrails from MP §11.3).

        Only combines matches where ALL active models have predictions.
        """
        from src.models.base_model import (
            MatchPrediction,
            derive_market_probabilities,
        )
        from src.self_improvement.ensemble_weights import get_current_weights
        from src.database.db import get_session
        from src.database.models import Prediction

        # Get model names that actually produced predictions
        model_names = [
            name for name in active_models
            if name in model_predictions and model_predictions[name]
        ]
        if len(model_names) < 2:
            logger.info("Not enough models with predictions for ensemble")
            return []

        # Get current ensemble weights
        weights = get_current_weights(model_names)
        logger.info("Ensemble weights: %s", weights)

        # Check which matches already have ensemble predictions
        with get_session() as session:
            existing_ensemble_ids = set(
                r[0] for r in session.query(Prediction.match_id)
                .filter(
                    Prediction.model_name == "ensemble_v1",
                )
                .all()
            )

        # Build a lookup: match_id → {model_name: MatchPrediction}
        match_model_preds = {}
        for model_name, preds in model_predictions.items():
            for pred in preds:
                if pred.match_id not in match_model_preds:
                    match_model_preds[pred.match_id] = {}
                match_model_preds[pred.match_id][model_name] = pred

        ensemble_preds = []
        for match_id, preds_by_model in match_model_preds.items():
            # Skip if already have ensemble prediction
            if match_id in existing_ensemble_ids:
                continue

            # Only combine if ALL weighted models have predictions
            if not all(m in preds_by_model for m in model_names):
                continue

            # Weighted average of scoreline matrices
            combined_matrix = [[0.0] * 7 for _ in range(7)]
            combined_home_goals = 0.0
            combined_away_goals = 0.0

            for model_name in model_names:
                w = weights.get(model_name, 1.0 / len(model_names))
                pred = preds_by_model[model_name]
                combined_home_goals += w * pred.predicted_home_goals
                combined_away_goals += w * pred.predicted_away_goals

                for h in range(7):
                    for a in range(7):
                        combined_matrix[h][a] += w * pred.scoreline_matrix[h][a]

            # Renormalise the combined matrix (weights should sum to 1.0,
            # but clamping/rounding may introduce tiny errors)
            total = sum(
                combined_matrix[h][a] for h in range(7) for a in range(7)
            )
            if total > 0 and abs(total - 1.0) > 1e-6:
                combined_matrix = [
                    [p / total for p in row] for row in combined_matrix
                ]

            # Derive market probabilities from the combined matrix
            market_probs = derive_market_probabilities(combined_matrix)

            ensemble_pred = MatchPrediction(
                match_id=match_id,
                model_name="ensemble_v1",
                model_version="1.0.0",
                predicted_home_goals=round(combined_home_goals, 4),
                predicted_away_goals=round(combined_away_goals, 4),
                scoreline_matrix=combined_matrix,
                **market_probs,
            )
            ensemble_preds.append(ensemble_pred)

        return ensemble_preds

    @staticmethod
    def _get_league_id(short_name: str) -> Optional[int]:
        """Look up a league's database ID by its short name."""
        with get_session() as session:
            league = session.query(League).filter_by(short_name=short_name).first()
            return league.id if league else None

    @staticmethod
    def _get_all_active_league_ids() -> List[int]:
        """Get database IDs for all active leagues in config.

        E37-02: Used by the XGBoost walk-forward backtester to load training
        features from all leagues simultaneously, mirroring production.

        Returns
        -------
        list[int]
            League IDs for all active leagues (EPL, Championship, La Liga).
            Returns empty list if database lookup fails.
        """
        ids: List[int] = []
        with get_session() as session:
            for lg in config.leagues:
                row = session.query(League).filter_by(
                    short_name=lg.short_name
                ).first()
                if row:
                    ids.append(row.id)
        return ids

    @staticmethod
    def _get_training_seasons(league_short: str, target_season: str) -> List[str]:
        """Get all seasons up to and including target_season from config.

        Used by ``run_backtest()`` to auto-discover which historical seasons
        should be included in the training data.  Returns seasons in
        chronological order (earliest first).

        Parameters
        ----------
        league_short : str
            League short name (e.g. "EPL").
        target_season : str
            The evaluation season (e.g. "2024-25").

        Returns
        -------
        list[str]
            Seasons from config up to and including target_season.
            Falls back to ``[target_season]`` if config lookup fails.
        """
        try:
            for lg in config.leagues:
                if getattr(lg, "short_name", "") == league_short:
                    all_seasons = list(lg.seasons)
                    # Include only seasons <= target_season (chronological)
                    training = [s for s in all_seasons if s <= target_season]
                    if training:
                        return sorted(training)
        except Exception as e:
            logger.warning(
                "Could not auto-discover training seasons: %s. "
                "Falling back to target season only.", e,
            )
        return [target_season]

    @staticmethod
    def _get_default_user_id() -> Optional[int]:
        """Get the default (owner) user ID for system pick logging."""
        from src.database.models import User
        with get_session() as session:
            user = session.query(User).filter_by(role="owner").first()
            return user.id if user else None

    @staticmethod
    def _get_recently_finished_matches(league_id: int) -> List[int]:
        """Get IDs of recently finished matches that might have pending bets.

        Returns match IDs for finished matches in this league.  The
        resolve_bets function handles checking whether each match actually
        has pending bets, so we cast a wide net here.
        """
        from src.database.models import BetLog
        with get_session() as session:
            # Get match IDs that have pending bets and finished results
            pending_match_ids = (
                session.query(BetLog.match_id)
                .join(Match, BetLog.match_id == Match.id)
                .filter(
                    Match.league_id == league_id,
                    Match.status == "finished",
                    BetLog.status == "pending",
                )
                .distinct()
                .all()
            )
            return [r[0] for r in pending_match_ids]

    @staticmethod
    def _get_notifiable_users(email_type: str) -> List[int]:
        """Get user IDs that should receive a given email type.

        Checks that the user is active, has an email address set, and has
        the relevant notification preference enabled.

        Args:
            email_type: One of "morning", "evening", or "weekly".

        Returns:
            List of user IDs to send to.
        """
        from src.database.models import User

        # Map email type to the notification preference column
        notify_col_map = {
            "morning": User.notify_morning,
            "evening": User.notify_evening,
            "weekly": User.notify_weekly,
        }
        notify_col = notify_col_map.get(email_type)
        if notify_col is None:
            return []

        with get_session() as session:
            users = (
                session.query(User.id)
                .filter(
                    User.is_active == 1,
                    User.email.isnot(None),
                    User.email != "",
                    notify_col == 1,
                )
                .all()
            )
            return [u[0] for u in users]

    def _send_emails(
        self,
        email_type: str,
        run_id: int,
        errors: List[str],
    ) -> int:
        """Send emails to all notifiable users for the given email type.

        Wraps email sending in try/except so failures never crash the pipeline.
        Increments emails_sent on the pipeline run for each successful send.

        Args:
            email_type: "morning", "evening", or "weekly".
            run_id: Pipeline run ID for tracking emails_sent.
            errors: Mutable error list to append failures to.

        Returns:
            Number of emails successfully sent.
        """
        type_labels = {
            "morning": "morning picks",
            "evening": "evening review",
            "weekly": "weekly summary",
        }
        label = type_labels.get(email_type, email_type)
        print(f"\n[Email] Sending {label} emails...")

        user_ids = self._get_notifiable_users(email_type)
        if not user_ids:
            print(f"  → No users with {label} notifications enabled")
            return 0

        # Import email functions
        try:
            from src.delivery.email_alerts import (
                send_morning_picks,
                send_evening_review,
                send_weekly_summary,
            )
        except ImportError as e:
            err = f"Email module import failed: {e}"
            logger.error(err)
            errors.append(err)
            print(f"  → FAILED: {err}")
            return 0

        send_func_map = {
            "morning": send_morning_picks,
            "evening": send_evening_review,
            "weekly": send_weekly_summary,
        }
        send_func = send_func_map.get(email_type)
        if send_func is None:
            return 0

        sent_count = 0
        for user_id in user_ids:
            try:
                success = send_func(user_id)
                if success:
                    sent_count += 1
                    print(f"  → Sent {label} to user {user_id}")
                else:
                    print(f"  → Failed to send {label} to user {user_id}")
            except Exception as e:
                err = f"Email send failed for user {user_id} ({label}): {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → FAILED for user {user_id}: {e}")
                # Continue to next user — don't let one failure block others

        print(f"  → {sent_count}/{len(user_ids)} {label} emails sent")
        return sent_count

    @staticmethod
    def _create_pipeline_run(run_type: str) -> int:
        """Create a pipeline_runs record with status='running'.

        Returns the new run's database ID for updating later.
        Retries once on OperationalError (PC-26-01: handles transient DB locks
        from concurrent processes like backfill scripts or the dashboard).
        """
        import time as _time
        from sqlalchemy.exc import OperationalError as _OpErr

        for attempt in range(2):
            try:
                with get_session() as session:
                    run = PipelineRun(
                        run_type=run_type,
                        status="running",
                    )
                    session.add(run)
                    session.flush()
                    run_id = run.id
                return run_id
            except _OpErr as exc:
                if attempt == 0:
                    logger.warning(
                        "Database locked creating pipeline run — "
                        "retrying in 5s (attempt 1/2): %s", exc,
                    )
                    _time.sleep(5)
                else:
                    raise

    @staticmethod
    def _complete_run(
        run_id: int,
        status: str,
        matches_scraped: int = 0,
        predictions_made: int = 0,
        value_bets_found: int = 0,
        emails_sent: int = 0,
        duration: float = 0.0,
        errors: Optional[List[str]] = None,
    ) -> None:
        """Update a pipeline_runs record with final status and counts."""
        with get_session() as session:
            run = session.query(PipelineRun).filter_by(id=run_id).first()
            if run is None:
                logger.error("Pipeline run %d not found", run_id)
                return

            run.status = status
            run.completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            run.matches_scraped = matches_scraped
            run.predictions_made = predictions_made
            run.value_bets_found = value_bets_found
            run.emails_sent = emails_sent
            run.duration_seconds = round(duration, 2)

            if errors:
                # Store errors as a semicolon-separated string
                run.error_message = "; ".join(errors)
