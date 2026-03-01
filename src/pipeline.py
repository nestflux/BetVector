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
from src.database.models import League, Match, PipelineRun, Weather
from src.database.seed import seed_all

logger = logging.getLogger(__name__)


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

    Usage::

        pipeline = Pipeline()
        result = pipeline.run_morning()
        print(f"Found {result.value_bets_found} value bets")
    """

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
                    print(f"  → API-Football injuries: {len(api_football_injuries)} records")
                else:
                    print("  → API-Football injuries: No data returned")

            except Exception as e:
                err = f"API-Football scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → API-Football: FAILED ({e})")

            # 1d. Understat (xG data — replaces blocked FBref)
            understat_df = None
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

            # --- Step 2: Load into database ---
            print(f"[Step 2/7] Loading data into database...")
            try:
                from src.scrapers.loader import (
                    load_matches, load_odds, load_match_stats,
                    load_odds_api_football, load_understat_stats,
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

                # FBref match stats
                if fbref_df is not None and not fbref_df.empty:
                    stats_result = load_match_stats(fbref_df, league_id)
                    print(f"  → Match stats (FBref): {stats_result}")

                # Understat xG stats (fills gaps where FBref is blocked)
                if understat_df is not None and not understat_df.empty:
                    us_result = load_understat_stats(understat_df, league_id)
                    print(f"  → xG stats (Understat): {us_result}")

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
                from src.betting.value_finder import ValueFinder
                finder = ValueFinder()
                edge_threshold = config.settings.value_betting.edge_threshold

                all_value_bets = []
                for pred in predictions:
                    vbs = finder.find_value_bets(
                        match_id=pred.match_id,
                        edge_threshold=edge_threshold,
                        model_name=pred.model_name,
                    )
                    all_value_bets.extend(vbs)

                if all_value_bets:
                    save_result = finder.save_value_bets(all_value_bets)
                    total_value_bets += save_result.get("new", 0)
                    print(f"  → {len(all_value_bets)} value bets found, "
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

            # --- Step 2: Recalculate edges ---
            print(f"[Step 2/3] Recalculating value bets for {league_name}...")
            try:
                from src.betting.value_finder import ValueFinder
                from src.models.storage import get_latest_predictions

                finder = ValueFinder()
                edge_threshold = config.settings.value_betting.edge_threshold

                # Get existing predictions for upcoming matches
                predictions = get_latest_predictions(league_id=league_id)
                all_value_bets = []

                for pred in predictions:
                    vbs = finder.find_value_bets(
                        match_id=pred.match_id,
                        edge_threshold=edge_threshold,
                        model_name=pred.model_name,
                    )
                    all_value_bets.extend(vbs)

                if all_value_bets:
                    save_result = finder.save_value_bets(all_value_bets)
                    total_value_bets += save_result.get("new", 0)
                    print(f"  → {len(all_value_bets)} value bets, "
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
            except Exception as e:
                err = f"Transfermarkt market value refresh failed: {e}"
                logger.error(err)
                errors.append(err)
                print(f"    → Transfermarkt: FAILED ({e})")

            # --- Weekly: Send weekly summary email ---
            weekly_sent = self._send_emails("weekly", run_id, errors)
            emails_sent += weekly_sent

        result.emails_sent = emails_sent

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

    def run_backtest(
        self,
        league: str = "EPL",
        season: str = "2024-25",
    ) -> PipelineResult:
        """Run a walk-forward backtest via the backtester module.

        Delegates to ``src.evaluation.backtester.run_backtest()`` and wraps
        the result in a PipelineResult for consistent tracking.

        Parameters
        ----------
        league : str
            Short name of the league (e.g. "EPL").
        season : str
            Season identifier (e.g. "2024-25").

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

        print(f"Running walk-forward backtest: {league} {season}")
        try:
            from src.evaluation.backtester import run_backtest as bt_run
            from src.evaluation.reporter import (
                print_backtest_report,
                save_backtest_report,
                plot_backtest_results,
            )
            from src.models.poisson import PoissonModel

            # Read staking config
            bankroll_cfg = config.settings.bankroll
            edge_threshold = config.settings.value_betting.edge_threshold

            bt_result = bt_run(
                league_id=league_id,
                season=season,
                model_class=PoissonModel,
                edge_threshold=edge_threshold,
                staking_method=bankroll_cfg.staking_method,
                stake_percentage=bankroll_cfg.stake_percentage,
                starting_bankroll=bankroll_cfg.starting_amount,
            )

            # Print and save the report
            print_backtest_report(bt_result)
            save_backtest_report(bt_result)
            plot_backtest_results(bt_result)

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
    ) -> list:
        """Train the model and generate predictions for matches needing them.

        Trains on ALL finished matches across ALL seasons (not just the
        current season) to maximise the training set.  The Poisson model
        benefits from more data — 5+ seasons of results produce more
        stable attack/defence estimates than a single season alone.
        (MP §4: walk-forward uses all data up to the prediction date.)

        Historical season features are loaded via compute_all_features()
        which reads from the features table.  This is idempotent — if
        features are already computed, they're read from the DB instantly.

        Predictions are only generated for the current season's matches
        that don't yet have predictions from the active model.

        Returns a list of MatchPrediction objects.
        """
        import pandas as pd

        from src.database.db import get_session
        from src.database.models import Match, Prediction
        from src.features.engineer import compute_all_features
        from src.models.poisson import PoissonModel
        from src.models.storage import save_predictions

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
        # seasons, call compute_all_features() which reads existing features
        # from the DB (idempotent — no recomputation if already stored).
        all_features = features_df
        if hist_seasons:
            logger.info(
                "Loading historical features for training: %s",
                ", ".join(hist_seasons),
            )
            hist_dfs = []
            for hist_season in hist_seasons:
                hist_df = compute_all_features(league_id, hist_season)
                if not hist_df.empty:
                    hist_dfs.append(hist_df)
            if hist_dfs:
                all_features = pd.concat(
                    [features_df] + hist_dfs, ignore_index=True,
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

        # Train the model on the full historical dataset
        model = PoissonModel()
        model.train(train_features, results_df)

        # Find matches that need predictions (finished matches without
        # predictions from this model, plus any scheduled matches)
        with get_session() as session:
            existing_pred_ids = set(
                r[0] for r in session.query(Prediction.match_id)
                .filter(
                    Prediction.model_name == model.name,
                    Prediction.model_version == model.version,
                )
                .all()
            )

        # Predict all matches in the features DataFrame that don't have predictions
        predict_features = features_df[~features_df["match_id"].isin(existing_pred_ids)]

        if predict_features.empty:
            logger.info("All matches already have predictions from %s", model.name)
            return []

        predictions = model.predict(predict_features)

        # Save to database
        if predictions:
            save_predictions(predictions)

        return predictions

    @staticmethod
    def _get_league_id(short_name: str) -> Optional[int]:
        """Look up a league's database ID by its short name."""
        with get_session() as session:
            league = session.query(League).filter_by(short_name=short_name).first()
            return league.id if league else None

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
        """
        with get_session() as session:
            run = PipelineRun(
                run_type=run_type,
                status="running",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        return run_id

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
