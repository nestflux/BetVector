"""
BetVector World Cup 2026 — Bayesian vs Poisson Validation (WC-09-07)
====================================================================
Two comparisons, surfaced on the Model tab, so we can judge whether the shadow
Bayesian model deserves promotion:

1. **Holdout backtest** (rigorous, leak-free) — both models trained excluding
   the 2022 World Cup, then scored on it. The honest "which model predicts
   better" evidence, on a real tournament's worth of matches.
2. **Live tracker** (directional) — Brier / log-loss / accuracy on the 2026 WC
   matches finished so far, from each model's stored predictions. Small sample
   early on, and predictions are refreshed each pipeline run (a tiny leak — one
   WC result barely moves an 8,000-match fit), so treat it as a running
   indicator, not proof.

PROMOTION IS MANUAL. Nothing here changes which model places bets; the Poisson
remains the only staked model until the owner promotes the Bayesian against the
documented bar below (WC-09-07 — "no automatic promotion").
"""

from __future__ import annotations

import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.models import WCMatch, WCPrediction
from src.world_cup.predictor import WCPoissonPredictor, MODEL_NAME
from src.world_cup.bayesian_model import BayesianPoissonModel, MODEL_NAME_BAYES

logger = logging.getLogger(__name__)

# The bar the Bayesian must clear before the owner promotes it from shadow to a
# staked model. Documented + displayed; NEVER auto-applied (WC-09-07 AC).
PROMOTION_CRITERIA = (
    "The Bayesian model is promoted from shadow to staking ONLY by an explicit "
    "owner decision, and only after it clears ALL of:\n"
    "  1. Beats the Poisson on out-of-sample Brier in the holdout backtest.\n"
    "  2. Non-negative mean CLV over ≥ 30 live shadow picks (once picks exist).\n"
    "  3. Calibration at least as good as the Poisson on finished WC matches.\n"
    "The system never changes the staked model on its own."
)

_NAME_KEY = {MODEL_NAME: "poisson", MODEL_NAME_BAYES: "bayesian"}


def _empty() -> dict:
    return {"n": 0, "brier": None, "log_loss": None, "accuracy": None}


def _actual_vector(home_goals: int, away_goals: int) -> list[int]:
    """One-hot [home, draw, away] outcome."""
    if home_goals > away_goals:
        return [1, 0, 0]
    if home_goals == away_goals:
        return [0, 1, 0]
    return [0, 0, 1]


def _score(pred: list[float], actual: list[int]) -> tuple[float, float, int]:
    """Multi-class Brier, log-loss, and whether the argmax matched."""
    brier = sum((pred[i] - actual[i]) ** 2 for i in range(3))
    p_actual = min(max(pred[actual.index(1)], 1e-12), 1.0 - 1e-12)
    log_loss = -float(np.log(p_actual))
    hit = 1 if pred.index(max(pred)) == actual.index(1) else 0
    return brier, log_loss, hit


def run_holdout_comparison(holdout_tournament: str = "FIFA World Cup",
                           holdout_start: str = "2022-11-01",
                           holdout_end: str = "2022-12-31") -> dict:
    """Train both models excluding the holdout tournament, score both on it.
    Each model is fit and evaluated by its own ``evaluate_holdout`` (same holdout,
    same multi-class Brier), so the comparison is apples-to-apples. Returns each
    model's metrics plus the Brier verdict (informational — never auto-promotes).
    """
    result = {"holdout": f"{holdout_tournament} {holdout_start[:4]}",
              "poisson": None, "bayesian": None}
    try:
        poisson = WCPoissonPredictor(alpha=1.0)
        result["poisson"] = poisson.evaluate_holdout(
            holdout_tournament, holdout_start, holdout_end)
    except Exception as e:  # backtest is best-effort; never crash the dashboard
        logger.error("Poisson holdout failed: %s", e)
    try:
        bayes = BayesianPoissonModel()
        result["bayesian"] = bayes.evaluate_holdout(
            holdout_tournament, holdout_start, holdout_end)
    except Exception as e:
        logger.error("Bayesian holdout failed: %s", e)

    pb = (result["poisson"] or {}).get("brier")
    bb = (result["bayesian"] or {}).get("brier")
    if pb is not None and bb is not None:
        result["brier_winner"] = "bayesian" if bb < pb else "poisson"
        result["brier_delta"] = round(bb - pb, 4)  # negative ⇒ Bayesian better
    return result


def live_model_metrics() -> dict:
    """Brier / log-loss / accuracy for BOTH models on the 2026 WC matches finished
    so far, from their stored predictions. Directional only (small sample early;
    predictions refresh each run). Returns ``{poisson:{...}, bayesian:{...},
    n_matches}``. One bulk query (predictions eager-loaded) — no N+1.
    """
    out = {"poisson": _empty(), "bayesian": _empty(), "n_matches": 0}
    acc = {"poisson": [], "bayesian": []}
    with get_session() as s:
        finished = s.execute(
            select(WCMatch)
            .where(WCMatch.status == "finished")
            .options(joinedload(WCMatch.predictions))
        ).unique().scalars().all()

        n = 0
        for m in finished:
            if m.home_goals is None or m.away_goals is None:
                continue
            actual = _actual_vector(m.home_goals, m.away_goals)
            by_model = {p.model_name: p for p in m.predictions}
            counted = False
            for model_name, key in _NAME_KEY.items():
                p = by_model.get(model_name)
                if not p:
                    continue
                acc[key].append(_score(
                    [p.home_win_prob, p.draw_prob, p.away_win_prob], actual))
                counted = True
            if counted:
                n += 1
        out["n_matches"] = n

    for key in ("poisson", "bayesian"):
        vals = acc[key]
        if vals:
            out[key] = {
                "n": len(vals),
                "brier": round(sum(v[0] for v in vals) / len(vals), 4),
                "log_loss": round(sum(v[1] for v in vals) / len(vals), 4),
                "accuracy": round(sum(v[2] for v in vals) / len(vals), 4),
            }
    return out
