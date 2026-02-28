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
from src.database.models import Match, Odds, Prediction, Team
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
) -> BacktestResult:
    """Run a walk-forward backtest on a full season of historical data.

    For each matchday:
      1. Train the model on ALL matches before this date
      2. Compute features for this matchday's matches
      3. Generate predictions
      4. Find value bets against available odds
      5. Simulate betting with the specified staking method
      6. Record results and advance

    Parameters
    ----------
    league_id : int
        Database ID of the league.
    season : str
        Season identifier (e.g. "2024-25").
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

    print(f"Starting walk-forward backtest: {season}, {total_matchdays} matchdays")

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

        # --- Step 1: Get all features (uses expanding window up to this date) ---
        # compute_all_features builds features for ALL matches in the season.
        # We'll filter to only use data before match_date for training.
        try:
            all_features = compute_all_features(league_id, season)
        except Exception as e:
            logger.warning("Backtest: Feature computation failed at %s: %s", match_date, e)
            continue

        # Split features into training set (before this date) and test set (this date)
        train_features = all_features[all_features["match_id"].isin(
            _get_match_ids_before_date(league_id, match_date)
        )]
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
    print(f"  Matches: {result.total_matches}, Predicted: {result.total_predicted}")
    print(f"  Value bets: {result.total_value_bets}, Staked: £{result.total_staked:.2f}")
    print(f"  Final PnL: £{result.total_pnl:+.2f}, ROI: {result.roi or 0:.1f}%")
    print(f"  Brier score: {result.brier_score or 'N/A'}")

    return result


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
