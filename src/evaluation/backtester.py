"""
BetVector — Walk-Forward Backtester (E7-02)
=============================================
Simulates real-world usage on historical data to evaluate model performance
before risking real money.

Walk-Forward Validation
-----------------------
Walk-forward validation is the ONLY valid backtesting approach for
time-series prediction like sports betting.  It works like this:

  1. Start at matchday 1
  2. Train the model on all data before matchday 1 (just the pre-season)
  3. Predict matchday 1's matches
  4. Record predictions and find value bets
  5. Advance to matchday 2
  6. Train on all data before matchday 2 (including matchday 1's results)
  7. Predict matchday 2's matches
  8. ... continue through the entire season

**Why this matters:** Random train/test splits would leak future information
into the training set (a match from April might train the model that then
predicts a March match).  Walk-forward validation prevents this by ensuring
the model only ever sees data from before the prediction date — exactly as
it would in live operation.

**Training set grows over time:** As the season progresses, the model has
access to more data.  Early-season predictions (matchdays 1–5) have very
little training data and will be noisy.  This is realistic — in live
operation, we'd also have less data at the start of a new season.

Minimum Training Size
---------------------
The Poisson GLM requires at least 20 matches to fit (set in the model).
With a 38-matchday EPL season and 10 matches per matchday, we typically
need at least 2–3 matchdays before predictions become possible.  The
backtester skips matchdays where training data is insufficient.

Master Plan refs: MP §4 Evaluation, MP §12 Glossary (walk-forward validation)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

import pandas as pd

from src.betting.bankroll import BankrollManager
from src.betting.value_finder import MARKET_TO_PROB, ValueFinder
from src.database.db import get_session
from src.database.models import Match, ModelPerformance, Odds, Prediction, Team
from src.evaluation.metrics import (
    calculate_brier_score,
    calculate_calibration,
    calculate_roi,
)
from src.features.engineer import compute_all_features
from src.models.base_model import BaseModel, MatchPrediction
from src.models.storage import save_predictions

logger = logging.getLogger(__name__)


# ============================================================================
# BacktestResult Dataclass
# ============================================================================

@dataclass
class BacktestResult:
    """Results of a walk-forward backtest.

    Contains all metrics and data needed for analysis and plotting.
    """
    total_matches: int = 0
    total_predicted: int = 0
    total_value_bets: int = 0
    total_staked: float = 0.0
    total_pnl: float = 0.0
    roi: Optional[float] = None           # ROI as percentage
    brier_score: Optional[float] = None   # Lower is better (0 = perfect)
    calibration_data: Dict = field(default_factory=dict)
    clv_avg: Optional[float] = None
    daily_pnl_series: List[Dict[str, Any]] = field(default_factory=list)
    # Per-bet details for market breakdown in reports
    # Each entry: {stake, pnl, status, market_type, ...}
    bet_details: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# Walk-Forward Backtester
# ============================================================================

def run_backtest(
    league_id: int,
    season: str,
    model_class: Type[BaseModel],
    edge_threshold: float = 0.05,
    staking_method: str = "flat",
    stake_percentage: float = 0.02,
    starting_bankroll: float = 1000.0,
    training_seasons: Optional[List[str]] = None,
) -> BacktestResult:
    """Run a walk-forward backtest on a full season of historical data.

    For each matchday:
      1. Train the model on ALL matches before this date (from all
         ``training_seasons``, not just the target season)
      2. Compute features for this matchday's matches
      3. Generate predictions
      4. Find value bets against available odds
      5. Simulate betting with the specified staking method
      6. Record results and advance

    Multi-Season Training (E23-06)
    ------------------------------
    When ``training_seasons`` is provided, the backtester loads features from
    ALL specified seasons before the matchday loop begins.  This means that
    when predicting matchday 1 of 2024-25, the model trains on ~1,520 matches
    from 2020-21 through 2023-24 (instead of 0 matches with single-season).
    This dramatically improves early-season predictions and overall calibration.

    The ``_get_match_ids_before_date()`` and ``_get_results_before_date()``
    helpers already query ALL matches before a date (no season filter), so
    the training set naturally expands to include historical seasons.

    Parameters
    ----------
    league_id : int
        Database ID of the league.
    season : str
        Season identifier to evaluate on (e.g. "2024-25").
    model_class : Type[BaseModel]
        The model class to instantiate and train (e.g. PoissonModel).
    edge_threshold : float
        Minimum edge to flag a value bet (default 0.05 = 5%).
    staking_method : str
        Staking method: "flat", "percentage", or "kelly".
    stake_percentage : float
        Fraction of bankroll per bet (for flat/percentage methods).
    starting_bankroll : float
        Starting bankroll for the simulation.
    training_seasons : list[str] or None
        All seasons whose features should be available for training.
        If None, only the target ``season`` is loaded (original behaviour).
        Example: ``["2020-21", "2021-22", ..., "2024-25"]`` to train on
        5 seasons of data when evaluating 2024-25.

    Returns
    -------
    BacktestResult
        Complete backtest results with all metrics and daily PnL.
    """
    start_time = time.time()

    # Get all matches for this season, sorted by date
    matchdays = _get_matchdays(league_id, season)
    total_matchdays = len(matchdays)

    if total_matchdays == 0:
        logger.warning("run_backtest: No matchdays found for %s %s", league_id, season)
        return BacktestResult()

    # --- Pre-load features from all training seasons (E23-06) ---
    # Loading features ONCE before the loop is both faster and enables
    # multi-season training.  Previously, compute_all_features() was called
    # inside the loop on every matchday — redundant since features are stored
    # in the DB and don't change between matchdays.
    all_seasons = training_seasons or [season]
    print(f"Starting walk-forward backtest: {season}, {total_matchdays} matchdays")
    print(f"  Loading features from {len(all_seasons)} season(s): {', '.join(all_seasons)}")

    feature_load_start = time.time()
    features_dfs: List[pd.DataFrame] = []
    for s in all_seasons:
        try:
            sf = compute_all_features(league_id, s)
            features_dfs.append(sf)
            logger.info("Loaded %d feature rows for season %s", len(sf), s)
        except Exception as e:
            logger.warning("Backtest: Failed to load features for season %s: %s", s, e)

    if not features_dfs:
        logger.error("Backtest: No features loaded from any season")
        return BacktestResult()

    all_features = pd.concat(features_dfs, ignore_index=True)
    feature_load_time = time.time() - feature_load_start
    print(
        f"  → {len(all_features)} feature rows loaded "
        f"({len(all_features) // 2} matches) in {feature_load_time:.1f}s"
    )

    # Simulation state
    bankroll = starting_bankroll
    all_predictions: List[Dict] = []
    all_actuals: List[Dict] = []
    all_bet_results: List[Dict] = []
    daily_pnl_series: List[Dict] = []
    total_value_bets = 0
    total_predicted = 0

    # Value finder for comparing predictions to odds
    finder = ValueFinder()

    for day_idx, (match_date, match_ids) in enumerate(matchdays):
        matchday_num = day_idx + 1

        # --- Step 1: Split preloaded features into train and test sets ---
        # all_features contains features from ALL training_seasons.
        # _get_match_ids_before_date returns match IDs from ALL seasons
        # before this date, so training naturally includes historical data.
        train_match_ids = _get_match_ids_before_date(league_id, match_date)
        train_features = all_features[all_features["match_id"].isin(train_match_ids)]
        test_features = all_features[all_features["match_id"].isin(match_ids)]

        if test_features.empty:
            continue

        # --- Step 2: Build results DataFrame for training ---
        results_df = _get_results_before_date(league_id, match_date)

        if len(train_features) < 20 or len(results_df) < 20:
            print(
                f"  Matchday {matchday_num}/{total_matchdays} ({match_date}): "
                f"Skipping — insufficient training data ({len(train_features)} matches)"
            )
            continue

        # --- Step 3: Train model (only on data before this date) ---
        model = model_class()
        try:
            model.train(train_features, results_df)
        except Exception as e:
            logger.warning(
                "Backtest: Model training failed at matchday %d: %s",
                matchday_num, e,
            )
            continue

        # --- Step 4: Predict this matchday's matches ---
        try:
            predictions = model.predict(test_features)
        except Exception as e:
            logger.warning(
                "Backtest: Prediction failed at matchday %d: %s",
                matchday_num, e,
            )
            continue

        total_predicted += len(predictions)

        # --- Step 5: Find value bets and simulate betting ---
        day_value_bets = 0
        day_pnl = 0.0
        day_staked = 0.0

        for pred in predictions:
            # Store prediction for Brier score calculation
            all_predictions.append({
                "match_id": pred.match_id,
                "prob_home_win": pred.prob_home_win,
                "prob_draw": pred.prob_draw,
                "prob_away_win": pred.prob_away_win,
            })

            # Get actual result for this match
            actual = _get_match_result(pred.match_id)
            if actual:
                all_actuals.append(actual)

            # Get odds for this match
            odds_list = finder._get_match_odds(pred.match_id)
            if not odds_list:
                continue

            # Find value bets
            for odds_row in odds_list:
                key = (odds_row["market_type"], odds_row["selection"])
                prob_field = MARKET_TO_PROB.get(key)
                if prob_field is None:
                    continue

                model_prob = getattr(pred, prob_field, None)
                if model_prob is None:
                    continue

                implied_prob = 1.0 / odds_row["odds_decimal"]
                edge = model_prob - implied_prob

                if edge < edge_threshold:
                    continue

                # This is a value bet — simulate placing it
                day_value_bets += 1
                total_value_bets += 1

                # Calculate stake
                if staking_method == "kelly":
                    raw_kelly = BankrollManager._kelly_stake(
                        model_prob=model_prob,
                        odds=odds_row["odds_decimal"],
                        kelly_fraction=0.25,
                        bankroll=bankroll,
                    )
                    stake = min(raw_kelly, bankroll * 0.05)
                else:
                    stake = bankroll * stake_percentage
                    stake = min(stake, bankroll * 0.05)

                stake = round(max(0.0, stake), 2)
                if stake == 0:
                    continue

                day_staked += stake

                # Determine if this bet won (using actual result)
                if actual:
                    won = _check_bet_result(
                        odds_row["market_type"],
                        odds_row["selection"],
                        actual["home_goals"],
                        actual["away_goals"],
                    )

                    if won:
                        pnl = round(stake * (odds_row["odds_decimal"] - 1.0), 2)
                    else:
                        pnl = round(-stake, 2)

                    bankroll = round(bankroll + pnl, 2)
                    day_pnl += pnl

                    all_bet_results.append({
                        "stake": stake,
                        "pnl": pnl,
                        "status": "won" if won else "lost",
                        "market_type": odds_row["market_type"],
                        "closing_odds": None,
                        "odds_at_placement": odds_row["odds_decimal"],
                        "odds_at_detection": odds_row["odds_decimal"],
                    })

        # Record daily PnL
        daily_pnl_series.append({
            "date": match_date,
            "matchday": matchday_num,
            "pnl": round(day_pnl, 2),
            "cumulative_pnl": round(bankroll - starting_bankroll, 2),
            "bankroll": bankroll,
            "value_bets": day_value_bets,
            "matches": len(match_ids),
        })

        # Progress message
        running_roi = (
            ((bankroll - starting_bankroll) / max(sum(b["stake"] for b in all_bet_results), 1))
            * 100
        ) if all_bet_results else 0

        print(
            f"  Matchday {matchday_num}/{total_matchdays} ({match_date}): "
            f"{day_value_bets} value bets, "
            f"day PnL: £{day_pnl:+.2f}, "
            f"bankroll: £{bankroll:.2f}, "
            f"running ROI: {running_roi:+.1f}%"
        )

    # --- Calculate final metrics ---
    elapsed = time.time() - start_time

    brier = calculate_brier_score(all_predictions, all_actuals)
    roi = calculate_roi(all_bet_results)
    calibration = calculate_calibration(all_predictions, all_actuals)

    total_staked = sum(b["stake"] for b in all_bet_results)
    total_pnl = round(bankroll - starting_bankroll, 2)

    result = BacktestResult(
        total_matches=sum(len(ids) for _, ids in matchdays),
        total_predicted=total_predicted,
        total_value_bets=total_value_bets,
        total_staked=round(total_staked, 2),
        total_pnl=total_pnl,
        roi=roi,
        brier_score=brier,
        calibration_data=calibration,
        clv_avg=None,  # No closing odds in historical backtest
        daily_pnl_series=daily_pnl_series,
        bet_details=all_bet_results,
    )

    print(f"\nBacktest complete in {elapsed:.1f}s")
    print(f"  Training data: {len(all_seasons)} season(s)")
    print(f"  Matches: {result.total_matches}, Predicted: {result.total_predicted}")
    print(f"  Value bets: {result.total_value_bets}, Staked: £{result.total_staked:.2f}")
    print(f"  Final PnL: £{result.total_pnl:+.2f}, ROI: {result.roi or 0:.1f}%")
    print(f"  Brier score: {result.brier_score or 'N/A'}")

    return result


def save_backtest_to_model_performance(
    result: BacktestResult,
    season: str,
    model_name: str = "poisson_v1",
    training_seasons: Optional[List[str]] = None,
) -> None:
    """Store backtest results in the model_performance table.

    Creates a ModelPerformance record with period_type="backtest" so it
    can be distinguished from live performance metrics.  The model_name
    includes the number of training seasons for A/B comparison
    (e.g., "poisson_v1_6s" for 6-season training).

    Parameters
    ----------
    result : BacktestResult
        Completed backtest results.
    season : str
        The evaluation season (e.g., "2024-25").
    model_name : str
        Base model name (default: "poisson_v1").
    training_seasons : list[str] or None
        Seasons used for training — appended to model_name for tracking.
    """
    import json
    from datetime import datetime
    from src.database.models import ModelPerformance

    # Tag model name with training season count for comparison
    n_seasons = len(training_seasons) if training_seasons else 1
    tagged_name = f"{model_name}_{n_seasons}s"

    calibration_json = (
        json.dumps(result.calibration_data)
        if result.calibration_data
        else None
    )

    # Compute per-market win rates from bet_details
    win_rates = {"1x2": None, "ou": None, "btts": None}
    for market_key, prefixes in [
        ("1x2", ["1X2"]),
        ("ou", ["OU25", "OU15", "OU35"]),
        ("btts", ["BTTS"]),
    ]:
        market_bets = [
            b for b in result.bet_details
            if b.get("market_type") in prefixes
        ]
        if market_bets:
            wins = sum(1 for b in market_bets if b["status"] == "won")
            win_rates[market_key] = round(wins / len(market_bets) * 100, 1)

    with get_session() as session:
        # Upsert: check if a record already exists for this model+season
        existing = session.query(ModelPerformance).filter_by(
            model_name=tagged_name,
            period_type="backtest",
            period_start=season,
        ).first()

        if existing:
            existing.total_predictions = result.total_predicted
            existing.brier_score = result.brier_score
            existing.roi = result.roi
            existing.avg_clv = result.clv_avg
            existing.calibration_json = calibration_json
            existing.win_rate_1x2 = win_rates["1x2"]
            existing.win_rate_ou = win_rates["ou"]
            existing.win_rate_btts = win_rates["btts"]
            existing.computed_at = datetime.utcnow().isoformat()
            logger.info("Updated model_performance for %s backtest %s", tagged_name, season)
        else:
            row = ModelPerformance(
                model_name=tagged_name,
                period_type="backtest",
                period_start=season,
                period_end=season,
                total_predictions=result.total_predicted,
                brier_score=result.brier_score,
                roi=result.roi,
                avg_clv=result.clv_avg,
                calibration_json=calibration_json,
                win_rate_1x2=win_rates["1x2"],
                win_rate_ou=win_rates["ou"],
                win_rate_btts=win_rates["btts"],
            )
            session.add(row)
            logger.info("Saved model_performance for %s backtest %s", tagged_name, season)

    print(f"  → Results saved to model_performance as '{tagged_name}'")



# ============================================================================
# Internal Helpers
# ============================================================================

def _get_matchdays(
    league_id: int,
    season: str,
) -> List[tuple]:
    """Get all matchdays as (date, [match_ids]) pairs, sorted chronologically.

    Groups matches by date (one matchday = all matches on the same date).
    """
    with get_session() as session:
        matches = (
            session.query(Match)
            .filter_by(league_id=league_id, season=season, status="finished")
            .order_by(Match.date)
            .all()
        )

        # Group by date
        from collections import OrderedDict
        days: OrderedDict = OrderedDict()
        for m in matches:
            if m.date not in days:
                days[m.date] = []
            days[m.date].append(m.id)

    return list(days.items())


def _get_match_ids_before_date(league_id: int, before_date: str) -> List[int]:
    """Get all finished match IDs strictly before a date."""
    with get_session() as session:
        rows = (
            session.query(Match.id)
            .filter(
                Match.league_id == league_id,
                Match.date < before_date,
                Match.status == "finished",
            )
            .all()
        )
        return [r[0] for r in rows]


def _get_results_before_date(
    league_id: int,
    before_date: str,
) -> pd.DataFrame:
    """Get match results before a date as a DataFrame."""
    with get_session() as session:
        matches = (
            session.query(Match)
            .filter(
                Match.league_id == league_id,
                Match.date < before_date,
                Match.status == "finished",
            )
            .all()
        )

        data = [
            {
                "match_id": m.id,
                "home_goals": m.home_goals,
                "away_goals": m.away_goals,
            }
            for m in matches
        ]

    return pd.DataFrame(data) if data else pd.DataFrame(
        columns=["match_id", "home_goals", "away_goals"]
    )


def _get_match_result(match_id: int) -> Optional[Dict]:
    """Get the actual result for a match."""
    with get_session() as session:
        m = session.query(Match).filter_by(id=match_id).first()
        if m and m.home_goals is not None:
            return {
                "match_id": m.id,
                "home_goals": m.home_goals,
                "away_goals": m.away_goals,
            }
    return None


def _check_bet_result(
    market_type: str,
    selection: str,
    home_goals: int,
    away_goals: int,
) -> bool:
    """Determine if a bet won based on the actual result."""
    total = home_goals + away_goals

    if market_type == "1X2":
        if selection == "home":
            return home_goals > away_goals
        elif selection == "draw":
            return home_goals == away_goals
        elif selection == "away":
            return home_goals < away_goals
    elif market_type == "OU25":
        if selection == "over":
            return total >= 3
        elif selection == "under":
            return total <= 2
    elif market_type == "OU15":
        if selection == "over":
            return total >= 2
        elif selection == "under":
            return total <= 1
    elif market_type == "OU35":
        if selection == "over":
            return total >= 4
        elif selection == "under":
            return total <= 3
    elif market_type == "BTTS":
        if selection == "yes":
            return home_goals >= 1 and away_goals >= 1
        elif selection == "no":
            return home_goals == 0 or away_goals == 0

    return False
