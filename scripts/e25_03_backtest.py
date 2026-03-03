#!/usr/bin/env python3
"""
E25-03 — Walk-Forward Backtest: Poisson vs XGBoost vs Ensemble
===============================================================
Runs all 3 model configurations through the walk-forward backtester
on the 2024-25 EPL season (109 matchdays) with 5-season training data.

Outputs comparison table and saves results to:
  - ModelPerformance DB table (for Model Health dashboard)
  - data/e25_03_backtest_results.json (for audit trail)

Usage:
    python scripts/e25_03_backtest.py
"""

import json
import sys
import time
from pathlib import Path
from typing import List

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database.db import init_db
from src.evaluation.backtester import run_backtest, save_backtest_to_model_performance
from src.models.poisson import PoissonModel
from src.models.xgboost_model import XGBoostModel
from src.models.base_model import BaseModel, MatchPrediction, derive_market_probabilities

import numpy as np
import pandas as pd
from scipy.stats import poisson


# ============================================================================
# Ensemble Model Wrapper
# ============================================================================
# The backtester expects a model_class with train() and predict() methods.
# This wrapper trains both Poisson and XGBoost internally, then combines
# their scoreline matrices using equal weights (no adaptive weights yet —
# those require 300+ resolved predictions per model, which we don't have).

class EnsembleModel(BaseModel):
    """Ensemble wrapper that combines Poisson + XGBoost predictions.

    Each train() call trains both sub-models on the same data.
    Each predict() call generates predictions from both models, then
    combines their 7×7 scoreline matrices via weighted averaging.

    Weights: 50/50 (equal) for this initial comparison. In production,
    adaptive weights from ensemble_weights.py would be used after both
    models accumulate 300+ resolved predictions.
    """

    @property
    def name(self) -> str:
        return "ensemble_v1"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self) -> None:
        self._poisson = PoissonModel()
        self._xgboost = XGBoostModel()
        self._poisson_weight = 0.5
        self._xgboost_weight = 0.5
        self._is_trained = False

    def train(self, features: pd.DataFrame, results: pd.DataFrame) -> None:
        """Train both sub-models on the same data."""
        self._poisson.train(features, results)
        self._xgboost.train(features, results)
        self._is_trained = True

    def predict(self, features: pd.DataFrame) -> List[MatchPrediction]:
        """Generate ensemble predictions by combining scoreline matrices."""
        if not self._is_trained:
            raise RuntimeError("Model not trained — call train() first")

        poisson_preds = self._poisson.predict(features)
        xgboost_preds = self._xgboost.predict(features)

        # Build lookup by match_id for safe matching
        xgb_by_match = {p.match_id: p for p in xgboost_preds}

        ensemble_preds = []
        for pp in poisson_preds:
            xp = xgb_by_match.get(pp.match_id)
            if xp is None:
                # If XGBoost didn't produce a prediction, use Poisson only
                ensemble_preds.append(pp)
                continue

            # Combine scoreline matrices (weighted average)
            combined_matrix = []
            for h in range(7):
                row = []
                for a in range(7):
                    val = (
                        self._poisson_weight * pp.scoreline_matrix[h][a]
                        + self._xgboost_weight * xp.scoreline_matrix[h][a]
                    )
                    row.append(val)
                combined_matrix.append(row)

            # Renormalise to sum to 1.0
            total = sum(sum(row) for row in combined_matrix)
            if total > 0:
                combined_matrix = [
                    [p / total for p in row]
                    for row in combined_matrix
                ]

            # Combined expected goals (weighted average)
            combined_home = (
                self._poisson_weight * pp.predicted_home_goals
                + self._xgboost_weight * xp.predicted_home_goals
            )
            combined_away = (
                self._poisson_weight * pp.predicted_away_goals
                + self._xgboost_weight * xp.predicted_away_goals
            )

            # Derive all market probabilities from the combined matrix
            market_probs = derive_market_probabilities(combined_matrix)

            pred = MatchPrediction(
                match_id=pp.match_id,
                model_name=self.name,
                model_version=self.version,
                predicted_home_goals=round(combined_home, 4),
                predicted_away_goals=round(combined_away, 4),
                scoreline_matrix=combined_matrix,
                **market_probs,
            )
            ensemble_preds.append(pred)

        return ensemble_preds

    def save(self, path: Path) -> None:
        raise NotImplementedError("Ensemble save not needed for backtesting")

    def load(self, path: Path) -> None:
        raise NotImplementedError("Ensemble load not needed for backtesting")


# ============================================================================
# Main
# ============================================================================

def main():
    init_db()

    # Configuration
    league_id = 1  # EPL
    eval_season = "2024-25"
    training_seasons = ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]
    edge_threshold = 0.05

    configs = [
        ("Poisson-only", PoissonModel, "poisson_v1"),
        ("XGBoost-only", XGBoostModel, "xgboost_v1"),
        ("Ensemble (50/50)", EnsembleModel, "ensemble_v1"),
    ]

    print("=" * 70)
    print("E25-03: Walk-Forward Backtest — Poisson vs XGBoost vs Ensemble")
    print("=" * 70)
    print(f"Evaluation season: {eval_season}")
    print(f"Training seasons: {', '.join(training_seasons)}")
    print(f"Edge threshold: {int(edge_threshold * 100)}%")
    print()

    results = {}

    for config_name, model_class, model_key in configs:
        print("=" * 70)
        print(f"CONFIG: {config_name.upper()}")
        print("=" * 70)

        start = time.time()

        try:
            result = run_backtest(
                league_id=league_id,
                season=eval_season,
                model_class=model_class,
                edge_threshold=edge_threshold,
                staking_method="flat",
                stake_percentage=0.02,
                starting_bankroll=1000.0,
                training_seasons=training_seasons,
            )

            elapsed = time.time() - start

            # Save to ModelPerformance table
            save_backtest_to_model_performance(
                result=result,
                season=eval_season,
                model_name=model_key,
                training_seasons=training_seasons,
            )

            results[config_name] = {
                "model_key": model_key,
                "brier": result.brier_score,
                "roi": result.roi,
                "total_predicted": result.total_predicted,
                "total_value_bets": result.total_value_bets,
                "total_staked": result.total_staked,
                "total_pnl": result.total_pnl,
                "final_bankroll": 1000.0 + result.total_pnl,
                "time_seconds": round(elapsed, 1),
                "calibration": result.calibration_data,
                "max_drawdown": _calc_max_drawdown(result.daily_pnl_series),
                "win_rate_1x2": _calc_market_win_rate(result.bet_details, ["1X2"]),
                "win_rate_ou": _calc_market_win_rate(result.bet_details, ["OU25", "OU15", "OU35"]),
                "win_rate_btts": _calc_market_win_rate(result.bet_details, ["BTTS"]),
            }

            print(f"\n  ✅ {config_name} complete in {elapsed:.1f}s")
            print()

        except Exception as e:
            print(f"\n  ❌ {config_name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            results[config_name] = {"error": str(e)}
            print()

    # ====================================================================
    # COMPARISON TABLE
    # ====================================================================
    print("\n" + "=" * 70)
    print("COMPARISON TABLE")
    print("=" * 70)
    print()

    # Header
    header = f"{'Metric':<25}"
    for name in results:
        header += f"{'|':>3} {name:<20}"
    print(header)
    print("-" * len(header))

    # Rows
    metrics = [
        ("Brier Score", "brier", ".4f", True),
        ("ROI (%)", "roi", ".2f", False),
        ("Total PnL (£)", "total_pnl", "+.2f", False),
        ("Final Bankroll (£)", "final_bankroll", ".2f", False),
        ("Value Bets", "total_value_bets", "d", False),
        ("Total Staked (£)", "total_staked", ".2f", False),
        ("Max Drawdown (%)", "max_drawdown", ".1f", True),
        ("Win Rate 1X2 (%)", "win_rate_1x2", ".1f", False),
        ("Win Rate O/U (%)", "win_rate_ou", ".1f", False),
        ("Win Rate BTTS (%)", "win_rate_btts", ".1f", False),
        ("Matches Predicted", "total_predicted", "d", False),
        ("Time (s)", "time_seconds", ".1f", True),
    ]

    for label, key, fmt, lower_better in metrics:
        row = f"{label:<25}"
        values = []
        for name in results:
            r = results[name]
            if "error" in r:
                row += f"{'|':>3} {'ERROR':<20}"
                values.append(None)
            else:
                val = r.get(key)
                if val is None:
                    row += f"{'|':>3} {'N/A':<20}"
                    values.append(None)
                else:
                    row += f"{'|':>3} {format(val, fmt):<20}"
                    values.append(val)
        # Mark best
        valid = [(i, v) for i, v in enumerate(values) if v is not None]
        if valid and key not in ("time_seconds", "total_predicted"):
            if lower_better:
                best_idx = min(valid, key=lambda x: x[1])[0]
            else:
                best_idx = max(valid, key=lambda x: x[1])[0]
            row += f"  ← {'best' if key != 'max_drawdown' else 'best'}"

        print(row)

    # ====================================================================
    # WINNER IDENTIFICATION
    # ====================================================================
    print()
    print("=" * 70)
    print("WINNER ANALYSIS")
    print("=" * 70)

    valid_results = {k: v for k, v in results.items() if "error" not in v}
    if valid_results:
        # Primary criterion: Brier score (lower = better prediction quality)
        by_brier = sorted(valid_results.items(), key=lambda x: x[1]["brier"] or 99)
        # Secondary criterion: ROI (higher = better profitability)
        by_roi = sorted(valid_results.items(), key=lambda x: -(x[1]["roi"] or -99))

        print(f"\n  By Brier Score (prediction quality):")
        for i, (name, r) in enumerate(by_brier):
            marker = " 🏆" if i == 0 else ""
            print(f"    {i+1}. {name}: {r['brier']:.4f}{marker}")

        print(f"\n  By ROI (profitability):")
        for i, (name, r) in enumerate(by_roi):
            marker = " 🏆" if i == 0 else ""
            print(f"    {i+1}. {name}: {r['roi']:.2f}%{marker}")

        # Overall winner: best Brier (primary) with ROI tiebreak
        winner_name = by_brier[0][0]
        winner = by_brier[0][1]
        print(f"\n  OVERALL WINNER: {winner_name}")
        print(f"    Brier: {winner['brier']:.4f}, ROI: {winner['roi']:.2f}%, PnL: £{winner['total_pnl']:+.2f}")

    # ====================================================================
    # SAVE RESULTS
    # ====================================================================
    output_path = Path("data/e25_03_backtest_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert calibration data for JSON serialization
    serializable = {}
    for name, r in results.items():
        if "error" in r:
            serializable[name] = r
        else:
            sr = dict(r)
            # calibration might have non-serializable types
            if sr.get("calibration"):
                sr["calibration"] = str(sr["calibration"])
            serializable[name] = sr

    with open(output_path, "w") as f:
        json.dump(serializable, f, indent=2)

    print(f"\n  Results saved to {output_path}")
    print("\n" + "=" * 70)
    print("E25-03 BACKTEST COMPLETE")
    print("=" * 70)


def _calc_max_drawdown(daily_pnl_series: list) -> float:
    """Calculate maximum drawdown as a percentage from peak bankroll."""
    if not daily_pnl_series:
        return 0.0

    peak = 0.0
    max_dd = 0.0
    for day in daily_pnl_series:
        bankroll = day.get("bankroll", 1000.0)
        if bankroll > peak:
            peak = bankroll
        dd = (peak - bankroll) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return round(max_dd, 1)


def _calc_market_win_rate(bet_details: list, market_types: list) -> float:
    """Calculate win rate for specific market types."""
    bets = [b for b in bet_details if b.get("market_type") in market_types]
    if not bets:
        return 0.0
    wins = sum(1 for b in bets if b["status"] == "won")
    return round(wins / len(bets) * 100, 1)


if __name__ == "__main__":
    main()
