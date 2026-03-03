"""
BetVector — Metrics Module (E7-01)
====================================
Calculates evaluation metrics for model predictions and betting performance.

Understanding the Metrics
-------------------------
These metrics answer different questions about system performance:

**ROI (Return on Investment)**
  "Am I making money?"
  ROI = total_pnl / total_staked × 100
  - **Good:** > 0% (profitable)
  - **Great:** > 5% (strong edge)
  - **Typical:** Professional sports bettors aim for 2–5% ROI long-term.
  - **Context:** ROI is heavily influenced by variance in the short term.
    A 100-bet sample tells you almost nothing — you need 500+ bets for
    ROI to stabilise.

**Brier Score**
  "How accurate are my probability estimates?"
  Brier = mean[ (predicted_prob - actual_outcome)² ]
  - **0.0:** Perfect predictions (predicted 100% for events that happened)
  - **0.25:** Useless — equivalent to predicting 50/50 on everything
  - **Good:** < 0.20 for 1X2 market (hard to do better due to football's
    inherent randomness)
  - For the 1X2 market (3 outcomes), the Brier score is the sum of
    squared errors across all three outcomes per match, averaged.

**Calibration**
  "When I say 60%, does it happen 60% of the time?"
  Predictions are bucketed by probability range (e.g., 0.50–0.60),
  and we compare the average predicted probability to the actual win
  rate in each bucket.
  - **Perfect calibration:** Points lie on the diagonal (y = x)
  - **Overconfident:** Actual rates below predicted (model too bullish)
  - **Underconfident:** Actual rates above predicted (model too cautious)

**CLV (Closing Line Value)**
  "Am I beating the market?"
  CLV compares the odds you got to the final closing line.
  - **Positive average CLV:** You're consistently getting better odds than
    the market closes at — the single best predictor of long-term profit.
  - **Negative average CLV:** The market is smarter than your timing.

Master Plan refs: MP §4 Evaluation, MP §6 model_performance table,
                  MP §7 Pipeline Orchestrator, MP §12 Glossary
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.database.db import get_session
from src.database.models import BetLog, Match, ModelPerformance, Prediction

logger = logging.getLogger(__name__)


# ============================================================================
# ROI
# ============================================================================

def calculate_roi(bet_logs: List[Dict[str, Any]]) -> Optional[float]:
    """Calculate Return on Investment from bet history.

    ROI = (total_pnl / total_staked) × 100

    Example:
      Staked $1000 total across 50 bets.
      Won back $1050 total.
      PnL = +$50.
      ROI = 50 / 1000 × 100 = 5.0%

    Parameters
    ----------
    bet_logs : list[dict]
        Bet history entries (from ``get_bet_history()``).
        Each must have ``stake`` and ``pnl`` keys.

    Returns
    -------
    float or None
        ROI as a percentage (5.0 means 5%).
        None if no bets or zero total stake.
    """
    if not bet_logs:
        return None

    total_staked = sum(b["stake"] for b in bet_logs if b["stake"])
    total_pnl = sum(b["pnl"] for b in bet_logs if b["pnl"] is not None)

    if total_staked == 0:
        return None

    # ROI as a percentage: 5.0 means 5% return
    roi = (total_pnl / total_staked) * 100.0
    return round(roi, 2)


# ============================================================================
# Brier Score
# ============================================================================

def calculate_brier_score(
    predictions: List[Dict[str, float]],
    actuals: List[Dict[str, int]],
) -> Optional[float]:
    """Calculate the Brier score for 1X2 market predictions.

    The Brier score measures the accuracy of probabilistic predictions.
    For the 1X2 market (three mutually exclusive outcomes), we compute:

      Brier = mean[ (p_home - y_home)² + (p_draw - y_draw)² + (p_away - y_away)² ]

    Where:
      p_home, p_draw, p_away = model's predicted probabilities
      y_home, y_draw, y_away = actual outcomes (one is 1, others are 0)

    **Interpreting the Brier score:**
      0.0 = perfect predictions (impossible in practice for football)
      0.25 = predicting 33/33/33 on every match (no skill)
      > 0.25 = worse than random
      < 0.20 = good for football 1X2 predictions

    A "trivial" predictor that always outputs the base rate (~45% home,
    ~27% draw, ~28% away for the EPL) would score about 0.22.  Beating
    that means your model adds value.

    Parameters
    ----------
    predictions : list[dict]
        Each dict must have: prob_home_win, prob_draw, prob_away_win.
    actuals : list[dict]
        Each dict must have: match_id, home_goals, away_goals.
        Must be in the same order / matched by index.

    Returns
    -------
    float or None
        Brier score (lower is better). None if no valid pairs.
    """
    if not predictions or not actuals:
        return None

    if len(predictions) != len(actuals):
        raise ValueError(
            f"predictions ({len(predictions)}) and actuals ({len(actuals)}) "
            f"must have the same length"
        )

    total_brier = 0.0
    valid_count = 0

    for pred, actual in zip(predictions, actuals):
        home_goals = actual.get("home_goals")
        away_goals = actual.get("away_goals")

        if home_goals is None or away_goals is None:
            continue

        # Determine the actual outcome (one-hot encoding)
        # y_home=1 if home won, y_draw=1 if draw, y_away=1 if away won
        if home_goals > away_goals:
            y_home, y_draw, y_away = 1, 0, 0
        elif home_goals == away_goals:
            y_home, y_draw, y_away = 0, 1, 0
        else:
            y_home, y_draw, y_away = 0, 0, 1

        # Brier score for this match (sum of squared errors)
        p_home = pred.get("prob_home_win", 0)
        p_draw = pred.get("prob_draw", 0)
        p_away = pred.get("prob_away_win", 0)

        brier = (
            (p_home - y_home) ** 2
            + (p_draw - y_draw) ** 2
            + (p_away - y_away) ** 2
        )
        total_brier += brier
        valid_count += 1

    if valid_count == 0:
        return None

    return round(total_brier / valid_count, 6)


# ============================================================================
# Calibration
# ============================================================================

def calculate_calibration(
    predictions: List[Dict[str, float]],
    actuals: List[Dict[str, int]],
    n_bins: int = 10,
) -> Dict[str, Dict[str, Any]]:
    """Calculate calibration data for probability predictions.

    Buckets all 1X2 predicted probabilities into bins (e.g., 0.0–0.1,
    0.1–0.2, ..., 0.9–1.0), then computes the actual win rate in each bin.

    Perfect calibration means: when the model says "60% chance", the
    actual outcome occurs 60% of the time.  The calibration plot (predicted
    vs actual) should lie on the diagonal y = x.

    Parameters
    ----------
    predictions : list[dict]
        Each dict must have: prob_home_win, prob_draw, prob_away_win.
    actuals : list[dict]
        Each dict must have: home_goals, away_goals.
    n_bins : int
        Number of probability bins (default 10 → 0.0–0.1, ..., 0.9–1.0).

    Returns
    -------
    dict
        Keys are bin labels like ``"0.5-0.6"``.
        Values are dicts with: predicted_avg, actual_rate, count.
    """
    # Collect (predicted_prob, actual_outcome) pairs for all selections
    # We treat each 1X2 selection as a separate observation
    pairs: List[Tuple[float, int]] = []

    for pred, actual in zip(predictions, actuals):
        home_goals = actual.get("home_goals")
        away_goals = actual.get("away_goals")
        if home_goals is None or away_goals is None:
            continue

        # Actual outcomes
        if home_goals > away_goals:
            y_home, y_draw, y_away = 1, 0, 0
        elif home_goals == away_goals:
            y_home, y_draw, y_away = 0, 1, 0
        else:
            y_home, y_draw, y_away = 0, 0, 1

        pairs.append((pred.get("prob_home_win", 0), y_home))
        pairs.append((pred.get("prob_draw", 0), y_draw))
        pairs.append((pred.get("prob_away_win", 0), y_away))

    if not pairs:
        return {}

    # Bucket into bins
    bin_width = 1.0 / n_bins
    bins: Dict[str, List[Tuple[float, int]]] = {}

    for prob, outcome in pairs:
        # Determine which bin this probability falls into
        bin_idx = min(int(prob / bin_width), n_bins - 1)
        bin_low = round(bin_idx * bin_width, 2)
        bin_high = round((bin_idx + 1) * bin_width, 2)
        bin_label = f"{bin_low}-{bin_high}"

        if bin_label not in bins:
            bins[bin_label] = []
        bins[bin_label].append((prob, outcome))

    # Compute stats per bin
    result = {}
    for label, bin_pairs in sorted(bins.items()):
        predicted_avg = sum(p for p, _ in bin_pairs) / len(bin_pairs)
        actual_rate = sum(o for _, o in bin_pairs) / len(bin_pairs)
        result[label] = {
            "predicted_avg": round(predicted_avg, 4),
            "actual_rate": round(actual_rate, 4),
            "count": len(bin_pairs),
        }

    return result


# ============================================================================
# CLV (Closing Line Value)
# ============================================================================

def calculate_clv(bet_logs: List[Dict[str, Any]]) -> Optional[float]:
    """Calculate average Closing Line Value across all bets.

    CLV measures whether you consistently get better odds than the
    closing line (the final available odds before kickoff).

    CLV = (1/closing_odds) - (1/odds_at_placement)

    A **negative** CLV means you got better odds than closing (good!),
    because the implied probability you paid was lower than what the
    market settled at.

    **Why CLV matters:** In the long run, CLV is the single best
    predictor of profitability.  Even if short-term results are bad
    (due to variance), consistently beating the closing line means
    you're finding genuine value — and the profits will come.

    Parameters
    ----------
    bet_logs : list[dict]
        Bet history entries.  Only bets with both ``closing_odds``
        and ``odds_at_placement`` are included.

    Returns
    -------
    float or None
        Average CLV. None if no bets have closing odds data.
    """
    clv_values = []

    for b in bet_logs:
        closing = b.get("closing_odds")
        placement = b.get("odds_at_placement") or b.get("odds_at_detection")

        if closing and placement and closing > 1.0 and placement > 1.0:
            # CLV = implied_prob(closing) - implied_prob(placement)
            clv = (1.0 / closing) - (1.0 / placement)
            clv_values.append(clv)

    if not clv_values:
        return None

    return round(sum(clv_values) / len(clv_values), 6)


# ============================================================================
# Win Rate by Market Type
# ============================================================================

def _calculate_win_rates(
    bet_logs: List[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    """Calculate win rates by market type grouping.

    Returns win rates for 1X2, Over/Under (combined), and BTTS markets.
    Only includes resolved bets (won or lost).

    Returns
    -------
    dict
        Keys: win_rate_1x2, win_rate_ou, win_rate_btts.
        Values: float (0.0–1.0) or None if no bets in that market.
    """
    groups: Dict[str, List[bool]] = {
        "1x2": [],
        "ou": [],
        "btts": [],
    }

    for b in bet_logs:
        if b["status"] not in ("won", "lost"):
            continue

        won = b["status"] == "won"
        mt = b["market_type"]

        if mt == "1X2":
            groups["1x2"].append(won)
        elif mt in ("OU15", "OU25", "OU35"):
            groups["ou"].append(won)
        elif mt == "BTTS":
            groups["btts"].append(won)

    return {
        "win_rate_1x2": _safe_rate(groups["1x2"]),
        "win_rate_ou": _safe_rate(groups["ou"]),
        "win_rate_btts": _safe_rate(groups["btts"]),
    }


def _safe_rate(values: List[bool]) -> Optional[float]:
    """Calculate win rate from a list of booleans. None if empty."""
    if not values:
        return None
    return round(sum(values) / len(values), 4)


# ============================================================================
# Performance Report
# ============================================================================

def generate_performance_report(
    model_name: str,
    period_type: str,
    period_start: str,
    period_end: str,
) -> Dict[str, Any]:
    """Calculate all metrics for a model over a time period and store results.

    Gathers predictions and bet history for the specified period, computes
    all metrics (Brier score, ROI, CLV, calibration, win rates), and stores
    the results in the ``model_performance`` table.

    Parameters
    ----------
    model_name : str
        Name of the model to evaluate (e.g. "poisson_v1").
    period_type : str
        Period granularity: "daily", "weekly", "monthly", "season", "all_time".
    period_start : str
        Start date (inclusive) in ISO format.
    period_end : str
        End date (inclusive) in ISO format.

    Returns
    -------
    dict
        The performance report with all metrics.
    """
    # Gather predictions for this model in the date range
    predictions_data, actuals_data = _get_predictions_with_actuals(
        model_name, period_start, period_end,
    )

    # Gather bet logs for this period
    bet_logs = _get_bet_logs_for_period(period_start, period_end)

    # Calculate all metrics
    brier = calculate_brier_score(predictions_data, actuals_data)
    roi = calculate_roi(bet_logs)
    avg_clv = calculate_clv(bet_logs)
    calibration = calculate_calibration(predictions_data, actuals_data)
    win_rates = _calculate_win_rates(bet_logs)

    report = {
        "model_name": model_name,
        "period_type": period_type,
        "period_start": period_start,
        "period_end": period_end,
        "total_predictions": len(predictions_data),
        "brier_score": brier,
        "roi": roi,
        "avg_clv": avg_clv,
        "calibration": calibration,
        "win_rate_1x2": win_rates["win_rate_1x2"],
        "win_rate_ou": win_rates["win_rate_ou"],
        "win_rate_btts": win_rates["win_rate_btts"],
    }

    # Store in the model_performance table (upsert)
    _save_performance_report(report)

    logger.info(
        "generate_performance_report: %s %s %s→%s — "
        "brier=%.4f, roi=%.2f%%, predictions=%d",
        model_name, period_type, period_start, period_end,
        brier or 0, roi or 0, len(predictions_data),
    )

    return report


# ============================================================================
# Internal Helpers
# ============================================================================

def _get_predictions_with_actuals(
    model_name: str,
    date_from: str,
    date_to: str,
) -> Tuple[List[Dict[str, float]], List[Dict[str, int]]]:
    """Fetch predictions and their actual match results.

    Only includes matches that have been played (status='finished')
    so we can compare predictions to actuals.
    """
    predictions_data = []
    actuals_data = []

    with get_session() as session:
        # Join predictions with matches to get results
        rows = (
            session.query(Prediction, Match)
            .join(Match, Prediction.match_id == Match.id)
            .filter(
                Prediction.model_name == model_name,
                Match.date >= date_from,
                Match.date <= date_to,
                Match.status == "finished",
                Match.home_goals.isnot(None),
            )
            .order_by(Match.date)
            .all()
        )

        for pred, match in rows:
            predictions_data.append({
                "match_id": pred.match_id,
                "prob_home_win": pred.prob_home_win,
                "prob_draw": pred.prob_draw,
                "prob_away_win": pred.prob_away_win,
                "prob_over_25": pred.prob_over_25,
                "prob_under_25": pred.prob_under_25,
            })
            actuals_data.append({
                "match_id": match.id,
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
            })

    return predictions_data, actuals_data


def _get_bet_logs_for_period(
    date_from: str,
    date_to: str,
) -> List[Dict[str, Any]]:
    """Fetch resolved bet logs for a date range."""
    with get_session() as session:
        rows = (
            session.query(BetLog)
            .filter(
                BetLog.date >= date_from,
                BetLog.date <= date_to,
                BetLog.status.in_(["won", "lost", "void"]),
            )
            .all()
        )

        return [
            {
                "stake": r.stake,
                "pnl": r.pnl,
                "status": r.status,
                "market_type": r.market_type,
                "closing_odds": r.closing_odds,
                "odds_at_placement": r.odds_at_placement,
                "odds_at_detection": r.odds_at_detection,
            }
            for r in rows
        ]


def _save_performance_report(report: Dict[str, Any]) -> None:
    """Store a performance report in the model_performance table (upsert)."""
    with get_session() as session:
        existing = session.query(ModelPerformance).filter_by(
            model_name=report["model_name"],
            period_type=report["period_type"],
            period_start=report["period_start"],
        ).first()

        calibration_json = json.dumps(report["calibration"]) if report["calibration"] else None

        if existing:
            existing.period_end = report["period_end"]
            existing.total_predictions = report["total_predictions"]
            existing.brier_score = report["brier_score"]
            existing.roi = report["roi"]
            existing.avg_clv = report["avg_clv"]
            existing.calibration_json = calibration_json
            existing.win_rate_1x2 = report["win_rate_1x2"]
            existing.win_rate_ou = report["win_rate_ou"]
            existing.win_rate_btts = report["win_rate_btts"]
            logger.debug(
                "Updated model_performance for %s %s",
                report["model_name"], report["period_type"],
            )
        else:
            row = ModelPerformance(
                model_name=report["model_name"],
                period_type=report["period_type"],
                period_start=report["period_start"],
                period_end=report["period_end"],
                total_predictions=report["total_predictions"],
                brier_score=report["brier_score"],
                roi=report["roi"],
                avg_clv=report["avg_clv"],
                calibration_json=calibration_json,
                win_rate_1x2=report["win_rate_1x2"],
                win_rate_ou=report["win_rate_ou"],
                win_rate_btts=report["win_rate_btts"],
            )
            session.add(row)
            logger.debug(
                "Saved model_performance for %s %s",
                report["model_name"], report["period_type"],
            )
