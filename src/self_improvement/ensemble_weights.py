"""
BetVector — Adaptive Ensemble Weights (E12-03)
================================================
Dynamically adjusts how much weight each prediction model gets in the
ensemble based on recent performance.  A model that's been more accurate
recently gets more weight.

Weight calculation: inverse Brier score weighting.  Each model's weight
is proportional to ``1 / Brier_score``, normalised so all weights sum
to 1.0.  Lower Brier score = better calibrated predictions = higher weight.

Brier score (MP §12 Glossary):
  The mean squared error of probability predictions.  For a 1X2 market
  prediction, Brier = mean of [(prob_home - actual_home)^2 +
  (prob_draw - actual_draw)^2 + (prob_away - actual_away)^2].
  Lower = better.  0.0 = perfect, 0.25 = coin flip, > 0.25 = worse than guessing.

Guardrails (MP §11.3):
- Min 300 resolved predictions per model before adaptive weighting activates
- Weights evaluated over a rolling window of the last 300 predictions
- Max ±10 percentage points change per recalculation
- Weight floor: 10% (no model drops below)
- Weight ceiling: 60% (no model exceeds)
- Smoothing: new_weight = 0.7 × calculated + 0.3 × previous

Master Plan refs: MP §11.3 Adaptive Ensemble Weights
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from src.config import config
from src.database.db import get_session
from src.database.models import (
    EnsembleWeightHistory,
    Match,
    Prediction,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Public API
# ============================================================================

def get_current_weights(model_names: List[str]) -> Dict[str, float]:
    """Get current ensemble weights for the given models.

    Returns the latest weights from the database.  If no weights have been
    calculated yet (or only one model is active), returns equal weights.

    Single-model graceful degradation: if only one model is active, its
    weight is 1.0.  The ensemble effectively becomes a single model.

    Parameters
    ----------
    model_names : list of str
        Active model names (e.g. ["poisson_v1", "xgboost_v1"]).

    Returns
    -------
    dict
        Mapping of model_name → weight.  Always sums to 1.0.
    """
    if not model_names:
        return {}

    # Single model: weight is always 1.0
    if len(model_names) == 1:
        return {model_names[0]: 1.0}

    # Try to get the latest weights from the database
    weights = _get_latest_weights_from_db(model_names)

    if weights:
        # Ensure all requested models are present (new models get equal share)
        missing = [m for m in model_names if m not in weights]
        if missing:
            # Redistribute: give missing models equal share of remaining
            existing_total = sum(weights.values())
            share = (1.0 - existing_total) / len(missing) if existing_total < 1.0 else 1.0 / len(model_names)
            for m in missing:
                weights[m] = share
            # Renormalise
            total = sum(weights.values())
            weights = {m: w / total for m, w in weights.items()}
        return weights

    # No weights in DB yet: equal weights
    equal = 1.0 / len(model_names)
    return {m: equal for m in model_names}


def recalculate_weights(model_names: List[str]) -> Optional[Dict[str, float]]:
    """Recalculate ensemble weights based on recent Brier scores.

    Triggered every 100 resolved ensemble predictions (checked by the
    pipeline).  Computes inverse Brier score weights, applies guardrails,
    and stores the result in ``ensemble_weight_history``.

    Parameters
    ----------
    model_names : list of str
        Active model names to weight.

    Returns
    -------
    dict or None
        New weights if recalculation was performed, None if skipped
        (insufficient data or only one model).
    """
    if len(model_names) <= 1:
        print("  → Only one model active, no ensemble weighting needed")
        return None

    aw_cfg = config.settings.self_improvement.adaptive_weights
    min_samples = aw_cfg.min_sample_size       # 300
    eval_window = aw_cfg.evaluation_window     # 300
    max_change = aw_cfg.max_weight_change      # 0.10
    floor = aw_cfg.weight_floor                # 0.10
    ceiling = aw_cfg.weight_ceiling            # 0.60

    # Step 1: Check minimum sample size per model
    for model_name in model_names:
        count = _count_resolved_predictions(model_name)
        if count < min_samples:
            print(f"  → {model_name} has {count} resolved predictions "
                  f"(need {min_samples}), skipping weight recalculation")
            return None

    # Step 2: Compute Brier score per model over the evaluation window
    brier_scores = {}
    for model_name in model_names:
        brier = _compute_brier_score(model_name, eval_window)
        if brier is None or brier <= 0:
            print(f"  → Could not compute Brier score for {model_name}")
            return None
        brier_scores[model_name] = brier
        print(f"  → {model_name}: Brier score = {brier:.4f}")

    # Step 3: Calculate inverse Brier weights
    # Weight ∝ 1/Brier — lower Brier (better) = higher weight
    inv_brier = {m: 1.0 / b for m, b in brier_scores.items()}
    total_inv = sum(inv_brier.values())
    raw_weights = {m: v / total_inv for m, v in inv_brier.items()}

    # Step 4: Apply smoothing with previous weights
    # new_weight = 0.7 × calculated + 0.3 × previous
    previous = get_current_weights(model_names)
    smoothed = {}
    for m in model_names:
        calc = raw_weights.get(m, 1.0 / len(model_names))
        prev = previous.get(m, 1.0 / len(model_names))
        smoothed[m] = 0.7 * calc + 0.3 * prev

    # Renormalise after smoothing
    total = sum(smoothed.values())
    smoothed = {m: w / total for m, w in smoothed.items()}

    # Step 5: Apply max change guardrail (±10pp from previous)
    clamped = {}
    for m in model_names:
        prev = previous.get(m, 1.0 / len(model_names))
        new_w = smoothed[m]
        # Clamp to ±max_change from previous
        clamped[m] = max(prev - max_change, min(prev + max_change, new_w))

    # Step 6: Apply floor and ceiling
    for m in clamped:
        clamped[m] = max(floor, min(ceiling, clamped[m]))

    # Renormalise after clamping (floor/ceiling may have broken sum=1)
    total = sum(clamped.values())
    final_weights = {m: w / total for m, w in clamped.items()}

    # Step 7: Store in ensemble_weight_history
    _store_weights(
        model_names=model_names,
        weights=final_weights,
        brier_scores=brier_scores,
        previous_weights=previous,
        eval_window=eval_window,
    )

    for m, w in final_weights.items():
        prev = previous.get(m, 1.0 / len(model_names))
        change = w - prev
        direction = "+" if change >= 0 else ""
        print(f"  → {m}: {prev:.1%} → {w:.1%} ({direction}{change:.1%})")

    return final_weights


def should_recalculate(model_names: List[str]) -> bool:
    """Check if it's time to recalculate ensemble weights.

    Weights are recalculated every 100 resolved ensemble predictions.
    This function counts resolved predictions since the last weight
    recalculation and returns True if the threshold is met.

    Parameters
    ----------
    model_names : list of str
        Active model names.

    Returns
    -------
    bool
        True if recalculation is due.
    """
    if len(model_names) <= 1:
        return False

    # Get the date of the last weight recalculation
    with get_session() as session:
        latest = (
            session.query(EnsembleWeightHistory.created_at)
            .order_by(EnsembleWeightHistory.created_at.desc())
            .first()
        )

    since_date = latest[0] if latest else None

    # Count resolved predictions since last recalculation
    # Use the first model as proxy — all models predict the same matches
    total = _count_resolved_predictions(model_names[0], since_date)

    return total >= 100


# ============================================================================
# Internal helpers
# ============================================================================

def _count_resolved_predictions(
    model_name: str,
    since_date: Optional[str] = None,
) -> int:
    """Count resolved predictions for a model, optionally since a date."""
    with get_session() as session:
        query = (
            session.query(Prediction)
            .join(Match, Prediction.match_id == Match.id)
            .filter(
                Prediction.model_name == model_name,
                Match.status == "finished",
                Match.home_goals.isnot(None),
            )
        )
        if since_date:
            query = query.filter(Prediction.created_at > since_date)
        return query.count()


def _compute_brier_score(
    model_name: str,
    window: int,
) -> Optional[float]:
    """Compute Brier score for a model over the last N resolved predictions.

    Uses the 1X2 market (home win, draw, away win) for multi-class Brier:
      Brier = mean of [(p_home - y_home)^2 + (p_draw - y_draw)^2 +
                        (p_away - y_away)^2]

    Lower = better.  0.0 = perfect, 0.25 = useless coin-flip.

    Parameters
    ----------
    model_name : str
        Model to evaluate.
    window : int
        Number of most recent resolved predictions to use.

    Returns
    -------
    float or None
        Brier score, or None if insufficient data.
    """
    with get_session() as session:
        rows = (
            session.query(
                Prediction.prob_home_win,
                Prediction.prob_draw,
                Prediction.prob_away_win,
                Match.home_goals,
                Match.away_goals,
            )
            .join(Match, Prediction.match_id == Match.id)
            .filter(
                Prediction.model_name == model_name,
                Match.status == "finished",
                Match.home_goals.isnot(None),
            )
            .order_by(Prediction.created_at.desc())
            .limit(window)
            .all()
        )

    if not rows:
        return None

    brier_sum = 0.0
    for p_home, p_draw, p_away, h_goals, a_goals in rows:
        # Actual outcome as one-hot
        y_home = 1.0 if h_goals > a_goals else 0.0
        y_draw = 1.0 if h_goals == a_goals else 0.0
        y_away = 1.0 if h_goals < a_goals else 0.0

        brier_sum += (
            (p_home - y_home) ** 2
            + (p_draw - y_draw) ** 2
            + (p_away - y_away) ** 2
        )

    return brier_sum / len(rows)


def _get_latest_weights_from_db(
    model_names: List[str],
) -> Optional[Dict[str, float]]:
    """Get the most recent weights from ensemble_weight_history.

    Returns None if no weights have been stored yet.
    """
    with get_session() as session:
        # Get the latest created_at timestamp
        latest_ts = (
            session.query(EnsembleWeightHistory.created_at)
            .order_by(EnsembleWeightHistory.created_at.desc())
            .first()
        )
        if not latest_ts:
            return None

        # Get all weights from that timestamp
        entries = (
            session.query(EnsembleWeightHistory)
            .filter(EnsembleWeightHistory.created_at == latest_ts[0])
            .all()
        )

    if not entries:
        return None

    weights = {e.model_name: e.weight for e in entries}

    # Only return if we have weights for all requested models
    if all(m in weights for m in model_names):
        return weights

    return None


def _store_weights(
    model_names: List[str],
    weights: Dict[str, float],
    brier_scores: Dict[str, float],
    previous_weights: Dict[str, float],
    eval_window: int,
) -> None:
    """Store weight recalculation results in ensemble_weight_history."""
    with get_session() as session:
        for model_name in model_names:
            entry = EnsembleWeightHistory(
                model_name=model_name,
                weight=round(weights[model_name], 6),
                brier_score=round(brier_scores[model_name], 6),
                evaluation_window=eval_window,
                previous_weight=round(
                    previous_weights.get(model_name, 1.0 / len(model_names)), 6,
                ),
                reason=(
                    f"Inverse Brier weighting over {eval_window} predictions. "
                    f"Brier={brier_scores[model_name]:.4f}, "
                    f"prev={previous_weights.get(model_name, 0):.4f}, "
                    f"new={weights[model_name]:.4f}"
                ),
            )
            session.add(entry)

        logger.info(
            "Stored ensemble weights for %d models: %s",
            len(model_names),
            {m: f"{w:.3f}" for m, w in weights.items()},
        )
