"""
BetVector — Automatic Recalibration (E12-01)
=============================================
Monitors whether predicted probabilities match actual outcomes and applies
statistical corrections when drift is detected.

If the model's "70% predictions" are only winning 60% of the time, this
module fits Platt scaling (logistic regression on probabilities) or isotonic
regression to bring predicted probabilities back in line with reality.

Calibration works by pooling ALL probability-outcome pairs from resolved
predictions — 1X2, Over/Under, and BTTS markets — giving a large sample
for robust calibration fitting.

Guardrails (MP §11.1):
- Minimum 200 resolved predictions before any recalibration
- Only recalibrates if mean absolute calibration error > 3 percentage points
- Rollback after 100 post-calibration predictions if performance worsens
- Always stores both raw and calibrated error for transparency
- Previous calibration is deactivated when a new one is applied

Master Plan refs: MP §11.1 Automatic Recalibration
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from src.config import config
from src.database.db import get_session
from src.database.models import (
    CalibrationHistory,
    Match,
    Prediction,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Market outcome helpers
# ============================================================================
# These map each predicted probability field to a function that computes the
# actual binary outcome (1 or 0) from the match result.  We pool ALL markets
# together to maximise the calibration sample size.

# Probability field → lambda(home_goals, away_goals) → 0 or 1
PROB_OUTCOME_MAP = {
    "prob_home_win": lambda h, a: int(h > a),
    "prob_draw": lambda h, a: int(h == a),
    "prob_away_win": lambda h, a: int(a > h),
    "prob_over_25": lambda h, a: int(h + a > 2),
    "prob_under_25": lambda h, a: int(h + a <= 2),
    "prob_over_15": lambda h, a: int(h + a > 1),
    "prob_under_15": lambda h, a: int(h + a <= 1),
    "prob_over_35": lambda h, a: int(h + a > 3),
    "prob_under_35": lambda h, a: int(h + a <= 3),
    "prob_btts_yes": lambda h, a: int(h > 0 and a > 0),
    "prob_btts_no": lambda h, a: int(h == 0 or a == 0),
}


# ============================================================================
# Public API
# ============================================================================

def check_and_recalibrate(model_name: str) -> Optional[CalibrationHistory]:
    """Check if recalibration is needed and apply it if so.

    Called from the evening pipeline after bets are resolved.  This is the
    main entry point for the automatic recalibration system.

    Steps:
    1. Count resolved predictions since the last calibration event
    2. If count < min_sample_size (200): skip — not enough data
    3. Gather all probability-outcome pairs from resolved predictions
    4. Compute mean absolute calibration error (MAE across bins)
    5. If MAE < threshold (0.03): skip — calibration is good enough
    6. Fit both Platt scaling and isotonic regression; pick the better one
    7. Deactivate any previously active calibration for this model
    8. Store new calibration in calibration_history with is_active=1

    Parameters
    ----------
    model_name : str
        The model to check (e.g. "poisson_v1").

    Returns
    -------
    CalibrationHistory or None
        The new calibration record if recalibration was triggered, else None.
    """
    recal_cfg = config.settings.self_improvement.recalibration
    min_samples = recal_cfg.min_sample_size       # 200
    error_threshold = recal_cfg.calibration_error_threshold  # 0.03

    # Step 1: Count resolved predictions since last calibration
    last_cal = get_active_calibration(model_name)
    since_date = last_cal.created_at if last_cal else None

    pred_count = _count_resolved_predictions(model_name, since_date)
    print(f"  → {pred_count} resolved predictions since last calibration")

    # Step 2: Check minimum sample size
    if pred_count < min_samples:
        print(f"  → Below minimum sample size ({pred_count} < {min_samples}), "
              f"skipping recalibration")
        return None

    # Step 3: Gather probability-outcome pairs
    predicted, actual = _gather_calibration_data(model_name, since_date)
    if len(predicted) == 0:
        print("  → No calibration data available, skipping")
        return None

    # Step 4: Compute calibration error
    mae_before = _compute_calibration_error(predicted, actual)
    print(f"  → Current calibration error (MAE): {mae_before:.4f}")

    # Step 5: Check error threshold
    if mae_before <= error_threshold:
        print(f"  → Below threshold ({mae_before:.4f} <= {error_threshold}), "
              f"no recalibration needed")
        return None

    # Step 6: Fit calibrators and pick the best
    print(f"  → Calibration error {mae_before:.4f} exceeds threshold "
          f"{error_threshold}, fitting calibrators...")

    best_method = None
    best_params = None
    best_mae_after = mae_before  # Must improve to be accepted

    for method in recal_cfg.calibration_methods:
        try:
            params = _fit_calibration(method, predicted, actual)
            calibrated = _apply_calibration_transform(method, params, predicted)
            mae_after = _compute_calibration_error(calibrated, actual)
            print(f"    → {method}: MAE {mae_before:.4f} → {mae_after:.4f}")

            if mae_after < best_mae_after:
                best_method = method
                best_params = params
                best_mae_after = mae_after
        except Exception as e:
            logger.warning("Calibration method '%s' failed: %s", method, e)
            print(f"    → {method}: FAILED ({e})")

    if best_method is None:
        print("  → No calibration method improved error, skipping")
        return None

    # Step 7 & 8: Deactivate old calibration and store new one
    print(f"  → Applying {best_method} calibration "
          f"(MAE {mae_before:.4f} → {best_mae_after:.4f})")

    cal_record = _store_calibration(
        model_name=model_name,
        method=best_method,
        params=best_params,
        sample_size=len(predicted),
        mae_before=mae_before,
        mae_after=best_mae_after,
    )

    return cal_record


def check_rollback(model_name: str) -> bool:
    """Check if the active calibration should be rolled back.

    After rollback_window (100) resolved predictions since the calibration
    was applied, compare the calibration error with calibration applied vs
    without it (raw model probabilities).  If calibrated error is worse
    than raw error, roll back the calibration.

    Parameters
    ----------
    model_name : str
        The model to check.

    Returns
    -------
    bool
        True if a rollback was performed, False otherwise.
    """
    active_cal = get_active_calibration(model_name)
    if active_cal is None:
        return False  # Nothing to roll back

    recal_cfg = config.settings.self_improvement.recalibration
    rollback_window = recal_cfg.rollback_window  # 100

    # Count resolved predictions since this calibration was created
    post_cal_count = _count_resolved_predictions(
        model_name, active_cal.created_at,
    )

    if post_cal_count < rollback_window:
        # Not enough data to evaluate yet
        return False

    print(f"  → Evaluating rollback: {post_cal_count} predictions since "
          f"calibration (threshold: {rollback_window})")

    # Gather post-calibration data
    predicted, actual = _gather_calibration_data(
        model_name, active_cal.created_at,
    )
    if len(predicted) == 0:
        return False

    # Compute raw error (without calibration)
    raw_mae = _compute_calibration_error(predicted, actual)

    # Compute calibrated error
    params = json.loads(active_cal.parameters_json)
    calibrated = _apply_calibration_transform(
        active_cal.calibration_method, params, predicted,
    )
    calibrated_mae = _compute_calibration_error(calibrated, actual)

    print(f"  → Raw MAE: {raw_mae:.4f}, Calibrated MAE: {calibrated_mae:.4f}")

    if calibrated_mae >= raw_mae:
        # Calibration is making things worse — roll back
        print(f"  → Rolling back calibration (calibrated {calibrated_mae:.4f} "
              f">= raw {raw_mae:.4f})")
        _rollback_calibration(active_cal)
        return True

    print(f"  → Calibration is helping (calibrated {calibrated_mae:.4f} "
          f"< raw {raw_mae:.4f}), keeping it")
    return False


def apply_calibration(
    model_name: str,
    raw_probs: Dict[str, float],
) -> Dict[str, float]:
    """Apply the active calibration to a set of raw probabilities.

    If no active calibration exists for the model, returns raw_probs
    unchanged.  After transformation, complementary probabilities are
    renormalised so they sum to 1.0 within each market group.

    Parameters
    ----------
    model_name : str
        The model whose calibration to apply.
    raw_probs : dict
        Dictionary of probability field names to raw values, e.g.
        {"prob_home_win": 0.65, "prob_draw": 0.20, "prob_away_win": 0.15}.

    Returns
    -------
    dict
        Calibrated probabilities (or raw if no calibration is active).
    """
    active_cal = get_active_calibration(model_name)
    if active_cal is None:
        return raw_probs

    params = json.loads(active_cal.parameters_json)
    method = active_cal.calibration_method

    # Apply calibration to each probability individually
    calibrated = {}
    for field, raw_val in raw_probs.items():
        if field in PROB_OUTCOME_MAP:
            arr = np.array([raw_val])
            transformed = _apply_calibration_transform(method, params, arr)
            calibrated[field] = float(np.clip(transformed[0], 0.001, 0.999))
        else:
            calibrated[field] = raw_val

    # Renormalise within each market group so complementary probs sum to 1.0
    calibrated = _renormalise_market_groups(calibrated)
    return calibrated


def get_active_calibration(model_name: str) -> Optional[CalibrationHistory]:
    """Get the currently active calibration for a model.

    Returns the most recent calibration with is_active=1.
    """
    with get_session() as session:
        cal = (
            session.query(CalibrationHistory)
            .filter(
                CalibrationHistory.model_name == model_name,
                CalibrationHistory.is_active == 1,
                CalibrationHistory.rolled_back == 0,
            )
            .order_by(CalibrationHistory.created_at.desc())
            .first()
        )
        if cal:
            # Detach from session so it can be used outside
            session.expunge(cal)
        return cal


# ============================================================================
# Internal helpers
# ============================================================================

def _count_resolved_predictions(
    model_name: str,
    since_date: Optional[str] = None,
) -> int:
    """Count resolved predictions (match is finished) since a given date.

    If since_date is None, counts all resolved predictions for this model.
    """
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


def _gather_calibration_data(
    model_name: str,
    since_date: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Gather all probability-outcome pairs from resolved predictions.

    Pools predictions across all markets (1X2, O/U, BTTS) to maximise
    the calibration sample size.  Each resolved prediction contributes
    11 probability-outcome pairs (one per market probability field).

    Returns
    -------
    predicted : np.ndarray
        1D array of predicted probabilities.
    actual : np.ndarray
        1D array of actual binary outcomes (0 or 1).
    """
    with get_session() as session:
        query = (
            session.query(
                Prediction, Match.home_goals, Match.away_goals,
            )
            .join(Match, Prediction.match_id == Match.id)
            .filter(
                Prediction.model_name == model_name,
                Match.status == "finished",
                Match.home_goals.isnot(None),
            )
        )
        if since_date:
            query = query.filter(Prediction.created_at > since_date)

        rows = query.all()

    if not rows:
        return np.array([]), np.array([])

    predicted_list: List[float] = []
    actual_list: List[int] = []

    for pred, home_goals, away_goals in rows:
        for field, outcome_fn in PROB_OUTCOME_MAP.items():
            prob_val = getattr(pred, field, None)
            if prob_val is not None:
                predicted_list.append(prob_val)
                actual_list.append(outcome_fn(home_goals, away_goals))

    return np.array(predicted_list), np.array(actual_list)


def _compute_calibration_error(
    predicted: np.ndarray,
    actual: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Compute mean absolute calibration error across probability bins.

    Splits predictions into n_bins equal-width bins from 0 to 1.  In each
    bin, compares the mean predicted probability to the actual outcome
    frequency.  Returns the mean of |predicted_mean - actual_frequency|
    across all non-empty bins.

    This measures how well-calibrated the model's probabilities are:
    - 0.0 = perfectly calibrated (predicted = actual frequency)
    - 0.25 = very poorly calibrated

    Parameters
    ----------
    predicted : np.ndarray
        Predicted probabilities.
    actual : np.ndarray
        Actual binary outcomes (0 or 1).
    n_bins : int
        Number of bins for calibration curve.

    Returns
    -------
    float
        Mean absolute calibration error.
    """
    if len(predicted) == 0:
        return 0.0

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    total_error = 0.0
    n_used = 0

    for i in range(n_bins):
        if i < n_bins - 1:
            mask = (predicted >= bins[i]) & (predicted < bins[i + 1])
        else:
            # Last bin includes the right edge (1.0)
            mask = (predicted >= bins[i]) & (predicted <= bins[i + 1])

        if mask.sum() > 0:
            mean_predicted = predicted[mask].mean()
            mean_actual = actual[mask].mean()
            total_error += abs(mean_predicted - mean_actual)
            n_used += 1

    return total_error / n_used if n_used > 0 else 0.0


def _fit_calibration(
    method: str,
    predicted: np.ndarray,
    actual: np.ndarray,
) -> dict:
    """Fit a calibration function to probability-outcome data.

    Parameters
    ----------
    method : str
        "platt" for Platt scaling (logistic regression on probabilities)
        or "isotonic" for isotonic regression.
    predicted : np.ndarray
        Predicted probabilities.
    actual : np.ndarray
        Actual binary outcomes.

    Returns
    -------
    dict
        Serialisable parameters for the calibration function.
    """
    if method == "platt":
        # Platt scaling: fit a logistic regression y = sigmoid(a*x + b)
        # where x is the raw probability and y is the calibrated probability.
        lr = LogisticRegression(solver="lbfgs", max_iter=1000)
        lr.fit(predicted.reshape(-1, 1), actual)
        return {
            "coef": float(lr.coef_[0][0]),
            "intercept": float(lr.intercept_[0]),
        }

    elif method == "isotonic":
        # Isotonic regression: non-parametric monotonic calibration.
        # Stores the piecewise-linear function as threshold arrays.
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(predicted, actual)
        return {
            "x_thresholds": ir.X_thresholds_.tolist(),
            "y_thresholds": ir.y_thresholds_.tolist(),
        }

    else:
        raise ValueError(f"Unknown calibration method: {method}")


def _apply_calibration_transform(
    method: str,
    params: dict,
    predicted: np.ndarray,
) -> np.ndarray:
    """Apply a calibration transformation to predicted probabilities.

    Parameters
    ----------
    method : str
        "platt" or "isotonic".
    params : dict
        Parameters from _fit_calibration().
    predicted : np.ndarray
        Raw predicted probabilities to transform.

    Returns
    -------
    np.ndarray
        Calibrated probabilities.
    """
    if method == "platt":
        # Apply logistic function: P(y=1) = 1 / (1 + exp(-(a*x + b)))
        coef = params["coef"]
        intercept = params["intercept"]
        logits = coef * predicted + intercept
        calibrated = 1.0 / (1.0 + np.exp(-logits))
        return np.clip(calibrated, 0.001, 0.999)

    elif method == "isotonic":
        # Reconstruct isotonic regression and transform
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.X_thresholds_ = np.array(params["x_thresholds"])
        ir.y_thresholds_ = np.array(params["y_thresholds"])
        ir.X_min_ = ir.X_thresholds_[0]
        ir.X_max_ = ir.X_thresholds_[-1]
        ir.f_ = None  # Will be rebuilt on first transform
        # Manual piecewise linear interpolation (more reliable than
        # relying on sklearn's internal state reconstruction)
        calibrated = np.interp(
            predicted,
            ir.X_thresholds_,
            ir.y_thresholds_,
        )
        return np.clip(calibrated, 0.001, 0.999)

    else:
        raise ValueError(f"Unknown calibration method: {method}")


def _renormalise_market_groups(probs: Dict[str, float]) -> Dict[str, float]:
    """Renormalise calibrated probabilities within each market group.

    After calibration, complementary probabilities may no longer sum to 1.0.
    This function renormalises them within each group:
    - 1X2: home_win + draw + away_win = 1.0
    - OU25: over_25 + under_25 = 1.0
    - OU15: over_15 + under_15 = 1.0
    - OU35: over_35 + under_35 = 1.0
    - BTTS: btts_yes + btts_no = 1.0
    """
    result = dict(probs)

    # Market groups: list of (field_1, field_2, ...) that must sum to 1.0
    groups = [
        ("prob_home_win", "prob_draw", "prob_away_win"),
        ("prob_over_25", "prob_under_25"),
        ("prob_over_15", "prob_under_15"),
        ("prob_over_35", "prob_under_35"),
        ("prob_btts_yes", "prob_btts_no"),
    ]

    for group in groups:
        present = [f for f in group if f in result]
        if len(present) == len(group):
            total = sum(result[f] for f in present)
            if total > 0:
                for f in present:
                    result[f] = result[f] / total

    return result


def _store_calibration(
    model_name: str,
    method: str,
    params: dict,
    sample_size: int,
    mae_before: float,
    mae_after: float,
) -> CalibrationHistory:
    """Store a new calibration and deactivate any previous ones.

    The new calibration is stored with is_active=1.  Any previously active
    calibrations for the same model are deactivated (is_active=0).

    Returns the new CalibrationHistory record.
    """
    with get_session() as session:
        # Deactivate all previous active calibrations for this model
        prev_active = (
            session.query(CalibrationHistory)
            .filter(
                CalibrationHistory.model_name == model_name,
                CalibrationHistory.is_active == 1,
            )
            .all()
        )
        for prev in prev_active:
            prev.is_active = 0
            logger.info(
                "Deactivated previous calibration %d for %s",
                prev.id, model_name,
            )

        # Store the new calibration
        cal = CalibrationHistory(
            model_name=model_name,
            calibration_method=method,
            sample_size=sample_size,
            mean_abs_error_before=mae_before,
            mean_abs_error_after=mae_after,
            parameters_json=json.dumps(params),
            is_active=1,
            rolled_back=0,
        )
        session.add(cal)
        session.flush()

        cal_id = cal.id
        logger.info(
            "Stored calibration %d for %s: %s, MAE %.4f → %.4f",
            cal_id, model_name, method, mae_before, mae_after,
        )

        # Expunge so it can be used outside the session
        session.expunge(cal)

    return cal


def _rollback_calibration(cal: CalibrationHistory) -> None:
    """Roll back a calibration by marking it as inactive and rolled back."""
    with get_session() as session:
        db_cal = (
            session.query(CalibrationHistory)
            .filter_by(id=cal.id)
            .first()
        )
        if db_cal:
            db_cal.is_active = 0
            db_cal.rolled_back = 1
            logger.info(
                "Rolled back calibration %d for %s",
                cal.id, cal.model_name,
            )
