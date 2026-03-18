"""
BetVector — Lambda Calibration Module (PC-24-03)
=================================================
Corrects systematic over/under-prediction of expected goals (λ values)
by applying scaling factors learned from held-out calibration data.

Rule 6 Compliance (Scoreline Matrix Contract)
----------------------------------------------
Calibration is applied to λ_home and λ_away BEFORE ``_build_scoreline_matrix()``
is called.  The corrected λ values produce a corrected 7×7 scoreline matrix,
and ``derive_market_probabilities()`` operates on that corrected matrix as normal.
This ensures the scoreline matrix remains the single source of truth for all
market probabilities — no post-derivation probability manipulation.

Why Calibrate λ Values?
------------------------
If the Poisson model systematically over-predicts home goals (e.g., predicts
λ_home = 1.8 on average but teams only score 1.5), all derived probabilities
are inflated — Home Win is overestimated, Under 2.5 is underestimated, and
every edge calculation is biased by ~5 percentage points.

A simple multiplicative correction (scale_home = actual_mean / predicted_mean)
brings the λ values in line with reality.  This is equivalent to re-centering
the Poisson distribution, which flows through the entire scoreline matrix.

MP §11.1 Guardrails
--------------------
- **Minimum sample size:** 200 resolved predictions before calibration applies
- **Significance threshold:** Only correct if |scale - 1.0| > 0.03 (3pp)
- **Rollback window:** 100 predictions post-calibration (if Brier worsens, undo)

Master Plan refs: MP §11.1 (Automatic Recalibration), Rule 6 (scoreline matrix
                  contract), config/settings.yaml self_improvement.recalibration
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# MP §11.1: Minimum resolved predictions before calibration is applied
CALIBRATION_MIN_SAMPLES = 200

# MP §11.1: Only correct if mean-abs calibration error exceeds 3pp
CALIBRATION_ERROR_THRESHOLD = 0.03


@dataclass
class CalibrationResult:
    """Stores the result of a calibration fit for inspection and logging."""

    n_samples: int = 0
    scale_home: float = 1.0
    scale_away: float = 1.0
    home_error: float = 0.0  # |scale_home - 1.0|
    away_error: float = 0.0  # |scale_away - 1.0|
    is_applied: bool = False  # True if calibration meets significance threshold
    reason: str = ""  # Why calibration was/wasn't applied


class LambdaCalibrator:
    """Scales predicted λ values to correct systematic bias.

    Learns multiplicative scaling factors from a held-out calibration set
    where both predicted λ and actual goals are known.  When applied to
    new predictions, the corrected λ values flow into the scoreline matrix
    builder — preserving the Rule 6 contract.

    Usage in Walk-Forward Backtesting
    ----------------------------------
    At each walk-forward step:
      1. Train the Poisson model on 90% of available training data
      2. Predict λ for the 10% held-out calibration set
      3. Call ``calibrator.fit(predicted_λ, actual_goals)``
      4. When predicting the test matchday, call
         ``calibrator.transform(λ_home, λ_away)`` to get corrected values
      5. Pass corrected λ to ``_build_scoreline_matrix()``

    If the calibrator is not fitted or the bias is below the significance
    threshold, ``transform()`` returns the original λ values unchanged.
    """

    def __init__(self) -> None:
        self._scale_home: float = 1.0
        self._scale_away: float = 1.0
        self._is_fitted: bool = False
        self._n_samples: int = 0
        self._last_result: Optional[CalibrationResult] = None

    @property
    def is_fitted(self) -> bool:
        """Whether calibration has been fitted and meets significance threshold."""
        return self._is_fitted

    @property
    def scales(self) -> Tuple[float, float]:
        """Current (scale_home, scale_away) values."""
        return (self._scale_home, self._scale_away)

    @property
    def last_result(self) -> Optional[CalibrationResult]:
        """The result from the most recent fit() call."""
        return self._last_result

    def fit(
        self,
        predicted_home_lambda: np.ndarray,
        predicted_away_lambda: np.ndarray,
        actual_home_goals: np.ndarray,
        actual_away_goals: np.ndarray,
    ) -> CalibrationResult:
        """Fit scaling factors from calibration data.

        Computes the ratio of mean actual goals to mean predicted λ for
        both home and away.  If the ratio is within the significance
        threshold (±3pp from 1.0), no calibration is applied.

        Parameters
        ----------
        predicted_home_lambda : np.ndarray
            Predicted home goal rates (λ_home) for calibration matches.
        predicted_away_lambda : np.ndarray
            Predicted away goal rates (λ_away) for calibration matches.
        actual_home_goals : np.ndarray
            Actual home goals scored in calibration matches.
        actual_away_goals : np.ndarray
            Actual away goals scored in calibration matches.

        Returns
        -------
        CalibrationResult
            Summary of the calibration fit.
        """
        n = len(predicted_home_lambda)

        # MP §11.1: Minimum sample size guardrail
        if n < CALIBRATION_MIN_SAMPLES:
            result = CalibrationResult(
                n_samples=n,
                reason=f"Below minimum sample size ({n} < {CALIBRATION_MIN_SAMPLES})",
            )
            self._is_fitted = False
            self._scale_home = 1.0
            self._scale_away = 1.0
            self._last_result = result
            logger.info(
                "LambdaCalibrator: %s — using raw λ values", result.reason,
            )
            return result

        # Compute mean predicted λ and mean actual goals
        mean_pred_home = float(np.mean(predicted_home_lambda))
        mean_pred_away = float(np.mean(predicted_away_lambda))
        mean_actual_home = float(np.mean(actual_home_goals))
        mean_actual_away = float(np.mean(actual_away_goals))

        # Avoid division by zero (shouldn't happen with real data)
        if mean_pred_home < 1e-6 or mean_pred_away < 1e-6:
            result = CalibrationResult(
                n_samples=n,
                reason="Predicted λ too close to zero — skipping calibration",
            )
            self._is_fitted = False
            self._last_result = result
            return result

        # Compute scaling factors
        scale_home = mean_actual_home / mean_pred_home
        scale_away = mean_actual_away / mean_pred_away

        # Compute calibration errors
        home_error = abs(scale_home - 1.0)
        away_error = abs(scale_away - 1.0)

        # MP §11.1: Significance threshold — only correct if error > 3pp
        if home_error < CALIBRATION_ERROR_THRESHOLD and away_error < CALIBRATION_ERROR_THRESHOLD:
            result = CalibrationResult(
                n_samples=n,
                scale_home=scale_home,
                scale_away=scale_away,
                home_error=home_error,
                away_error=away_error,
                is_applied=False,
                reason=(
                    f"Below significance threshold "
                    f"(home_error={home_error:.4f}, away_error={away_error:.4f}, "
                    f"threshold={CALIBRATION_ERROR_THRESHOLD})"
                ),
            )
            self._is_fitted = False
            self._scale_home = 1.0
            self._scale_away = 1.0
            self._last_result = result
            logger.info(
                "LambdaCalibrator: %s — using raw λ values", result.reason,
            )
            return result

        # Calibration is significant — apply scaling
        self._scale_home = scale_home
        self._scale_away = scale_away
        self._is_fitted = True
        self._n_samples = n

        result = CalibrationResult(
            n_samples=n,
            scale_home=scale_home,
            scale_away=scale_away,
            home_error=home_error,
            away_error=away_error,
            is_applied=True,
            reason=(
                f"Calibration applied: scale_home={scale_home:.4f}, "
                f"scale_away={scale_away:.4f} (n={n})"
            ),
        )
        self._last_result = result
        logger.info("LambdaCalibrator: %s", result.reason)
        return result

    def transform(
        self,
        lambda_home: float,
        lambda_away: float,
    ) -> Tuple[float, float]:
        """Apply calibration scaling to λ values.

        If the calibrator is not fitted or the bias was below the
        significance threshold, returns the original λ values unchanged.

        Parameters
        ----------
        lambda_home : float
            Raw predicted home goal rate.
        lambda_away : float
            Raw predicted away goal rate.

        Returns
        -------
        tuple[float, float]
            (calibrated_λ_home, calibrated_λ_away)
        """
        if not self._is_fitted:
            return lambda_home, lambda_away

        return (
            lambda_home * self._scale_home,
            lambda_away * self._scale_away,
        )

    def save(self, path: Path) -> None:
        """Save calibrator state to disk (alongside model pickle)."""
        state = {
            "scale_home": self._scale_home,
            "scale_away": self._scale_away,
            "is_fitted": self._is_fitted,
            "n_samples": self._n_samples,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f)

    def load(self, path: Path) -> None:
        """Load calibrator state from disk."""
        with open(path, "rb") as f:
            state = pickle.load(f)
        self._scale_home = state["scale_home"]
        self._scale_away = state["scale_away"]
        self._is_fitted = state["is_fitted"]
        self._n_samples = state["n_samples"]
