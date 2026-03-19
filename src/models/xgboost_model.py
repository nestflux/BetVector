"""
BetVector — XGBoost Scoreline Model (E25-01, updated E37-01)
=============================================================
Gradient-boosted decision tree model for predicting expected goals.
Trains two XGBRegressor models (home goals, away goals) on the same
feature matrix as the Poisson GLM, then generates the 7×7 scoreline
probability matrix via Poisson distribution from the predicted λ values.

E37-01 Updates (Multi-League Dataset):
- Trained on all 3 leagues combined (~9,000 matches) instead of EPL only
- Deeper trees (max_depth 5 vs 4) and more estimators (400 vs 200)
- Early stopping with validation set to prevent over-training
- Added E36-03 features: league_home_adv_5, is_newly_promoted
- min_train_samples raised to 500 (config-driven), preventing training on
  per-league subsets that are too small for reliable tree splits

Why XGBoost After Poisson?
--------------------------
The Poisson GLM models a linear relationship (in log-space) between
features and expected goals.  It cannot capture interactions like:
  - "Pinnacle odds AND high Elo difference AND fixture congestion"
  - "High set-piece xG against a team conceding from corners"

XGBoost (eXtreme Gradient Boosting) uses decision trees that naturally
discover these non-linear interactions.  It also handles missing values
natively (no imputation needed), provides feature importance rankings,
and generally achieves better predictive accuracy on tabular data.

How This Model Works
--------------------
1. **Training:** Two XGBRegressor models learn to predict home_goals
   and away_goals from the same features Poisson uses (rolling form,
   xG, market odds, Elo, etc.).
2. **Prediction:** For a new match, both regressors predict λ_home and
   λ_away (expected goals, clamped to [0.1, 5.0]).
3. **Scoreline Matrix:** Uses the SAME Poisson PMF approach as the
   Poisson model — P(h,a) = poisson.pmf(h, λ_home) × poisson.pmf(a, λ_away).
   The XGBoost advantage is in predicting *better* λ values, not in changing
   the scoreline→probability mechanism.

Key Design Decisions
--------------------
- Predicts λ (expected goals), NOT scoreline probabilities directly.
  This preserves the Poisson distribution assumption for the scoreline
  matrix, which downstream code (derive_market_probabilities) depends on.
- Uses the SAME feature set as Poisson for fair comparison.
- Hyperparameters are config-driven (settings.yaml) so they can be tuned
  without code changes.
- Walk-forward safe: train() only sees past data, predict() produces
  future predictions.

Master Plan refs: MP §5 Scoreline Matrix, §13.15 E25 XGBoost Ensemble
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import poisson
from xgboost import XGBRegressor

from src.config import config
from src.models.base_model import (
    BaseModel,
    MatchPrediction,
    derive_market_probabilities,
)

logger = logging.getLogger(__name__)

# Maximum goals per team in the scoreline matrix (0 through MAX_GOALS - 1)
MAX_GOALS = 7  # From config: scoreline_matrix.max_goals


# ============================================================================
# Hyperparameter defaults — overridden by config/settings.yaml if present
# ============================================================================

def _get_xgb_hyperparams() -> Dict:
    """Read XGBoost hyperparameters from config, with sensible defaults.

    Defaults are conservative to avoid overfitting on ~2,000 training matches:
    - max_depth=4: shallow trees reduce overfitting on small datasets
    - n_estimators=200: enough trees for a good ensemble without over-training
    - learning_rate=0.05: low rate + more trees = better generalisation
    - min_child_weight=5: prevents splits on tiny sample sizes
    - subsample=0.8: each tree sees 80% of data (row-level regularisation)
    - colsample_bytree=0.8: each tree sees 80% of features (column-level regularisation)
    - reg_alpha=0.1: L1 regularisation (encourages sparse feature weights)
    - reg_lambda=1.0: L2 regularisation (shrinks extreme coefficients)
    """
    defaults = {
        "max_depth": 5,
        "n_estimators": 400,
        "learning_rate": 0.05,
        "min_child_weight": 5,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "early_stopping_rounds": 30,  # Stop if val loss stagnates for 30 rounds
        "min_train_samples": 500,     # Refuse training on tiny datasets
    }

    try:
        cfg = config.settings.models
        if hasattr(cfg, "xgboost"):
            xgb_cfg = cfg.xgboost
            for key in defaults:
                if hasattr(xgb_cfg, key):
                    defaults[key] = getattr(xgb_cfg, key)
    except (AttributeError, TypeError):
        pass  # Use defaults if config section doesn't exist

    return defaults


class XGBoostModel(BaseModel):
    """XGBoost regression prediction model.

    Trains two separate XGBRegressor models:
      - **Home goals model:** predicts home team expected goals from features
      - **Away goals model:** predicts away team expected goals from features

    The predicted expected goals are used as λ (rate) parameters for the
    Poisson distribution to build the 7×7 scoreline probability matrix,
    exactly as the Poisson GLM does.  The difference is that XGBoost can
    capture non-linear feature interactions that the GLM cannot.
    """

    @property
    def name(self) -> str:
        return "xgboost_v1"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self) -> None:
        self._home_model: Optional[XGBRegressor] = None
        self._away_model: Optional[XGBRegressor] = None
        self._home_feature_cols: List[str] = []
        self._away_feature_cols: List[str] = []
        self._feature_cols: List[str] = []
        self._is_trained: bool = False

    # --- Training -----------------------------------------------------------------

    def train(
        self,
        features: pd.DataFrame,
        results: pd.DataFrame,
        sample_weight: Optional[pd.Series] = None,
    ) -> None:
        """Train XGBoost regressors for home and away expected goals.

        Fits two separate XGBRegressor models on the same feature matrix
        that the Poisson model uses.  XGBoost handles missing values natively
        (NaN features are routed to the optimal split direction), so we
        only need minimal preprocessing.

        Parameters
        ----------
        features : pd.DataFrame
            Training features from ``compute_all_features()``.
            Must contain ``match_id`` and home_*/away_* feature columns.
            May contain a ``_league`` column (dropped before training).
        results : pd.DataFrame
            Match results with columns: ``match_id``, ``home_goals``, ``away_goals``.
        sample_weight : pd.Series, optional
            Per-row training weight (PC-26-06).  Rows from leagues with higher
            ``training_weight`` (e.g. Championship 2.0×) contribute more to
            gradient updates.  If None, all rows weighted equally.
        """
        logger.info("Training XGBoost model on %d matches", len(features))

        # Preserve sample_weight alignment before merge — weights are indexed
        # to the original features DataFrame, so we need to carry them through
        # the merge and dropna steps.
        if sample_weight is not None:
            features = features.copy()
            features["_sample_weight"] = sample_weight.values

        # Merge features with results
        df = features.merge(results, on="match_id", how="inner")

        # Drop rows with missing target (unplayed matches)
        df = df.dropna(subset=["home_goals", "away_goals"])

        # Read the minimum sample size from config.
        # Default is 500 for the multi-league dataset — XGBoost needs enough
        # data to build meaningful tree splits and avoid overfitting.
        # (E25 on EPL-only ~1,900 matches was borderline; 9,000+ across 3
        # leagues gives the model room to learn cross-league patterns.)
        params = _get_xgb_hyperparams()
        min_train_samples = int(params.get("min_train_samples", 500))

        if len(df) < min_train_samples:
            raise ValueError(
                f"Not enough training data: {len(df)} matches "
                f"(XGBoost requires at least {min_train_samples} for reliable "
                f"tree splits — train on all active leagues combined, not per-league)"
            )

        # Select feature columns using the same logic as Poisson
        home_feature_cols = self._select_feature_cols(df, target="home")
        away_feature_cols = self._select_feature_cols(df, target="away")

        # Store the union for save/load and external reference
        self._feature_cols = sorted(
            set(home_feature_cols) | set(away_feature_cols)
        )

        # Extract per-row sample weights (PC-26-06) before selecting features.
        # These survived the merge + dropna because they were added as a column.
        w = None
        if "_sample_weight" in df.columns:
            w = df["_sample_weight"].astype(float).values
            unique_w = set(w)
            if len(unique_w) > 1:
                logger.info(
                    "Per-league sample weights active: %d unique values (min=%.1f, max=%.1f)",
                    len(unique_w), min(w), max(w),
                )

        # Prepare feature matrices.
        # XGBoost handles NaN natively (routes to the optimal split direction),
        # so we do NOT fillna — NaN features like Championship xG (not available
        # via Understat) will be handled internally.  We only convert to numeric
        # to ensure string columns don't slip through.
        X_home = df[home_feature_cols].apply(pd.to_numeric, errors="coerce")
        X_away = df[away_feature_cols].apply(pd.to_numeric, errors="coerce")

        y_home = df["home_goals"].astype(float)
        y_away = df["away_goals"].astype(float)

        # Params were already loaded above for min_train_samples check
        logger.info(
            "XGBoost hyperparams: max_depth=%d, n_estimators=%d, lr=%.3f, "
            "early_stopping_rounds=%s",
            params["max_depth"], params["n_estimators"], params["learning_rate"],
            params.get("early_stopping_rounds", "disabled"),
        )

        # Early stopping: hold out 10% of training data as validation set.
        # If the validation loss doesn't improve for early_stopping_rounds
        # consecutive boosting rounds, training stops early — preventing
        # over-training on the noise in the training set.
        early_stopping_rounds = int(params.get("early_stopping_rounds", 0)) or None
        eval_set_home = None
        eval_set_away = None

        if early_stopping_rounds is not None and len(X_home) >= 100:
            # 10% val split — sort by index so the most recent matches are
            # the validation set (temporal integrity)
            n_val = max(1, int(len(X_home) * 0.1))
            X_home_train = X_home.iloc[:-n_val]
            y_home_train = y_home.iloc[:-n_val]
            eval_set_home = [(X_home.iloc[-n_val:], y_home.iloc[-n_val:])]

            X_away_train = X_away.iloc[:-n_val]
            y_away_train = y_away.iloc[:-n_val]
            eval_set_away = [(X_away.iloc[-n_val:], y_away.iloc[-n_val:])]

            # Split sample weights to match train/val split (PC-26-06)
            w_train = w[:-n_val] if w is not None else None
            # Validation set is unweighted — we want to measure true
            # predictive accuracy, not reweight the loss function.

            logger.info(
                "Early stopping enabled: %d val matches held out (temporal split)",
                n_val,
            )
        else:
            X_home_train, y_home_train = X_home, y_home
            X_away_train, y_away_train = X_away, y_away
            w_train = w  # Full weights when no val split

        # --- Fit home goals model ---
        # objective="count:poisson" uses a Poisson regression loss, which is
        # ideal for count data (goals).  The model predicts log(λ) internally
        # and exp() is applied to get the expected goal count.  This ensures
        # predictions are always non-negative — important because goals can't
        # be negative.
        self._home_model = XGBRegressor(
            objective="count:poisson",
            max_depth=params["max_depth"],
            n_estimators=params["n_estimators"],
            learning_rate=params["learning_rate"],
            min_child_weight=params["min_child_weight"],
            subsample=params["subsample"],
            colsample_bytree=params["colsample_bytree"],
            reg_alpha=params["reg_alpha"],
            reg_lambda=params["reg_lambda"],
            early_stopping_rounds=early_stopping_rounds,
            random_state=42,
            verbosity=0,  # Suppress XGBoost's internal logging
        )

        logger.info(
            "Fitting home goals model (%d features, %d train samples)",
            len(home_feature_cols), len(X_home_train),
        )
        fit_kwargs_home: Dict = {"verbose": False}
        if eval_set_home is not None:
            fit_kwargs_home["eval_set"] = eval_set_home
        if w_train is not None:
            fit_kwargs_home["sample_weight"] = w_train
        self._home_model.fit(X_home_train, y_home_train, **fit_kwargs_home)

        # --- Fit away goals model ---
        self._away_model = XGBRegressor(
            objective="count:poisson",
            max_depth=params["max_depth"],
            n_estimators=params["n_estimators"],
            learning_rate=params["learning_rate"],
            min_child_weight=params["min_child_weight"],
            subsample=params["subsample"],
            colsample_bytree=params["colsample_bytree"],
            reg_alpha=params["reg_alpha"],
            reg_lambda=params["reg_lambda"],
            early_stopping_rounds=early_stopping_rounds,
            random_state=42,
            verbosity=0,
        )

        logger.info(
            "Fitting away goals model (%d features, %d train samples)",
            len(away_feature_cols), len(X_away_train),
        )
        fit_kwargs_away: Dict = {"verbose": False}
        if eval_set_away is not None:
            fit_kwargs_away["eval_set"] = eval_set_away
        if w_train is not None:
            fit_kwargs_away["sample_weight"] = w_train
        self._away_model.fit(X_away_train, y_away_train, **fit_kwargs_away)

        self._home_feature_cols = home_feature_cols
        self._away_feature_cols = away_feature_cols
        self._is_trained = True

        # Log feature importances (top 5 by gain)
        self._log_feature_importance("home", self._home_model, home_feature_cols)
        self._log_feature_importance("away", self._away_model, away_feature_cols)

        logger.info(
            "XGBoost training complete: %d features, %d training matches",
            len(self._feature_cols), len(df),
        )

    # --- Prediction ---------------------------------------------------------------

    def predict(
        self,
        features: pd.DataFrame,
        league: Optional[str] = None,
    ) -> List[MatchPrediction]:
        """Generate predictions for matches.

        For each match:
          1. Feed features through both XGBRegressors → lambda_home, lambda_away
          2. Build 7×7 scoreline matrix from Poisson PMFs
          3. Derive market probabilities from the matrix

        Parameters
        ----------
        features : pd.DataFrame
            Match features (same columns as training data).
            Must contain ``match_id``.
        league : str, optional
            League short name (PC-26-03). Accepted for interface
            compatibility with PoissonModel.predict(); currently unused.

        Returns
        -------
        list[MatchPrediction]
            One prediction per match.
        """
        if not self._is_trained:
            raise RuntimeError("Model not trained — call train() first")

        predictions: List[MatchPrediction] = []

        for _, row in features.iterrows():
            match_id = int(row["match_id"])

            # Prepare feature vectors
            X_home = row[self._home_feature_cols].to_frame().T
            X_away = row[self._away_feature_cols].to_frame().T

            # Convert to numeric (XGBoost handles NaN natively, no fillna needed)
            X_home = X_home.apply(pd.to_numeric, errors="coerce")
            X_away = X_away.apply(pd.to_numeric, errors="coerce")

            # Reset index so .iloc[0] works reliably
            X_home = X_home.reset_index(drop=True)
            X_away = X_away.reset_index(drop=True)

            # Predict expected goals (lambda values)
            # XGBRegressor with count:poisson objective returns the expected count
            # (already exp()-transformed internally), so predictions are always ≥ 0.
            lambda_home = float(self._home_model.predict(X_home)[0])
            lambda_away = float(self._away_model.predict(X_away)[0])

            # Clamp lambda to reasonable range [0.1, 5.0]
            # Very extreme lambdas produce degenerate scoreline matrices.
            # 0.1 prevents zero-goal certainty, 5.0 prevents unrealistic blowouts.
            lambda_home = max(0.1, min(5.0, lambda_home))
            lambda_away = max(0.1, min(5.0, lambda_away))

            # Build the 7×7 scoreline probability matrix.
            # Note: Dixon-Coles ρ is currently Poisson-only (MP §4).
            # The _build_scoreline_matrix method accepts a rho parameter for
            # forward compatibility, but XGBoost uses rho=0.0 (standard
            # independent Poisson matrix generation).  If future backtests
            # show XGBoost benefits from ρ correction, add _rho estimation
            # here (same MLE approach as PoissonModel._estimate_rho).
            matrix = self._build_scoreline_matrix(lambda_home, lambda_away)

            # Derive all market probabilities from the matrix
            market_probs = derive_market_probabilities(matrix)

            pred = MatchPrediction(
                match_id=match_id,
                model_name=self.name,
                model_version=self.version,
                predicted_home_goals=round(lambda_home, 4),
                predicted_away_goals=round(lambda_away, 4),
                scoreline_matrix=matrix,
                **market_probs,
            )
            predictions.append(pred)

        logger.info("Generated %d XGBoost predictions", len(predictions))
        return predictions

    # --- Save/Load ----------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Save the trained model to disk using pickle.

        Saves both XGBRegressor objects, feature column lists, and metadata
        in a single pickle file.
        """
        if not self._is_trained:
            raise RuntimeError("Cannot save untrained model")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "name": self.name,
            "version": self.version,
            "home_model": self._home_model,
            "away_model": self._away_model,
            "home_feature_cols": self._home_feature_cols,
            "away_feature_cols": self._away_feature_cols,
            "feature_cols": self._feature_cols,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f)

        logger.info("Saved XGBoost model to %s", path)

    def load(self, path: Path) -> None:
        """Load a previously trained model from disk."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        with open(path, "rb") as f:
            state = pickle.load(f)

        self._home_model = state["home_model"]
        self._away_model = state["away_model"]
        self._home_feature_cols = state["home_feature_cols"]
        self._away_feature_cols = state["away_feature_cols"]
        self._feature_cols = state["feature_cols"]
        self._is_trained = True

        logger.info("Loaded XGBoost model from %s", path)

    # --- Internal helpers ---------------------------------------------------------

    @staticmethod
    def _select_feature_cols(
        df: pd.DataFrame,
        target: str,
    ) -> List[str]:
        """Select feature columns for home or away goals prediction.

        Uses the SAME feature set as the Poisson model (E16-01, E20-01, E20-02,
        E21-01, E21-02, E21-03, E22-01, E22-02) so the comparison between
        models is fair — any performance difference comes from the model
        architecture, not feature engineering.

        Only includes columns that actually exist in the DataFrame, so the
        model degrades gracefully when some features are unavailable.
        """
        if target == "home":
            attack_prefix = "home_"
            defence_prefix = "away_"
        else:
            attack_prefix = "away_"
            defence_prefix = "home_"

        # Attacking features: how good is this team at scoring?
        attack_cols = [
            f"{attack_prefix}form_5",
            f"{attack_prefix}form_10",
            f"{attack_prefix}goals_scored_5",
            f"{attack_prefix}goals_scored_10",
            f"{attack_prefix}venue_form_5",
            f"{attack_prefix}venue_goals_scored_5",
            # Advanced attack features (E16-01)
            f"{attack_prefix}npxg_5",
            f"{attack_prefix}deep_5",
            # REMOVED (PC-18): shots_on_target_5 (0% all leagues — FBref dead)
            # REMOVED (PC-18): set_piece_xg_5, open_play_xg_5 (<65% coverage)
        ]

        # Defensive features: how bad is the opponent at defending?
        defence_cols = [
            f"{defence_prefix}goals_conceded_5",
            f"{defence_prefix}goals_conceded_10",
            f"{defence_prefix}venue_goals_conceded_5",
            # Advanced defence features (E16-01)
            f"{defence_prefix}npxga_5",
            f"{defence_prefix}ppda_allowed_5",
        ]

        # Context features
        context_cols = [
            f"{attack_prefix}rest_days",
            f"{attack_prefix}h2h_goals_scored",
            # Market-implied features (E20-01, E20-02)
            # NOTE (PC-09-01): pinnacle_draw_prob excluded — it is linearly
            # dependent on home + away (sum ≈ 1.0), causing multicollinearity
            # in the Poisson GLM.  Removed here too for feature consistency
            # across models, even though XGBoost trees are robust to collinearity.
            f"{attack_prefix}pinnacle_home_prob",
            f"{attack_prefix}pinnacle_away_prob",
            f"{attack_prefix}ah_line",
            # Elo ratings (E21-01)
            f"{attack_prefix}elo_rating",
            f"{attack_prefix}elo_diff",
            # Fixture congestion (E21-03)
            f"{attack_prefix}is_congested",
            # Injury impact (E22-02)
            f"{attack_prefix}injury_impact",
            f"{attack_prefix}key_player_out",
            # --- Lineup features (E39-09, E39-10) ---
            f"{attack_prefix}squad_rotation_index",
            f"{attack_prefix}formation_changed",
            # --- Manager features (E40-05, pruned PC-18) ---
            f"{attack_prefix}new_manager_flag",
            f"{attack_prefix}manager_change_count",
            # Multi-league context (E36-03)
            f"{attack_prefix}league_home_adv_5",
            f"{attack_prefix}is_newly_promoted",
            # REMOVED (PC-18): market_value_ratio, is_heavy_weather, ref_avg_goals,
            # ref_home_win_pct, bench_strength, manager_win_pct, manager_tenure_days
            # See poisson.py PC-18 comments for rationale.
        ]

        # Only include columns that exist in the DataFrame
        all_candidates = attack_cols + defence_cols + context_cols
        available = [c for c in all_candidates if c in df.columns]

        if not available:
            raise ValueError(
                f"No feature columns found for {target} goals model. "
                f"Expected columns like {all_candidates[:3]}"
            )

        return available

    @staticmethod
    def _build_scoreline_matrix(
        lambda_home: float,
        lambda_away: float,
        rho: float = 0.0,
    ) -> List[List[float]]:
        """Build a 7×7 scoreline probability matrix from Poisson lambdas.

        For each cell (h, a) in the matrix:
            P(home=h, away=a) = poisson.pmf(h, λ_h) × poisson.pmf(a, λ_a) × τ(h,a,ρ)

        When ``rho=0.0``, this is equivalent to independent Poisson (all τ = 1).

        Dixon-Coles Correction (PC-21)
        --------------------------------
        Applies the same τ correction as the Poisson model — see the
        ``PoissonModel._build_scoreline_matrix()`` docstring for the full
        explanation of the four τ multipliers and the ρ parameter.

        The XGBoost improvement comes from better λ estimates (via gradient
        boosting instead of GLM), not from the scoreline generation mechanism.
        Both models share the same Dixon-Coles correction logic.

        Parameters
        ----------
        lambda_home : float
            Expected home goals (Poisson rate parameter).
        lambda_away : float
            Expected away goals (Poisson rate parameter).
        rho : float, default 0.0
            Dixon-Coles correlation parameter.  Must be in [-0.15, 0.0].

        Returns
        -------
        list[list[float]]
            7×7 matrix of scoreline probabilities, renormalised to sum to 1.0.
        """
        matrix = []
        total = 0.0

        for h in range(MAX_GOALS):
            row = []
            for a in range(MAX_GOALS):
                # Independent Poisson probabilities
                p = poisson.pmf(h, lambda_home) * poisson.pmf(a, lambda_away)
                row.append(p)
                total += p
            matrix.append(row)

        # Renormalise for truncation (removes mass beyond 6 goals per side)
        if total > 0:
            matrix = [
                [p / total for p in row]
                for row in matrix
            ]

        # --- Dixon-Coles τ correction (PC-21-02) ---
        if rho != 0.0:
            # Dixon & Coles (1997) equation (4)
            tau_00 = 1.0 - lambda_home * lambda_away * rho  # 0-0: ↑ with ρ < 0
            tau_10 = 1.0 + lambda_away * rho                # 1-0: ↓ with ρ < 0
            tau_01 = 1.0 + lambda_home * rho                # 0-1: ↓ with ρ < 0
            tau_11 = 1.0 - rho                              # 1-1: ↑ with ρ < 0

            # Clamp τ to avoid negative probabilities
            matrix[0][0] *= max(0.0, tau_00)
            matrix[1][0] *= max(0.0, tau_10)
            matrix[0][1] *= max(0.0, tau_01)
            matrix[1][1] *= max(0.0, tau_11)

            # Renormalise so all 49 cells sum to 1.0
            total_after = sum(
                matrix[h][a]
                for h in range(MAX_GOALS)
                for a in range(MAX_GOALS)
            )
            if total_after > 0:
                matrix = [
                    [p / total_after for p in row]
                    for row in matrix
                ]

        return matrix

    @staticmethod
    def _log_feature_importance(
        label: str,
        model: XGBRegressor,
        feature_cols: List[str],
    ) -> None:
        """Log top features by importance gain for debugging.

        XGBoost tracks feature importance internally — how much each feature
        contributes to reducing the training loss.  Logging the top 5 helps
        verify the model is learning sensible relationships (e.g., Pinnacle
        odds and Elo should rank highly for goal prediction).
        """
        try:
            importances = model.feature_importances_
            if importances is None or len(importances) == 0:
                return

            # Sort by importance descending
            sorted_idx = np.argsort(importances)[::-1]
            top_n = min(5, len(sorted_idx))

            top_features = [
                (feature_cols[i], importances[i])
                for i in sorted_idx[:top_n]
            ]
            feature_str = ", ".join(
                f"{name}={imp:.4f}" for name, imp in top_features
            )
            logger.info(
                "XGBoost %s model top-%d features: %s",
                label, top_n, feature_str,
            )
        except Exception as e:
            logger.warning(
                "Could not log %s feature importances: %s", label, e,
            )

    def get_feature_importances(self) -> Dict[str, Dict[str, float]]:
        """Return feature importance rankings for both models.

        Useful for the Model Health dashboard and self-improvement
        feature tracking (MP §11.2).

        Returns
        -------
        dict
            Keys: "home", "away".
            Values: dict mapping feature_name → importance score.
        """
        if not self._is_trained:
            return {"home": {}, "away": {}}

        result = {}
        for label, model, cols in [
            ("home", self._home_model, self._home_feature_cols),
            ("away", self._away_model, self._away_feature_cols),
        ]:
            importances = model.feature_importances_
            result[label] = {
                cols[i]: float(importances[i])
                for i in range(len(cols))
                if i < len(importances)
            }

        return result
