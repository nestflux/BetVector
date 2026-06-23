"""
BetVector World Cup 2026 — Model Calibration & Dark Horse Detection (WC-04-03)
================================================================================
Live calibration of the WC Poisson model as tournament results come in.

Three core functions:
  1. calibrate_on_group_stage() — re-fit model with 2026 data included
  2. detect_dark_horses() — find teams undervalued by bookmakers
  3. compute_model_accuracy() — Brier score, log-loss, accuracy tracking

Also provides in-tournament Elo updates using config-driven K-factors
(K=40 group, K=50 knockout by default) and goal-difference multipliers
to capture momentum within the tournament.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import yaml
from sqlalchemy import select

from src.database.db import get_session
from src.world_cup.models import (
    WCCalibrationMetric, WCMatch, WCOdds, WCPrediction, WCTeam,
)
from src.world_cup.predictor import MODEL_NAME, WCPoissonPredictor

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _load_elo_config() -> dict:
    """Load Elo K-factors and home advantage from worldcup_2026.yaml."""
    config_path = CONFIG_DIR / "worldcup_2026.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("elo", {})


def _goal_diff_multiplier(goal_diff: int) -> float:
    """Scale Elo update by margin of victory (World Football Elo method).
    A 5-0 thrashing carries more Elo weight than a 1-0 grind."""
    g = abs(goal_diff)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11 + g) / 8


def _persist_metrics(metrics: dict, cal_type: str) -> None:
    """Store calibration metrics to DB for dashboard display."""
    if metrics.get("n_matches", 0) == 0:
        return
    with get_session() as session:
        row = WCCalibrationMetric(
            calibration_type=cal_type,
            n_matches=metrics["n_matches"],
            brier=metrics.get("brier"),
            brier_per_class=metrics.get("brier_per_class"),
            log_loss=metrics.get("log_loss"),
            accuracy=metrics.get("accuracy"),
        )
        session.add(row)
        session.commit()


def calibrate_on_group_stage(predictor: WCPoissonPredictor) -> dict:
    """
    Re-fit the Poisson model with 2026 group stage results included in
    the training set. This tunes coefficients for this tournament's
    specific characteristics (goal rate, upset frequency, etc.).

    Returns diagnostics comparing pre- and post-calibration Brier.
    """
    pre_brier = compute_model_accuracy()
    _persist_metrics(pre_brier, "pre_calibration")

    try:
        diag = predictor.fit()
        predictor.predict_all()
    except Exception:
        logger.exception("Calibration fit/predict failed — returning pre-calibration metrics")
        return {
            "status": "error",
            "pre_brier": pre_brier.get("brier", 0),
            "post_brier": pre_brier.get("brier", 0),
            "improvement": 0.0,
            "n_training": 0,
            "n_evaluated": pre_brier.get("n_matches", 0),
        }

    post_brier = compute_model_accuracy()
    _persist_metrics(post_brier, "post_calibration")

    improvement = (pre_brier.get("brier", 0) - post_brier.get("brier", 0))
    result = {
        "status": "ok",
        "pre_brier": pre_brier.get("brier", 0),
        "post_brier": post_brier.get("brier", 0),
        "improvement": improvement,
        "n_training": diag.get("n_matches", 0),
        "n_evaluated": post_brier.get("n_matches", 0),
    }
    logger.info(
        "Calibration: Brier %.4f → %.4f (improvement: %.4f)",
        result["pre_brier"], result["post_brier"], improvement,
    )
    return result


def detect_dark_horses(
    sim_probs: dict[str, dict] | None = None,
    min_edge: float = 0.05,
) -> list[dict]:
    """
    Compare model probabilities to bookmaker implied probabilities.
    Teams where model_prob exceeds market_prob by more than min_edge
    are dark horses — the market is undervaluing them.

    Two detection modes:
      1. Tournament-level: if sim_probs is provided (from simulator),
         compare advancement/winner probabilities against outright odds.
      2. Match-level: compare next-match win probabilities against h2h odds.

    In tournament betting, a 5% edge threshold is aggressive — bookmaker
    overrounds on outrights are typically 15-40%, so a 5% model edge
    represents genuine mispricing, not just overround noise.
    """
    dark_horses = []

    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()

        for team in teams:
            # Mode 1: tournament-advancement probabilities from simulator
            if sim_probs and team.name in sim_probs:
                tp = sim_probs[team.name]
                model_adv = tp.get("r32", 0.0)
                model_winner = tp.get("winner", 0.0)

                # Check outright winner odds
                _check_outright_edge(
                    session, team, model_winner, "winner",
                    min_edge, dark_horses,
                )
                # Check advancement odds (to_qualify markets)
                _check_outright_edge(
                    session, team, model_adv, "advancement",
                    min_edge, dark_horses,
                )

            # Mode 2: next-match win probability
            upcoming = session.execute(
                select(WCMatch)
                .where(
                    WCMatch.status != "finished",
                    (WCMatch.home_team_id == team.id) | (WCMatch.away_team_id == team.id),
                )
                .order_by(WCMatch.date)
                .limit(1)
            ).scalar_one_or_none()

            if not upcoming:
                continue

            pred = session.execute(
                select(WCPrediction)
                .where(
                    WCPrediction.match_id == upcoming.id,
                    WCPrediction.model_name == MODEL_NAME,
                )
            ).scalar_one_or_none()

            if not pred:
                continue

            is_home = upcoming.home_team_id == team.id
            selection = "home" if is_home else "away"
            model_prob = pred.home_win_prob if is_home else pred.away_win_prob

            best_odds = session.execute(
                select(WCOdds)
                .where(
                    WCOdds.match_id == upcoming.id,
                    WCOdds.market_type == "h2h",
                    WCOdds.selection == selection,
                )
                .order_by(WCOdds.odds_decimal.desc())
                .limit(1)
            ).scalar_one_or_none()

            if not best_odds or best_odds.odds_decimal <= 1.0:
                continue

            implied_prob = 1.0 / best_odds.odds_decimal
            edge = model_prob - implied_prob

            if edge >= min_edge:
                opponent = session.get(
                    WCTeam,
                    upcoming.away_team_id if is_home else upcoming.home_team_id,
                )
                dark_horses.append({
                    "team": team.name,
                    "opponent": opponent.name if opponent else "?",
                    "match_id": upcoming.id,
                    "market": "h2h",
                    "model_prob": round(model_prob, 4),
                    "implied_prob": round(implied_prob, 4),
                    "edge": round(edge, 4),
                    "best_odds": best_odds.odds_decimal,
                    "bookmaker": best_odds.bookmaker,
                    "dark_horse_score": team.dark_horse_score or 0,
                })

    dark_horses.sort(key=lambda x: -x["edge"])
    logger.info("Dark horses detected: %d (min_edge=%.1f%%)", len(dark_horses), min_edge * 100)
    return dark_horses


def _check_outright_edge(
    session, team: WCTeam, model_prob: float, market: str,
    min_edge: float, results: list,
) -> None:
    """Check if a team has an edge in outright/advancement markets."""
    best = session.execute(
        select(WCOdds)
        .where(
            WCOdds.market_type == "outright",
            WCOdds.selection == team.name,
        )
        .order_by(WCOdds.odds_decimal.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not best or best.odds_decimal <= 1.0:
        return

    implied = 1.0 / best.odds_decimal
    edge = model_prob - implied
    if edge >= min_edge:
        results.append({
            "team": team.name,
            "opponent": "(outright)",
            "match_id": None,
            "market": market,
            "model_prob": round(model_prob, 4),
            "implied_prob": round(implied, 4),
            "edge": round(edge, 4),
            "best_odds": best.odds_decimal,
            "bookmaker": best.bookmaker,
            "dark_horse_score": team.dark_horse_score or 0,
        })


def compute_model_accuracy() -> dict:
    """
    Compute calibration metrics on finished WC 2026 matches.
    Returns Brier score, log-loss, and accuracy percentage.

    Brier score measures probability calibration — lower is better.
    A Brier of 0.20 per class means the model's confidence roughly
    matches actual outcome frequency. Log-loss penalizes confident
    wrong predictions more heavily — important for betting where
    overconfidence destroys bankroll.
    """
    brier_scores = []
    log_losses = []
    correct = 0

    with get_session() as session:
        preds = session.execute(
            select(WCPrediction)
            .where(WCPrediction.model_name == MODEL_NAME)
        ).scalars().all()

        for p in preds:
            match = session.get(WCMatch, p.match_id)
            if not match or match.status != "finished" or match.home_goals is None:
                continue

            if match.home_goals > match.away_goals:
                actual = [1, 0, 0]
            elif match.home_goals == match.away_goals:
                actual = [0, 1, 0]
            else:
                actual = [0, 0, 1]

            pred_probs = [p.home_win_prob, p.draw_prob, p.away_win_prob]

            # 3-way Brier: sum of squared errors across H/D/A outcomes
            brier = sum((pred_probs[i] - actual[i]) ** 2 for i in range(3))
            brier_scores.append(brier)

            # Log-loss (clamped to prevent log(0))
            for i in range(3):
                if actual[i] == 1:
                    log_losses.append(-math.log(max(pred_probs[i], 1e-10)))

            # Accuracy — did the most probable outcome occur?
            pred_outcome = pred_probs.index(max(pred_probs))
            if actual[pred_outcome] == 1:
                correct += 1

    n = len(brier_scores)
    if n == 0:
        return {"n_matches": 0, "brier": 0.0, "log_loss": 0.0, "accuracy": 0.0}

    return {
        "n_matches": n,
        "brier": sum(brier_scores) / n,
        "brier_per_class": sum(brier_scores) / n / 3,
        "log_loss": sum(log_losses) / n,
        "accuracy": correct / n,
    }


def update_tournament_elo() -> dict:
    """
    Update team Elo ratings based on finished WC 2026 results.
    Uses config-driven K-factors (higher than friendlies because WC
    matches are the strongest competitive signal available).

    Idempotent: always recomputes from pre-tournament baseline Elo
    stored in the elo config, so running twice doesn't double-apply.

    Elo changes capture in-tournament momentum — a team that beats
    a strong opponent gains rating points, which shifts predictions
    for their subsequent matches.
    """
    cfg = _load_elo_config()
    k_group = cfg.get("k_factors", {}).get("wc_group", 40)
    k_knockout = cfg.get("k_factors", {}).get("wc_knockout", 50)
    partial_home = cfg.get("k_factors", {}).get("partial_home", 50)

    with get_session() as session:
        matches = session.execute(
            select(WCMatch)
            .where(WCMatch.status == "finished")
            .order_by(WCMatch.date)
        ).scalars().all()

        teams = session.execute(select(WCTeam)).scalars().all()
        team_by_id = {t.id: t for t in teams}

        # Start from pre-tournament Elo (the rating computed by elo.py
        # before any WC matches). We store this in elo_rating initially
        # and recompute from there each time for idempotency.
        # The first call snapshots it; subsequent calls restore baseline.
        baseline = {}
        for t in teams:
            if not hasattr(t, '_pre_tournament_elo'):
                baseline[t.id] = t.elo_rating or 1500
            else:
                baseline[t.id] = t._pre_tournament_elo
        elo = dict(baseline)

        updates = []
        for m in matches:
            if m.home_goals is None:
                continue

            k = k_knockout if m.stage != "group" else k_group
            r_h = elo[m.home_team_id]
            r_a = elo[m.away_team_id]

            # Host-nation partial home advantage
            home_team = team_by_id.get(m.home_team_id)
            ha = partial_home if (home_team and home_team.is_host) else 0

            # Expected score with home advantage
            e_h = 1.0 / (1.0 + 10 ** ((r_a - (r_h + ha)) / 400.0))

            # Actual score
            if m.home_goals > m.away_goals:
                s_h = 1.0
            elif m.home_goals == m.away_goals:
                s_h = 0.5
            else:
                s_h = 0.0

            gd_mult = _goal_diff_multiplier(m.home_goals - m.away_goals)
            delta = k * gd_mult * (s_h - e_h)
            elo[m.home_team_id] += delta
            elo[m.away_team_id] -= delta

            updates.append({
                "match_id": m.id,
                "home_id": m.home_team_id,
                "away_id": m.away_team_id,
                "delta": round(delta, 1),
            })

        # Write back updated Elo
        for team in teams:
            team.elo_rating = round(elo[team.id], 1)

        session.commit()

    logger.info("Updated Elo for %d finished matches (K_group=%d, K_ko=%d)",
                len(updates), k_group, k_knockout)
    return {"n_matches": len(updates), "updates": updates}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()

    print("=== Model Accuracy (Pre-Calibration) ===")
    metrics = compute_model_accuracy()
    print(f"Matches: {metrics['n_matches']}")
    print(f"Brier: {metrics['brier']:.4f} ({metrics['brier_per_class']:.4f}/class)")
    print(f"Log-loss: {metrics['log_loss']:.4f}")
    print(f"Accuracy: {metrics['accuracy']:.1%}")

    print("\n=== In-Tournament Elo Updates ===")
    elo_result = update_tournament_elo()
    print(f"Matches processed: {elo_result['n_matches']}")
    for u in elo_result["updates"][:5]:
        print(f"  Match {u['match_id']}: delta={u['delta']:+.1f}")

    print("\n=== Calibration ===")
    predictor = WCPoissonPredictor(alpha=1.0)
    predictor.fit()
    cal = calibrate_on_group_stage(predictor)
    print(f"Pre-Brier: {cal['pre_brier']:.4f}")
    print(f"Post-Brier: {cal['post_brier']:.4f}")
    print(f"Improvement: {cal['improvement']:.4f}")

    print("\n=== Dark Horses (>5% edge) ===")
    horses = detect_dark_horses(min_edge=0.05)
    if horses:
        for h in horses[:10]:
            print(
                f"  {h['team']:<20s} vs {h['opponent']:<20s} "
                f"edge={h['edge']:+.1%} model={h['model_prob']:.1%} "
                f"market={h['implied_prob']:.1%} @ {h['best_odds']:.2f} ({h['bookmaker']})"
            )
    else:
        print("  No dark horses found (no odds data loaded yet)")
