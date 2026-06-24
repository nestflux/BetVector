"""
BetVector World Cup 2026 — Hierarchical Bayesian Poisson (WC-09-05)
===================================================================
A Baio & Blangiardo-style hierarchical Poisson for international football, fit
with **scipy** (MAP estimation + Laplace approximation) rather than PyMC — same
Bayesian model, no heavy dependency, fits the project stack (Rule 2), seconds
to train.

Model
-----
For a match between home team h and away team a:

    log λ_home = μ + home_adv·(1 − neutral) + att[h] − def[a]
    log λ_away = μ +                          att[a] − def[h]
    home_goals ~ Poisson(λ_home),  away_goals ~ Poisson(λ_away)

Team attack/defence get **Gaussian shrinkage priors** N(0, σ²) — the hierarchical
effect that pools noisy strengths toward the global mean (the fix for sparse
international data). Matches are weighted by ``match_weight`` × recency decay.

We find the posterior mode (MAP) by minimising the penalised negative
log-posterior, then take a **Laplace approximation** (Gaussian at the mode, with
covariance = inverse Hessian) for uncertainty — a credible interval on λ. The
7×7 scoreline matrix + market probabilities reuse the Poisson model's builders
(Rule 6 — identical interface, zero downstream changes).
"""

from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import minimize
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.models import WCHistoricalMatch, WCMatch, WCPrediction
from src.world_cup.predictor import WCPoissonPredictor

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
MODEL_NAME_BAYES = "wc_bayesian_v1"

_LAMBDA_CLAMP = (0.2, 4.0)   # same goal-rate clamp as the Poisson model
_MU_HA_PRIOR_VAR = 25.0      # weak N(0, 5²) prior on the intercept + home advantage

# WC squad names that differ from the historical international results dataset.
# Without this the team can't be found in the training index and its matches are
# skipped. Only the host differs today ("USA" vs the dataset's "United States");
# all other 47 WC names align exactly. Extend here if future fixtures add a team
# whose WCTeam.name doesn't match its historical name.
_TEAM_ALIASES = {
    "USA": "United States",
}


def _load_cfg() -> dict:
    try:
        with open(CONFIG_DIR / "worldcup_2026.yaml") as f:
            return (yaml.safe_load(f) or {}).get("bayesian", {})
    except (FileNotFoundError, yaml.YAMLError):
        return {}


def _to_ordinal(date_str: str) -> int | None:
    try:
        return _dt.date.fromisoformat(date_str.strip()[:10]).toordinal()
    except (ValueError, AttributeError):
        return None


class BayesianPoissonModel:
    """Hierarchical Bayesian Poisson via scipy MAP + Laplace."""

    def __init__(self, prior_sd: float | None = None,
                 recency_halflife_days: float | None = None,
                 rho: float | None = None) -> None:
        cfg = _load_cfg()
        self.prior_sd = prior_sd if prior_sd is not None else cfg.get("prior_sd", 0.35)
        self.recency_halflife_days = (
            recency_halflife_days if recency_halflife_days is not None
            else cfg.get("recency_halflife_days", 1825)
        )
        self.rho = rho if rho is not None else cfg.get("rho", -0.05)
        self.teams: list[str] = []
        self.team_idx: dict[str, int] = {}
        self.params: np.ndarray | None = None
        self.cov: np.ndarray | None = None
        self._fitted = False

    # ------------------------------------------------------------------ data
    def _load_matches(self) -> list[tuple]:
        rows: list[tuple] = []
        with get_session() as s:
            for m in s.execute(select(WCHistoricalMatch)).scalars():
                rows.append((m.date, m.home_team, m.away_team,
                             float(m.home_goals), float(m.away_goals),
                             float(m.match_weight or 0.5), int(m.neutral_venue or 0)))
            wc = s.execute(
                select(WCMatch)
                .where(WCMatch.status == "finished")
                .options(joinedload(WCMatch.home_team), joinedload(WCMatch.away_team))
            ).unique().scalars().all()
            for m in wc:
                if m.home_goals is None or not m.home_team or not m.away_team:
                    continue
                rows.append((m.date, m.home_team.name, m.away_team.name,
                             float(m.home_goals), float(m.away_goals), 1.0, 0))
        return rows

    # ------------------------------------------------------------------- fit
    def fit(self) -> dict:
        """Fit on all historical + finished-WC matches."""
        return self._fit_on(self._load_matches())

    def _fit_on(self, rows: list[tuple]) -> dict:
        """MAP fit + Laplace on a given list of match rows. Factored out of fit()
        so the holdout evaluator can fit on a temporal train subset."""
        if len(rows) < 100:
            logger.error("Bayesian fit: insufficient data (%d matches)", len(rows))
            return {"status": "error", "reason": "insufficient data"}

        self.teams = sorted({r[1] for r in rows} | {r[2] for r in rows})
        self.team_idx = {t: i for i, t in enumerate(self.teams)}
        T = len(self.teams)

        hi = np.array([self.team_idx[r[1]] for r in rows])
        ai = np.array([self.team_idx[r[2]] for r in rows])
        hg = np.array([r[3] for r in rows])
        ag = np.array([r[4] for r in rows])
        mw = np.array([r[5] for r in rows])
        neu = np.array([r[6] for r in rows], dtype=float)

        # Recency: weight relative to the most recent match (deterministic given data)
        ords = np.array([_to_ordinal(r[0]) or 0 for r in rows], dtype=float)
        ref = ords.max() if ords.size else 0.0
        # Guard a nonsensical half-life of 0 (config error) → no decay rather than /0.
        decay = np.log(2) / max(float(self.recency_halflife_days), 1.0)
        w = mw * np.exp(-decay * np.maximum(ref - ords, 0.0))

        var = float(self.prior_sd) ** 2
        P = 2 + 2 * T

        def neg_log_post(theta: np.ndarray) -> float:
            mu, ha = theta[0], theta[1]
            att, deff = theta[2:2 + T], theta[2 + T:]
            eta_h = mu + ha * (1 - neu) + att[hi] - deff[ai]
            eta_a = mu + att[ai] - deff[hi]
            ll = (np.sum(w * (hg * eta_h - np.exp(eta_h)))
                  + np.sum(w * (ag * eta_a - np.exp(eta_a))))
            pen = 0.5 * (np.sum(att ** 2) + np.sum(deff ** 2)) / var
            pen += 0.5 * (mu ** 2 + ha ** 2) / _MU_HA_PRIOR_VAR
            return -ll + pen

        def grad(theta: np.ndarray) -> np.ndarray:
            mu, ha = theta[0], theta[1]
            att, deff = theta[2:2 + T], theta[2 + T:]
            eta_h = mu + ha * (1 - neu) + att[hi] - deff[ai]
            eta_a = mu + att[ai] - deff[hi]
            r_h = w * (hg - np.exp(eta_h))   # d(ll)/d eta_home
            r_a = w * (ag - np.exp(eta_a))
            g = np.zeros(P)
            g[0] = r_h.sum() + r_a.sum()
            g[1] = np.sum(r_h * (1 - neu))
            g_att, g_def = np.zeros(T), np.zeros(T)
            np.add.at(g_att, hi, r_h)
            np.add.at(g_att, ai, r_a)
            np.add.at(g_def, ai, -r_h)
            np.add.at(g_def, hi, -r_a)
            g[2:2 + T], g[2 + T:] = g_att, g_def
            gobj = -g  # gradient of the NEGATIVE log-likelihood
            gobj[2:2 + T] += att / var
            gobj[2 + T:] += deff / var
            gobj[0] += mu / _MU_HA_PRIOR_VAR
            gobj[1] += ha / _MU_HA_PRIOR_VAR
            return gobj

        theta0 = np.zeros(P)
        theta0[0] = np.log(max(0.1, (hg.mean() + ag.mean()) / 2.0))
        res = minimize(neg_log_post, theta0, jac=grad, method="L-BFGS-B",
                       options={"maxiter": 1000})
        self.params = res.x

        H = self._hessian(res.x, hi, ai, w, neu, T, var)
        posdef = False
        try:
            self.cov = np.linalg.inv(H)
            posdef = bool(np.all(np.linalg.eigvalsh(H) > 0))
        except np.linalg.LinAlgError:
            self.cov = None
        self._fitted = True

        logger.info("Bayesian fit: %d matches, %d teams, converged=%s, posdef=%s",
                    len(rows), T, res.success, posdef)
        return {"status": "ok", "n_matches": len(rows), "n_teams": T,
                "converged": bool(res.success), "posdef": posdef,
                "mu": float(res.x[0]), "home_adv": float(res.x[1])}

    def _hessian(self, theta, hi, ai, w, neu, T, var) -> np.ndarray:
        """Hessian of the negative log-posterior at the mode (for Laplace).
        Poisson GLM: d²/dη² = λ, so H = Σ_obs wλ·xxᵀ + prior precision."""
        mu, ha = theta[0], theta[1]
        att, deff = theta[2:2 + T], theta[2 + T:]
        lam_h = np.exp(mu + ha * (1 - neu) + att[hi] - deff[ai])
        lam_a = np.exp(mu + att[ai] - deff[hi])
        P = 2 + 2 * T
        H = np.zeros((P, P))

        def accumulate(att_i, def_i, ha_coef, wobs):
            cols = np.stack([np.zeros(len(att_i), int), np.ones(len(att_i), int),
                             2 + att_i, 2 + T + def_i], axis=1)
            signs = np.stack([np.ones(len(att_i)), ha_coef,
                              np.ones(len(att_i)), -np.ones(len(att_i))], axis=1)
            for i in range(4):
                for j in range(4):
                    np.add.at(H, (cols[:, i], cols[:, j]), wobs * signs[:, i] * signs[:, j])

        accumulate(hi, ai, (1 - neu), w * lam_h)   # home side (home adv applies)
        accumulate(ai, hi, np.zeros(len(neu)), w * lam_a)  # away side (no home adv)
        H[0, 0] += 1.0 / _MU_HA_PRIOR_VAR
        H[1, 1] += 1.0 / _MU_HA_PRIOR_VAR
        idx = np.arange(T)
        H[2 + idx, 2 + idx] += 1.0 / var
        H[2 + T + idx, 2 + T + idx] += 1.0 / var
        return H

    # --------------------------------------------------------------- predict
    def predict(self, home_name: str, away_name: str) -> dict | None:
        if not self._fitted or self.params is None:
            return None
        home_name = _TEAM_ALIASES.get(home_name, home_name)
        away_name = _TEAM_ALIASES.get(away_name, away_name)
        hi, ai = self.team_idx.get(home_name), self.team_idx.get(away_name)
        if hi is None or ai is None:
            return None

        T = len(self.teams)
        mu, ha = self.params[0], self.params[1]
        att, deff = self.params[2:2 + T], self.params[2 + T:]
        eta_h = mu + ha + att[hi] - deff[ai]
        eta_a = mu + att[ai] - deff[hi]
        lam_h = float(np.clip(np.exp(eta_h), *_LAMBDA_CLAMP))
        lam_a = float(np.clip(np.exp(eta_a), *_LAMBDA_CLAMP))

        matrix = WCPoissonPredictor._build_scoreline_matrix(lam_h, lam_a, self.rho)
        probs = WCPoissonPredictor._derive_probabilities(matrix)

        ci = None
        if self.cov is not None:
            x = np.zeros(2 + 2 * T)
            x[0], x[1], x[2 + hi], x[2 + T + ai] = 1.0, 1.0, 1.0, -1.0
            sd = float(np.sqrt(max(x @ self.cov @ x, 0.0)))
            ci = (round(float(np.exp(eta_h - 1.96 * sd)), 3),
                  round(float(np.exp(eta_h + 1.96 * sd)), 3))

        return {
            "lambda_home": lam_h,
            "lambda_away": lam_a,
            "lambda_home_ci": ci,
            "home_win_prob": probs["home_win"],
            "draw_prob": probs["draw"],
            "away_win_prob": probs["away_win"],
            "over_25_prob": probs["over_25"],
            "btts_prob": probs["btts"],
            "most_likely_score": probs["most_likely_score"],
            "matrix": matrix,
        }

    # --------------------------------------------------------------- shadow
    def predict_all_shadow(self) -> int:
        """Store Bayesian predictions for every WC match under
        ``MODEL_NAME_BAYES`` (``wc_bayesian_v1``) — **shadow only**.

        This never creates value bets (the value finder reads only the Poisson
        ``MODEL_NAME``) and never overrides the Poisson row; the
        ``UniqueConstraint(match_id, model_name)`` keeps the two models' rows
        side by side. We use the same home/away assignment as the fixture (and
        thus as the Poisson), so the home-advantage term lands on the same side
        in both models — keeping the scorecard comparison apples-to-apples.

        A match is skipped (counted, logged) when either team isn't in the
        training index — the Bayesian model can only rate teams it has seen
        play. Returns the number of predictions stored.
        """
        if not self._fitted:
            logger.error("Bayesian model not fitted — call fit() first")
            return 0

        stored = skipped = 0
        try:
            with get_session() as session:
                matches = session.execute(
                    select(WCMatch)
                    .options(joinedload(WCMatch.home_team),
                             joinedload(WCMatch.away_team))
                    .order_by(WCMatch.date)
                ).unique().scalars().all()

                for match in matches:
                    if not match.home_team or not match.away_team:
                        continue
                    pred = self.predict(match.home_team.name, match.away_team.name)
                    if not pred:
                        skipped += 1
                        continue

                    existing = session.execute(
                        select(WCPrediction).where(
                            WCPrediction.match_id == match.id,
                            WCPrediction.model_name == MODEL_NAME_BAYES,
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
                        session.add(WCPrediction(
                            match_id=match.id,
                            model_name=MODEL_NAME_BAYES,
                            home_win_prob=pred["home_win_prob"],
                            draw_prob=pred["draw_prob"],
                            away_win_prob=pred["away_win_prob"],
                            home_expected_goals=pred["lambda_home"],
                            away_expected_goals=pred["lambda_away"],
                            over_25_prob=pred["over_25_prob"],
                            btts_prob=pred["btts_prob"],
                            most_likely_score=pred["most_likely_score"],
                        ))
                    stored += 1

                session.commit()
                logger.info("Bayesian shadow: stored %d, skipped %d (team not in index)",
                            stored, skipped)
                return stored
        except Exception as e:
            logger.error("predict_all_shadow failed: %s", e)
            return 0

    # ----------------------------------------------------------- validation
    def evaluate_holdout(self, holdout_tournament: str = "FIFA World Cup",
                         holdout_start: str = "2022-11-01",
                         holdout_end: str = "2022-12-31") -> dict:
        """Temporal holdout backtest (default: the 2022 World Cup). Fit on every
        historical match EXCEPT the holdout period, then score multi-class Brier /
        log-loss / accuracy on the holdout. Mirrors
        ``WCPoissonPredictor.evaluate_holdout`` (same holdout, same metrics) so the
        two models can be compared apples-to-apples — this is the rigorous,
        leak-free comparison (vs the live tracker, which re-fits each run)."""
        with get_session() as s:
            hist = s.execute(
                select(WCHistoricalMatch).order_by(WCHistoricalMatch.date)
            ).scalars().all()
            rows_all = [(m.date, m.home_team, m.away_team, float(m.home_goals),
                         float(m.away_goals), float(m.match_weight or 0.5),
                         int(m.neutral_venue or 0), m.tournament) for m in hist]

        train, holdout = [], []
        for r in rows_all:
            if r[7] == holdout_tournament and holdout_start <= r[0] <= holdout_end:
                holdout.append(r)
            else:
                train.append(r)

        info = self._fit_on([r[:7] for r in train])
        if info.get("status") != "ok":
            return {"status": "error", "reason": "fit failed", "detail": info}

        briers, log_losses, correct, n = [], [], 0, 0
        for date, home, away, hg, ag, *_ in holdout:
            p = self.predict(home, away)
            if not p:
                continue
            if hg > ag:
                actual = [1, 0, 0]
            elif hg == ag:
                actual = [0, 1, 0]
            else:
                actual = [0, 0, 1]
            pred = [p["home_win_prob"], p["draw_prob"], p["away_win_prob"]]
            briers.append(sum((pred[i] - actual[i]) ** 2 for i in range(3)))
            p_actual = min(max(pred[actual.index(1)], 1e-12), 1.0 - 1e-12)
            log_losses.append(-np.log(p_actual))
            if pred.index(max(pred)) == actual.index(1):
                correct += 1
            n += 1

        return {
            "status": "ok",
            "model": MODEL_NAME_BAYES,
            "holdout": f"{holdout_tournament} {holdout_start[:4]}",
            "n_holdout": len(holdout),
            "n_evaluated": n,
            "brier": round(sum(briers) / n, 4) if n else None,
            "log_loss": round(sum(log_losses) / n, 4) if n else None,
            "accuracy": round(correct / n, 4) if n else None,
        }
