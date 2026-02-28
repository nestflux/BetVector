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
from src.database.models import League, Match, PipelineRun
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
        """Full morning pipeline: scrape → load → features → predict → value → log.

        This is the primary daily run that:
        1. Downloads latest match data and odds from all sources
        2. Loads scraped data into the database
        3. Computes features for all matches
        4. Generates model predictions for upcoming matches
        5. Compares predictions to bookmaker odds to find value bets
        6. Auto-logs value bets as system picks for tracking

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
            print(f"[Step 1/6] Scraping data for {league_name} {current_season}...")
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

            # --- Step 2: Load into database ---
            print(f"[Step 2/6] Loading data into database...")
            try:
                from src.scrapers.loader import load_matches, load_odds, load_match_stats

                if fd_df is not None and not fd_df.empty:
                    match_result = load_matches(fd_df, league_id, current_season)
                    matches_scraped = match_result.get("new", 0)
                    print(f"  → Matches: {match_result}")

                    odds_result = load_odds(fd_df, league_id)
                    print(f"  → Odds: {odds_result}")

                if fbref_df is not None and not fbref_df.empty:
                    stats_result = load_match_stats(fbref_df, league_id)
                    print(f"  → Match stats: {stats_result}")

            except Exception as e:
                err = f"Data loading failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Loading: FAILED ({e})")

            total_matches_scraped += matches_scraped

            # --- Step 3: Compute features ---
            print(f"[Step 3/6] Computing features for {league_name}...")
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
            print(f"[Step 4/6] Generating predictions...")
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
            print(f"[Step 5/6] Finding value bets...")
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
            print(f"[Step 6/6] Logging system picks...")
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

        # --- Finalize ---
        duration = time.time() - start_time
        status = "completed" if not errors else "completed"
        # Only mark as "failed" if ALL leagues had critical failures
        # (scraping + loading + features all failed for every league)
        if total_predictions == 0 and total_matches_scraped == 0:
            status = "failed"

        self._complete_run(
            run_id, status,
            matches_scraped=total_matches_scraped,
            predictions_made=total_predictions,
            value_bets_found=total_value_bets,
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
            try:
                from src.scrapers.football_data import FootballDataScraper
                from src.scrapers.loader import load_odds

                scraper = FootballDataScraper()
                fd_df = scraper.scrape(league_config=league_cfg, season=current_season)
                if not fd_df.empty:
                    odds_result = load_odds(fd_df, league_id)
                    print(f"  → Odds updated: {odds_result}")
                else:
                    print("  → No odds data returned")
            except Exception as e:
                err = f"Odds re-fetch failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Odds: FAILED ({e})")
                continue

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
        """Evening results pipeline: resolve bets → P&L → metrics.

        After the day's matches are finished:
        1. Scrape latest results to update match scores
        2. Resolve pending bets (determine won/lost, calculate P&L)
        3. Update user bankrolls
        4. Generate updated performance metrics

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
            print(f"[Step 1/4] Scraping results for {league_name}...")
            try:
                from src.scrapers.football_data import FootballDataScraper
                from src.scrapers.loader import load_matches, load_odds

                scraper = FootballDataScraper()
                fd_df = scraper.scrape(league_config=league_cfg, season=current_season)
                if not fd_df.empty:
                    match_result = load_matches(fd_df, league_id, current_season)
                    total_matches_scraped += match_result.get("new", 0)
                    print(f"  → Matches: {match_result}")

                    # Also update odds in case of late changes
                    odds_result = load_odds(fd_df, league_id)
                    print(f"  → Odds: {odds_result}")
                else:
                    print("  → No data returned")
            except Exception as e:
                err = f"Results scrape failed for {league_name}: {e}"
                logger.error(err)
                errors.append(err)
                print(f"  → Results: FAILED ({e})")

            # --- Step 2: Resolve pending bets ---
            print(f"[Step 2/4] Resolving pending bets...")
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
            print(f"[Step 3/4] Updating performance metrics...")
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

            # --- Step 4: (Email placeholder — E11) ---
            print(f"[Step 4/4] Email delivery... (not yet implemented — E11)")

        duration = time.time() - start_time
        status = "completed"

        self._complete_run(
            run_id, status,
            matches_scraped=total_matches_scraped,
            duration=duration,
            errors=errors,
        )

        result.status = status
        result.matches_scraped = total_matches_scraped
        result.duration_seconds = round(duration, 2)
        result.errors = errors

        print(f"\nEvening pipeline complete in {duration:.1f}s")
        print(f"  Matches updated: {total_matches_scraped}")
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

        Trains on all finished matches, then predicts matches that don't
        yet have predictions from the active model.

        Returns a list of MatchPrediction objects.
        """
        import pandas as pd

        from src.database.db import get_session
        from src.database.models import Match, Prediction
        from src.models.poisson import PoissonModel
        from src.models.storage import save_predictions

        # Build results DataFrame for training (finished matches only)
        with get_session() as session:
            finished = (
                session.query(Match)
                .filter(
                    Match.league_id == league_id,
                    Match.season == season,
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

        if len(results_data) < 20:
            logger.info("Not enough finished matches to train (%d < 20)", len(results_data))
            return []

        results_df = pd.DataFrame(results_data)

        # Filter features to finished matches for training
        finished_ids = set(results_df["match_id"].tolist())
        train_features = features_df[features_df["match_id"].isin(finished_ids)]

        # Train the model
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
