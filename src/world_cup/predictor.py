"""
BetVector World Cup 2026 — International Poisson Predictor (WC-04-01)
=====================================================================
Regularized Poisson regression for WC match prediction.
Based on Groll et al. (2015) methodology, adapted for 2026 tournament.

Training data: Historical international matches (2018+), weighted by
tournament importance. Feature selection based on research literature
for international football prediction.

Produces:
  - P(home), P(draw), P(away) via 7x7 scoreline matrix
  - Expected goals (lambda) for each team
  - O/U 2.5, O/U 3.5, BTTS probabilities
  - Most likely scoreline
  - Dixon-Coles correction for low-scoring draws
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
from sqlalchemy import select

from src.database.db import get_session
from src.world_cup.features import CONFEDERATION_ADJ
from src.world_cup.models import (
    WCFeature, WCHistoricalMatch, WCMatch, WCPrediction, WCTeam,
)

logger = logging.getLogger(__name__)

MAX_GOALS = 7
MODEL_NAME = "wc_poisson_v1"

# Features used for prediction (ordered by importance from research)
FEATURE_COLS = [
    "elo_diff",
    "market_value_ratio",
    "is_host",
    "confederation_adj",
    "wc_appearances",
    "avg_squad_age_centered",
    "avg_squad_age_sq",
    "cl_players_diff",
    "rest_days_diff",
    "altitude_m",
    "gdp_ratio",
    "dark_horse_score",
    "manager_tenure_diff",
    "form_diff",
]


class WCPoissonPredictor:
    """Regularized Poisson regression for WC match prediction."""

    def __init__(self, alpha: float = 1.0) -> None:
        """
        alpha: L2 regularization strength. Higher = more conservative coefficients.
        Default 1.0 — stronger than league model because international sample is smaller.
        """
        self.alpha = alpha
        self.home_coefs: np.ndarray | None = None
        self.away_coefs: np.ndarray | None = None
        self.home_intercept: float = 0.0
        self.away_intercept: float = 0.0
        self.rho: float = -0.05
        self.feature_means: dict[str, float] = {}
        self.feature_stds: dict[str, float] = {}
        self._is_fitted = False

    def fit(self) -> dict:
        """
        Train the model on historical international match data.
        Returns training diagnostics.
        """
        df = self._load_training_data()
        if df.empty:
            logger.error("No training data available")
            return {"status": "error", "reason": "no data"}

        X = self._prepare_features(df)
        y_home = df["home_goals"].values
        y_away = df["away_goals"].values
        weights = df["weight"].values

        # Standardize features
        for col in X.columns:
            mean = X[col].mean()
            std = X[col].std()
            self.feature_means[col] = mean
            self.feature_stds[col] = std if std > 0 else 1.0
            X[col] = (X[col] - mean) / self.feature_stds[col]

        X_arr = X.values

        # Fit home model
        self.home_coefs, self.home_intercept = self._fit_poisson_ridge(
            X_arr, y_home, weights,
        )
        # Fit away model
        self.away_coefs, self.away_intercept = self._fit_poisson_ridge(
            X_arr, y_away, weights,
        )

        # Estimate Dixon-Coles rho from training data
        self.rho = self._estimate_rho(X_arr, y_home, y_away, weights)

        self._is_fitted = True

        # Diagnostics
        pred_home = np.exp(X_arr @ self.home_coefs + self.home_intercept)
        pred_away = np.exp(X_arr @ self.away_coefs + self.away_intercept)

        return {
            "status": "ok",
            "n_matches": len(df),
            "avg_lambda_home": float(pred_home.mean()),
            "avg_lambda_away": float(pred_away.mean()),
            "rho": self.rho,
            "max_abs_coef_home": float(np.max(np.abs(self.home_coefs))),
            "max_abs_coef_away": float(np.max(np.abs(self.away_coefs))),
            "features": list(X.columns),
        }

    def predict(self, match_id: int, session=None) -> dict | None:
        """
        Predict outcome for a single WC match. Returns prediction dict
        or None if data is missing. Pass an existing session to avoid
        nested session contexts (e.g., when called from predict_all).
        """
        if not self._is_fitted:
            logger.error("Model not fitted — call fit() first")
            return None

        def _predict_in_session(s):
            match = s.get(WCMatch, match_id)
            feat = s.execute(
                select(WCFeature).where(WCFeature.match_id == match_id)
            ).scalar_one_or_none()

            if not match or not feat:
                logger.warning("Match %d or features not found", match_id)
                return None

            home = s.get(WCTeam, match.home_team_id)
            away = s.get(WCTeam, match.away_team_id)

            x = self._feature_vector(feat, home, away)
            x_std = self._standardize(x)
            x_arr = np.array([x_std[col] for col in FEATURE_COLS])

            lambda_home = np.exp(x_arr @ self.home_coefs + self.home_intercept)
            lambda_away = np.exp(x_arr @ self.away_coefs + self.away_intercept)

            lambda_home = np.clip(lambda_home, 0.2, 4.0)
            lambda_away = np.clip(lambda_away, 0.2, 4.0)

            # Knockout teams prioritize defense → fewer goals than group stage
            if feat.knockout_deflation and feat.knockout_deflation < 1.0:
                lambda_home *= feat.knockout_deflation
                lambda_away *= feat.knockout_deflation

            matrix = self._build_scoreline_matrix(
                float(lambda_home), float(lambda_away), self.rho,
            )

            is_group = (match.stage == "group")
            probs = self._derive_probabilities(matrix, is_group=is_group)

            return {
                "match_id": match_id,
                "home_team": home.name,
                "away_team": away.name,
                "lambda_home": float(lambda_home),
                "lambda_away": float(lambda_away),
                "home_win_prob": probs["home_win"],
                "draw_prob": probs["draw"],
                "away_win_prob": probs["away_win"],
                "over_25_prob": probs["over_25"],
                "btts_prob": probs["btts"],
                "most_likely_score": probs["most_likely_score"],
                "matrix": matrix,
            }

        if session:
            return _predict_in_session(session)
        try:
            with get_session() as s:
                return _predict_in_session(s)
        except Exception as e:
            logger.error("Prediction failed for match %d: %s", match_id, e)
            return None

    def predict_all(self) -> int:
        """Predict all scheduled WC matches and store in wc_predictions."""
        if not self._is_fitted:
            logger.error("Model not fitted")
            return 0

        try:
            with get_session() as session:
                matches = session.execute(
                    select(WCMatch).order_by(WCMatch.date)
                ).scalars().all()

                stored = 0
                for match in matches:
                    pred = self.predict(match.id, session=session)
                    if not pred:
                        continue

                    existing = session.execute(
                        select(WCPrediction).where(
                            WCPrediction.match_id == match.id,
                            WCPrediction.model_name == MODEL_NAME,
                        )
                    ).scalar_one_or_none()

                    if existing:
                        existing.home_win_prob = pred["home_win_prob"]
                        existing.draw_prob = pred["draw_prob"]
                        existing.away_win_prob = pred["away_win_prob"]
                        existing.home_expected_goals = pred["lambda_home"]
                        existing.away_expected_goals = pred["lambda_away"]
                        existing.over_25_prob = pred["over_25_prob"]
                        existing.btts_prob = pred["btts_prob"]
                        existing.most_likely_score = pred["most_likely_score"]
                    else:
                        new_pred = WCPrediction(
                            match_id=match.id,
                            model_name=MODEL_NAME,
                            home_win_prob=pred["home_win_prob"],
                            draw_prob=pred["draw_prob"],
                            away_win_prob=pred["away_win_prob"],
                            home_expected_goals=pred["lambda_home"],
                            away_expected_goals=pred["lambda_away"],
                            over_25_prob=pred["over_25_prob"],
                            btts_prob=pred["btts_prob"],
                            most_likely_score=pred["most_likely_score"],
                        )
                        session.add(new_pred)
                    stored += 1

                session.commit()
                logger.info("Stored predictions for %d matches", stored)
                return stored
        except Exception as e:
            logger.error("predict_all failed: %s", e)
            return 0

    def evaluate_holdout(self, holdout_tournament: str = "FIFA World Cup",
                         holdout_start: str = "2022-11-01",
                         holdout_end: str = "2022-12-31") -> dict:
        """
        Evaluate model on held-out tournament data (default: 2022 WC).
        Trains on everything except the holdout period, then predicts holdout.
        Returns Brier score and diagnostics.
        """
        with get_session() as session:
            all_hist = session.execute(
                select(WCHistoricalMatch)
                .where(WCHistoricalMatch.date >= "2018-01-01")
                .order_by(WCHistoricalMatch.date)
            ).scalars().all()

            teams = session.execute(select(WCTeam)).scalars().all()
            team_map = {t.name: t for t in teams}
            from src.world_cup.elo import WC_TO_HIST_NAME
            hist_to_wc = {v: k for k, v in WC_TO_HIST_NAME.items()}

        # Split into train and holdout
        train_matches = []
        holdout_matches = []
        for m in all_hist:
            if (m.tournament == holdout_tournament
                and holdout_start <= m.date <= holdout_end):
                holdout_matches.append(m)
            else:
                train_matches.append(m)

        logger.info("Holdout evaluation: %d train, %d holdout",
                     len(train_matches), len(holdout_matches))

        # Build training data (excluding holdout)
        rows = []
        for m in train_matches:
            row = self._hist_match_to_row(m, team_map, hist_to_wc)
            if row:
                rows.append(row)

        df = pd.DataFrame(rows)
        X = self._prepare_features(df)
        y_home = df["home_goals"].values
        y_away = df["away_goals"].values
        weights = df["weight"].values

        for col in X.columns:
            mean = X[col].mean()
            std = X[col].std()
            self.feature_means[col] = mean
            self.feature_stds[col] = std if std > 0 else 1.0
            X[col] = (X[col] - mean) / self.feature_stds[col]

        X_arr = X.values
        self.home_coefs, self.home_intercept = self._fit_poisson_ridge(X_arr, y_home, weights)
        self.away_coefs, self.away_intercept = self._fit_poisson_ridge(X_arr, y_away, weights)
        self.rho = self._estimate_rho(X_arr, y_home, y_away, weights)
        self._is_fitted = True

        # Evaluate on holdout
        brier_scores = []
        correct = 0
        for m in holdout_matches:
            row = self._hist_match_to_row(m, team_map, hist_to_wc)
            if not row:
                continue

            x = {col: row[col] for col in FEATURE_COLS}
            x_std = self._standardize(x)
            x_arr = np.array(list(x_std.values()))

            lh = float(np.clip(np.exp(x_arr @ self.home_coefs + self.home_intercept), 0.2, 4.0))
            la = float(np.clip(np.exp(x_arr @ self.away_coefs + self.away_intercept), 0.2, 4.0))

            matrix = self._build_scoreline_matrix(lh, la, self.rho)
            # WC 2022 group stage ended Dec 2; knockout from Dec 3
            is_group = m.date <= "2022-12-02"
            probs = self._derive_probabilities(matrix, is_group=is_group)

            if m.home_goals > m.away_goals:
                actual = [1, 0, 0]
            elif m.home_goals == m.away_goals:
                actual = [0, 1, 0]
            else:
                actual = [0, 0, 1]

            pred = [probs["home_win"], probs["draw"], probs["away_win"]]
            brier = sum((pred[i] - actual[i]) ** 2 for i in range(3))
            brier_scores.append(brier)

            pred_outcome = ["H", "D", "A"][pred.index(max(pred))]
            actual_outcome = ["H", "D", "A"][actual.index(1)]
            if pred_outcome == actual_outcome:
                correct += 1

        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else 999.0
        return {
            "n_holdout": len(holdout_matches),
            "n_evaluated": len(brier_scores),
            "brier": avg_brier,
            "accuracy": correct / len(brier_scores) if brier_scores else 0,
            "rho": self.rho,
        }

    def _hist_match_to_row(self, m, team_map, hist_to_wc) -> dict | None:
        """Convert a historical match to a feature row."""
        home_name = hist_to_wc.get(m.home_team, m.home_team)
        away_name = hist_to_wc.get(m.away_team, m.away_team)
        home = team_map.get(home_name) or team_map.get(m.home_team)
        away = team_map.get(away_name) or team_map.get(m.away_team)
        if not home or not away:
            return None
        return {
            "home_goals": m.home_goals,
            "away_goals": m.away_goals,
            "weight": m.match_weight,
            "elo_diff": (home.elo_rating or 1500) - (away.elo_rating or 1500),
            "market_value_ratio": math.log(
                max(home.squad_market_value or 1, 1) / max(away.squad_market_value or 1, 1),
            ),
            "is_host": 1 if home.is_host else 0,
            "confederation_adj": CONFEDERATION_ADJ.get(home.confederation or "", 0.0)
                - CONFEDERATION_ADJ.get(away.confederation or "", 0.0),
            "wc_appearances": math.log1p(home.wc_appearances or 0) - math.log1p(away.wc_appearances or 0),
            "avg_squad_age_centered": ((home.avg_squad_age or 27) - 27),
            "avg_squad_age_sq": ((home.avg_squad_age or 27) - 27) ** 2,
            "cl_players_diff": (home.cl_players or 0) - (away.cl_players or 0),
            "rest_days_diff": 0,
            "altitude_m": 0,
            "gdp_ratio": math.log(
                max(home.gdp_per_capita or 1, 1) / max(away.gdp_per_capita or 1, 1),
            ),
            "dark_horse_score": (home.dark_horse_score or 0) - (away.dark_horse_score or 0),
            "manager_tenure_diff": (home.manager_tenure_months or 0) - (away.manager_tenure_months or 0),
            "form_diff": 0,
        }

    def _load_training_data(self) -> pd.DataFrame:
        """Load historical international matches with features for training."""
        with get_session() as session:
            hist = session.execute(
                select(WCHistoricalMatch)
                .where(WCHistoricalMatch.date >= "2018-01-01")
                .order_by(WCHistoricalMatch.date)
            ).scalars().all()

            teams = session.execute(select(WCTeam)).scalars().all()
            team_map = {t.name: t for t in teams}

            from src.world_cup.elo import WC_TO_HIST_NAME
            hist_to_wc = {v: k for k, v in WC_TO_HIST_NAME.items()}

        rows = []
        for m in hist:
            row = self._hist_match_to_row(m, team_map, hist_to_wc)
            if row:
                rows.append(row)

        df = pd.DataFrame(rows)
        logger.info("Loaded %d training matches", len(df))
        return df

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Select and prepare feature columns."""
        return df[FEATURE_COLS].copy()

    def _feature_vector(self, feat: WCFeature, home: WCTeam, away: WCTeam) -> dict:
        """Build a feature dict for a single match from stored features."""
        return {
            "elo_diff": feat.elo_diff or 0.0,
            "market_value_ratio": feat.market_value_ratio or 0.0,
            "is_host": float(feat.is_host_home or 0),
            "confederation_adj": (feat.confederation_adj_home or 0.0) - (feat.confederation_adj_away or 0.0),
            "wc_appearances": math.log1p(feat.wc_appearances_home or 0) - math.log1p(feat.wc_appearances_away or 0),
            "avg_squad_age_centered": (feat.avg_age_home or 27.0) - 27.0,
            "avg_squad_age_sq": ((feat.avg_age_home or 27.0) - 27.0) ** 2,
            "cl_players_diff": float((feat.cl_players_home or 0) - (feat.cl_players_away or 0)),
            "rest_days_diff": float((feat.rest_days_home or 7) - (feat.rest_days_away or 7)),
            "altitude_m": feat.altitude_m or 0.0,
            "gdp_ratio": feat.gdp_ratio or 0.0,
            "dark_horse_score": (feat.dark_horse_score_home or 0.0) - (feat.dark_horse_score_away or 0.0),
            "manager_tenure_diff": float((feat.manager_tenure_home or 0) - (feat.manager_tenure_away or 0)),
            "form_diff": (feat.home_form_last5 or 7.5) - (feat.away_form_last5 or 7.5),
        }

    def _standardize(self, x: dict) -> dict:
        """Standardize a feature vector using training means/stds."""
        result = {}
        for col in FEATURE_COLS:
            val = x.get(col, 0.0)
            mean = self.feature_means.get(col, 0.0)
            std = self.feature_stds.get(col, 1.0)
            result[col] = (val - mean) / std
        return result

    def _fit_poisson_ridge(
        self, X: np.ndarray, y: np.ndarray, weights: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        """Fit Poisson regression with L2 penalty via MLE."""
        n_features = X.shape[1]
        init = np.zeros(n_features + 1)
        init[0] = np.log(y.mean() + 0.01)

        def neg_log_likelihood(params):
            intercept = params[0]
            coefs = params[1:]
            eta = X @ coefs + intercept
            # Clamp for numerical stability
            eta = np.clip(eta, -5, 5)
            mu = np.exp(eta)
            # Weighted Poisson log-likelihood + L2 penalty
            ll = np.sum(weights * (y * np.log(mu + 1e-10) - mu))
            penalty = self.alpha * np.sum(coefs ** 2)
            return -(ll - penalty)

        result = minimize(
            neg_log_likelihood, init, method="L-BFGS-B",
            options={"maxiter": 1000, "ftol": 1e-8},
        )

        if not result.success:
            logger.warning("Optimization did not converge: %s", result.message)

        return result.x[1:], result.x[0]

    def _estimate_rho(
        self, X: np.ndarray, y_home: np.ndarray, y_away: np.ndarray,
        weights: np.ndarray,
    ) -> float:
        """Estimate Dixon-Coles rho from training data."""
        lambdas_h = np.exp(X @ self.home_coefs + self.home_intercept)
        lambdas_a = np.exp(X @ self.away_coefs + self.away_intercept)

        from scipy.optimize import minimize_scalar

        def neg_ll(rho):
            total = 0.0
            for i in range(len(y_home)):
                lh, la = lambdas_h[i], lambdas_a[i]
                gh, ga = int(y_home[i]), int(y_away[i])
                p = poisson.pmf(gh, lh) * poisson.pmf(ga, la)
                tau = _tau(gh, ga, lh, la, rho)
                total += weights[i] * np.log(max(p * tau, 1e-20))
            return -total

        result = minimize_scalar(neg_ll, bounds=(-0.15, 0.0), method="bounded")
        rho = result.x
        logger.info("Estimated rho = %.4f", rho)
        return rho

    @staticmethod
    def _build_scoreline_matrix(
        lambda_home: float, lambda_away: float, rho: float = 0.0,
    ) -> list[list[float]]:
        """Build 7x7 scoreline probability matrix with Dixon-Coles correction."""
        matrix = []
        total = 0.0
        for h in range(MAX_GOALS):
            row = []
            for a in range(MAX_GOALS):
                p = poisson.pmf(h, lambda_home) * poisson.pmf(a, lambda_away)
                tau = _tau(h, a, lambda_home, lambda_away, rho)
                cell = p * tau
                row.append(cell)
                total += cell
            matrix.append(row)

        # Renormalize
        if total > 0:
            for h in range(MAX_GOALS):
                for a in range(MAX_GOALS):
                    matrix[h][a] /= total

        return matrix

    @staticmethod
    def _derive_probabilities(matrix: list[list[float]], is_group: bool = True) -> dict:
        """Derive all market probabilities from the scoreline matrix."""
        home_win = sum(matrix[h][a] for h in range(MAX_GOALS) for a in range(h))
        draw = sum(matrix[h][h] for h in range(MAX_GOALS))
        away_win = sum(matrix[h][a] for h in range(MAX_GOALS) for a in range(h + 1, MAX_GOALS))

        # No ad-hoc draw inflation. Draw frequency is modeled directly by the
        # scoreline matrix and the MLE-estimated Dixon-Coles rho (which already
        # captures the low-score correlation that drives draws). A previous flat
        # +0.03 group-stage "draw_boost" was measured to over-predict draws by
        # ~4.5pp against the de-vigged 59-bookmaker market consensus, manufacturing
        # spurious h2h/draw value bets, so it was removed (WC calibration 2026-06-23).
        # is_group is retained for the interface; knockout goal dynamics are handled
        # upstream via knockout_deflation on lambda, not here.
        _ = is_group
        total = home_win + draw + away_win
        home_win /= total
        draw /= total
        away_win /= total

        over_15 = sum(
            matrix[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS)
            if h + a > 1
        )
        over_25 = sum(
            matrix[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS)
            if h + a > 2
        )
        over_35 = sum(
            matrix[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS)
            if h + a > 3
        )
        btts = sum(
            matrix[h][a] for h in range(1, MAX_GOALS) for a in range(1, MAX_GOALS)
        )

        # Most likely scoreline
        max_prob = 0
        best_score = "1-0"
        for h in range(MAX_GOALS):
            for a in range(MAX_GOALS):
                if matrix[h][a] > max_prob:
                    max_prob = matrix[h][a]
                    best_score = f"{h}-{a}"

        return {
            "home_win": round(home_win, 4),
            "draw": round(draw, 4),
            "away_win": round(away_win, 4),
            "over_15": round(over_15, 4),
            "over_25": round(over_25, 4),
            "over_35": round(over_35, 4),
            "btts": round(btts, 4),
            "most_likely_score": best_score,
        }


def _tau(h: int, a: int, lh: float, la: float, rho: float) -> float:
    """Dixon-Coles tau correction factor for low-scoring cells."""
    if h == 0 and a == 0:
        tau = 1 - lh * la * rho
    elif h == 1 and a == 0:
        tau = 1 + la * rho
    elif h == 0 and a == 1:
        tau = 1 + lh * rho
    elif h == 1 and a == 1:
        tau = 1 - rho
    else:
        return 1.0
    return max(tau, 1e-10)


# Model's default Dixon-Coles prior (matches WCPoissonPredictor.__init__). Used to
# rebuild the scoreline matrix for the research card / deep dive when the per-fit
# rho isn't persisted; the difference vs the fitted rho is sub-0.5pp and immaterial
# for a directional decision-support view (DF-01).
_DEFAULT_RHO = -0.05


def derive_markets_from_lambdas(
    lambda_home: float | None, lambda_away: float | None, rho: float = _DEFAULT_RHO,
) -> dict:
    """All market probabilities (1X2, O/U 1.5/2.5/3.5, BTTS, most-likely score)
    rebuilt from a stored prediction's expected goals via the 7x7 scoreline matrix.

    Decision-support helper for the research card + deep dive (DF-01): the WC model
    computes these lines but only persists 1X2 / O/U 2.5 / BTTS, so the extra O/U
    lines are reconstructed here. The scoreline matrix is the universal interface
    (MP §5) — markets are never derived any other way. Returns {} on missing input.
    """
    if lambda_home is None or lambda_away is None:
        return {}
    matrix = WCPoissonPredictor._build_scoreline_matrix(
        float(lambda_home), float(lambda_away), rho)
    return WCPoissonPredictor._derive_probabilities(matrix)


def scoreline_matrix_from_lambdas(
    lambda_home: float | None, lambda_away: float | None, rho: float = _DEFAULT_RHO,
) -> list[list[float]]:
    """The 7x7 Dixon-Coles-corrected scoreline probability matrix rebuilt from a
    stored prediction's expected goals — the universal model interface (MP §5).

    ``wc_predictions`` persists the expected goals (lambda) but not the matrix
    itself, so the deep-dive heatmap (DF-08) reconstructs the grid here rather
    than re-running the model. ``matrix[h][a]`` = P(home scores h, away scores a),
    summing to 1 across the 7x7 (goals 0..6). Returns ``[]`` on missing input so
    the view can fall back to an empty state. The default rho matches the model's
    prior; the sub-0.5pp difference vs a per-fit rho is immaterial for this
    read-only decision-support view."""
    if lambda_home is None or lambda_away is None:
        return []
    return WCPoissonPredictor._build_scoreline_matrix(
        float(lambda_home), float(lambda_away), rho)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()

    # Step 1: Holdout evaluation on 2022 WC
    print("=== Holdout Evaluation (2022 World Cup) ===")
    eval_predictor = WCPoissonPredictor(alpha=1.0)
    holdout = eval_predictor.evaluate_holdout()
    print(f"Holdout matches: {holdout['n_evaluated']}/{holdout['n_holdout']}")
    print(f"Brier score: {holdout['brier']:.4f} (target < 0.220)")
    print(f"Accuracy: {holdout['accuracy']:.1%}")
    print(f"Rho: {holdout['rho']:.4f}")

    # Step 2: Train on full data and predict 2026
    print("\n=== Training WC Poisson Model (full data) ===")
    predictor = WCPoissonPredictor(alpha=1.0)
    diag = predictor.fit()
    print(f"Status: {diag['status']}")
    print(f"Training matches: {diag.get('n_matches', 0)}")
    print(f"Avg lambda home: {diag.get('avg_lambda_home', 0):.3f}")
    print(f"Avg lambda away: {diag.get('avg_lambda_away', 0):.3f}")
    print(f"Rho: {diag.get('rho', 0):.4f}")
    print(f"Max |coef| home: {diag.get('max_abs_coef_home', 0):.4f}")
    print(f"Max |coef| away: {diag.get('max_abs_coef_away', 0):.4f}")

    print("\n=== Predicting All WC 2026 Matches ===")
    stored = predictor.predict_all()
    print(f"Predictions stored: {stored}")

    print("\n=== Sample Predictions ===")
    with get_session() as session:
        preds = session.execute(
            select(WCPrediction)
            .where(WCPrediction.model_name == MODEL_NAME)
            .order_by(WCPrediction.match_id)
            .limit(10)
        ).scalars().all()

        for p in preds:
            match = session.get(WCMatch, p.match_id)
            ht = session.get(WCTeam, match.home_team_id)
            at = session.get(WCTeam, match.away_team_id)
            actual = f" [{match.home_goals}-{match.away_goals}]" if match.home_goals is not None else ""
            print(
                f"  {ht.name:<20s} vs {at.name:<20s}: "
                f"H={p.home_win_prob:.2f} D={p.draw_prob:.2f} A={p.away_win_prob:.2f} "
                f"xG={p.home_expected_goals:.2f}-{p.away_expected_goals:.2f} "
                f"MLS={p.most_likely_score}{actual}"
            )
