"""
BetVector — Base Model Interface and Market Derivation (E5-01)
===============================================================
Defines the abstract interface all prediction models must implement,
the ``MatchPrediction`` dataclass that standardises model output, and
the critical ``derive_market_probabilities()`` utility.

Architectural Rationale (MP §5):
  Every prediction model — Poisson, Elo, XGBoost, neural net — must
  output a **7×7 scoreline probability matrix**.  The matrix covers
  every possible scoreline from 0-0 to 6-6 (49 cells that sum to 1.0).
  All market probabilities (1X2, Over/Under, BTTS) are then derived
  from this single matrix.  This means:
    - Any model can be plugged into the ensemble without changing
      downstream code
    - Value detection, backtesting, and the dashboard all work
      identically regardless of which model produced the prediction

The ``derive_market_probabilities()`` function is THE single point
where market probabilities are computed.  It is never bypassed.

Master Plan refs: MP §5 Scoreline Matrix, MP §7 Model Interface
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import pandas as pd


# ============================================================================
# MatchPrediction Dataclass
# ============================================================================

@dataclass
class MatchPrediction:
    """Universal output structure for all prediction models.

    Every model produces one ``MatchPrediction`` per match.  The scoreline
    matrix is the fundamental output; all market probabilities are derived
    from it via ``derive_market_probabilities()``.

    Attributes
    ----------
    match_id : int
        Database ID of the match being predicted.
    model_name : str
        Name of the model that produced this prediction (e.g. "poisson_v1").
    model_version : str
        Semantic version of the model (e.g. "1.0.0").
    predicted_home_goals : float
        Expected home goals (lambda for Poisson distribution).  Typically
        in the range 0.5–3.5.  This is NOT the predicted scoreline — it's
        the Poisson rate parameter.  A value of 1.5 means the home team
        is expected to score 1.5 goals on average.
    predicted_away_goals : float
        Expected away goals (lambda for Poisson distribution).
    scoreline_matrix : list[list[float]]
        7×7 matrix where ``matrix[h][a]`` is the probability of the
        scoreline being h-a.  All 49 values sum to 1.0.
    prob_home_win .. prob_btts_no : float
        Market probabilities derived from the scoreline matrix.
    """
    match_id: int
    model_name: str
    model_version: str
    predicted_home_goals: float
    predicted_away_goals: float
    scoreline_matrix: List[List[float]]

    # Derived market probabilities — filled by derive_market_probabilities()
    prob_home_win: float = 0.0
    prob_draw: float = 0.0
    prob_away_win: float = 0.0
    prob_over_25: float = 0.0
    prob_under_25: float = 0.0
    prob_over_15: float = 0.0
    prob_under_15: float = 0.0
    prob_over_35: float = 0.0
    prob_under_35: float = 0.0
    prob_btts_yes: float = 0.0
    prob_btts_no: float = 0.0


# ============================================================================
# Market Probability Derivation
# ============================================================================

def derive_market_probabilities(
    scoreline_matrix: List[List[float]],
) -> Dict[str, float]:
    """Derive all betting market probabilities from a scoreline matrix.

    This is THE critical function in BetVector's architecture.  Every
    market probability flows through this single function.  No market
    probability is ever calculated any other way.

    How it works:
      The 7×7 matrix contains the probability of every scoreline from
      0-0 to 6-6.  To get the probability of "home win", we sum all cells
      where home_goals > away_goals.  To get "over 2.5 goals", we sum all
      cells where home_goals + away_goals >= 3.  And so on.

    Parameters
    ----------
    scoreline_matrix : list[list[float]]
        7×7 matrix where ``matrix[h][a]`` = P(home scores h, away scores a).
        Must sum to approximately 1.0.

    Returns
    -------
    dict
        Keys: prob_home_win, prob_draw, prob_away_win, prob_over_25,
        prob_under_25, prob_over_15, prob_under_15, prob_over_35,
        prob_under_35, prob_btts_yes, prob_btts_no.

    Raises
    ------
    ValueError
        If the matrix is not 7×7 or probabilities don't sum to ~1.0.
    """
    # Validate matrix dimensions
    if len(scoreline_matrix) != 7:
        raise ValueError(
            f"Scoreline matrix must have 7 rows (got {len(scoreline_matrix)})"
        )
    for i, row in enumerate(scoreline_matrix):
        if len(row) != 7:
            raise ValueError(
                f"Scoreline matrix row {i} must have 7 columns (got {len(row)})"
            )

    # Validate sum ≈ 1.0
    total = sum(
        scoreline_matrix[h][a] for h in range(7) for a in range(7)
    )
    if abs(total - 1.0) > 0.01:
        raise ValueError(
            f"Scoreline matrix probabilities sum to {total:.6f}, "
            f"expected ~1.0 (tolerance 0.01)"
        )

    # --- 1X2 market (match result) ---
    # Home win: home_goals > away_goals
    # Draw: home_goals == away_goals
    # Away win: home_goals < away_goals
    prob_home_win = 0.0
    prob_draw = 0.0
    prob_away_win = 0.0

    # --- Over/Under goals markets ---
    # Over X.5: total goals >= X+1 (e.g., over 2.5 means >= 3 goals)
    # Under X.5: total goals <= X (e.g., under 2.5 means <= 2 goals)
    prob_over_15 = 0.0
    prob_over_25 = 0.0
    prob_over_35 = 0.0

    # --- Both Teams To Score (BTTS) ---
    # BTTS Yes: both teams score at least 1 goal
    # BTTS No: at least one team scores 0
    prob_btts_yes = 0.0

    for h in range(7):
        for a in range(7):
            p = scoreline_matrix[h][a]
            total_goals = h + a

            # 1X2
            if h > a:
                prob_home_win += p
            elif h == a:
                prob_draw += p
            else:
                prob_away_win += p

            # Over/Under thresholds
            if total_goals >= 2:  # Over 1.5
                prob_over_15 += p
            if total_goals >= 3:  # Over 2.5
                prob_over_25 += p
            if total_goals >= 4:  # Over 3.5
                prob_over_35 += p

            # BTTS: both teams scored at least 1
            if h >= 1 and a >= 1:
                prob_btts_yes += p

    # --- Probability capping ---
    # No single market outcome should be above 98% or below 2%.
    # Even the strongest favourite vs the weakest underdog has upset potential.
    # Capping prevents degenerate edges (e.g., +60%) that mislead the bettor.
    # Complementary pairs (over/under, btts yes/no, 1X2) are capped individually
    # so they may not sum to exactly 1.0 — this is acceptable for display and
    # edge computation (the raw matrix probabilities remain uncapped internally).
    PROB_MIN, PROB_MAX = 0.02, 0.98

    def _cap(p: float) -> float:
        return round(max(PROB_MIN, min(PROB_MAX, p)), 6)

    return {
        "prob_home_win": _cap(prob_home_win),
        "prob_draw": _cap(prob_draw),
        "prob_away_win": _cap(prob_away_win),
        "prob_over_25": _cap(prob_over_25),
        "prob_under_25": _cap(1.0 - prob_over_25),
        "prob_over_15": _cap(prob_over_15),
        "prob_under_15": _cap(1.0 - prob_over_15),
        "prob_over_35": _cap(prob_over_35),
        "prob_under_35": _cap(1.0 - prob_over_35),
        "prob_btts_yes": _cap(prob_btts_yes),
        "prob_btts_no": _cap(1.0 - prob_btts_yes),
    }


# ============================================================================
# Base Model ABC
# ============================================================================

class BaseModel(ABC):
    """Abstract base class for all BetVector prediction models.

    Every model must:
      1. Accept a training DataFrame and learn parameters
      2. Accept a features DataFrame and produce MatchPrediction objects
      3. Be serialisable (save/load to disk)

    The ``predict()`` method must return a list of ``MatchPrediction``
    objects, each containing a 7×7 scoreline matrix.  Market probabilities
    are derived from this matrix via ``derive_market_probabilities()``.

    Example concrete implementations:
      - ``PoissonModel`` — Poisson regression with attack/defence strengths
      - ``EloModel`` (future) — Elo rating system
      - ``XGBoostModel`` (future) — gradient-boosted trees
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short model identifier (e.g. 'poisson_v1', 'xgboost_v1')."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string (e.g. '1.0.0')."""

    @abstractmethod
    def train(
        self,
        features: pd.DataFrame,
        results: pd.DataFrame,
    ) -> None:
        """Train the model on historical data.

        Parameters
        ----------
        features : pd.DataFrame
            Training features (one row per match, home_*/away_* columns).
        results : pd.DataFrame
            Match results with columns: match_id, home_goals, away_goals.
        """

    @abstractmethod
    def predict(
        self,
        features: pd.DataFrame,
    ) -> List[MatchPrediction]:
        """Generate predictions for matches.

        Parameters
        ----------
        features : pd.DataFrame
            Features for matches to predict (same column format as training).

        Returns
        -------
        list[MatchPrediction]
            One prediction per match, each containing the 7×7 scoreline
            matrix and all derived market probabilities.
        """

    @abstractmethod
    def save(self, path: Path) -> None:
        """Serialise the trained model to disk.

        Parameters
        ----------
        path : Path
            File path to save the model to (e.g. ``models/poisson_v1.pkl``).
        """

    @abstractmethod
    def load(self, path: Path) -> None:
        """Load a previously trained model from disk.

        Parameters
        ----------
        path : Path
            File path to load the model from.
        """
