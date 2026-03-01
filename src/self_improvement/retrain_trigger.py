"""
BetVector — Seasonal Re-training Triggers (E12-05)
====================================================
Monitors model accuracy over a rolling window and triggers automatic
retraining when performance degrades beyond a configurable threshold.

How it works:
1. Daily in the evening pipeline, ``check_retrain_needed()`` computes the
   rolling Brier score (last 100 predictions) and compares it to the
   model's all-time average Brier score.
2. If the rolling score is >= 15% worse than all-time, a retrain is triggered.
3. The retrain uses the full historical dataset (not just recent data).
4. After 50 new predictions post-retrain, the new model is compared to the
   old one.  If the new model is worse, it's automatically rolled back.

Guardrails (MP §11.5):
- Rolling window: last 100 predictions (enough to detect degradation quickly)
- Degradation threshold: 15% worse than all-time average triggers retrain
- Cooldown: 30 days between automatic retrains (prevents retrain loops)
- Full history: retrains use ALL available data (prevents overfitting to recent)
- Auto-rollback: if new model is worse over 50 predictions, revert
- Owner notified by email on every automatic retrain

Master Plan refs: MP §11.5 Seasonal Re-training Triggers
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.config import config
from src.database.db import get_session
from src.database.models import (
    Match,
    Prediction,
    RetrainHistory,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Public API
# ============================================================================

def check_retrain_needed(model_name: str) -> Optional[RetrainHistory]:
    """Check if a model needs retraining due to performance degradation.

    Called daily from the evening pipeline.  Computes rolling Brier score
    over the last N predictions and compares to the all-time average.
    If the rolling score has degraded by >= 15%, triggers a retrain
    (subject to cooldown).

    Parameters
    ----------
    model_name : str
        Model to evaluate (e.g. "poisson_v1").

    Returns
    -------
    RetrainHistory or None
        The retrain history record if a retrain was triggered, else None.
    """
    rt_cfg = config.settings.self_improvement.retrain
    rolling_window = rt_cfg.rolling_window                # 100
    degradation_threshold = rt_cfg.degradation_threshold  # 0.15 (15%)
    cooldown_days = rt_cfg.cooldown_period_days           # 30

    # Step 1: Compute rolling and all-time Brier scores
    rolling_brier = _compute_brier_score(model_name, window=rolling_window)
    alltime_brier = _compute_brier_score(model_name, window=None)

    if rolling_brier is None or alltime_brier is None:
        print(f"  → Insufficient data to evaluate {model_name}")
        return None

    if alltime_brier <= 0:
        print(f"  → All-time Brier score is zero for {model_name}, skipping")
        return None

    print(f"  → {model_name}: rolling Brier = {rolling_brier:.4f}, "
          f"all-time = {alltime_brier:.4f}")

    # Step 2: Check degradation
    degradation = (rolling_brier - alltime_brier) / alltime_brier
    print(f"  → Degradation: {degradation:.1%} "
          f"(threshold: {degradation_threshold:.0%})")

    if degradation < degradation_threshold:
        print(f"  → No retrain needed (below threshold)")
        return None

    # Step 3: Check cooldown
    if _is_in_cooldown(model_name, cooldown_days):
        print(f"  → Retrain needed but within {cooldown_days}-day cooldown, "
              f"skipping")
        return None

    # Step 4: Trigger retrain
    print(f"  → Retrain triggered! Rolling Brier {rolling_brier:.4f} is "
          f"{degradation:.1%} worse than all-time {alltime_brier:.4f}")

    retrain_record = _trigger_retrain(
        model_name=model_name,
        brier_before=rolling_brier,
        reason=(
            f"Rolling Brier score ({rolling_brier:.4f}) degraded by "
            f"{degradation:.1%} vs all-time average ({alltime_brier:.4f}). "
            f"Threshold: {degradation_threshold:.0%}."
        ),
    )

    # Step 5: Send email alert to owner
    _send_retrain_alert(model_name, rolling_brier, alltime_brier, degradation)

    return retrain_record


def check_post_retrain_rollback(model_name: str) -> bool:
    """Check if a recent retrain should be rolled back.

    After comparison_window (50) new predictions post-retrain, compares
    the new model's Brier score to the pre-retrain Brier score.  If the
    new model is worse, marks the retrain as rolled back.

    Parameters
    ----------
    model_name : str
        Model to check.

    Returns
    -------
    bool
        True if a rollback was performed, False otherwise.
    """
    rt_cfg = config.settings.self_improvement.retrain
    comparison_window = rt_cfg.comparison_window  # 50

    if not rt_cfg.auto_rollback:
        return False

    # Find the most recent non-rolled-back retrain
    latest_retrain = _get_latest_retrain(model_name)
    if latest_retrain is None:
        return False

    # Already evaluated or rolled back
    if latest_retrain.brier_after is not None:
        return False

    # Count predictions since this retrain
    post_count = _count_predictions_since(model_name, latest_retrain.created_at)
    if post_count < comparison_window:
        return False

    print(f"  → Evaluating post-retrain performance for {model_name} "
          f"({post_count} predictions since retrain)")

    # Compute Brier score over the post-retrain predictions
    post_brier = _compute_brier_score_since(
        model_name, latest_retrain.created_at, limit=comparison_window,
    )

    if post_brier is None:
        return False

    # Update the retrain record with brier_after
    with get_session() as session:
        record = (
            session.query(RetrainHistory)
            .filter_by(id=latest_retrain.id)
            .first()
        )
        if record:
            record.brier_after = round(post_brier, 6)

    print(f"  → Pre-retrain Brier: {latest_retrain.brier_before:.4f}, "
          f"post-retrain: {post_brier:.4f}")

    if post_brier >= latest_retrain.brier_before:
        # New model is worse or same — rollback
        print(f"  → Rolling back retrain (new model is worse)")
        _rollback_retrain(latest_retrain)
        return True

    print(f"  → New model is better, keeping retrain")
    return False


# ============================================================================
# Internal helpers
# ============================================================================

def _compute_brier_score(
    model_name: str,
    window: Optional[int] = None,
) -> Optional[float]:
    """Compute Brier score for a model's 1X2 predictions.

    Uses the multi-class Brier score on home win / draw / away win.

    Parameters
    ----------
    model_name : str
        Model to evaluate.
    window : int or None
        Number of most recent resolved predictions.  None = all-time.

    Returns
    -------
    float or None
        Brier score, or None if no data.
    """
    with get_session() as session:
        query = (
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
        )
        if window is not None:
            query = query.limit(window)

        rows = query.all()

    if not rows:
        return None

    brier_sum = 0.0
    for p_home, p_draw, p_away, h, a in rows:
        y_home = 1.0 if h > a else 0.0
        y_draw = 1.0 if h == a else 0.0
        y_away = 1.0 if h < a else 0.0
        brier_sum += (
            (p_home - y_home) ** 2
            + (p_draw - y_draw) ** 2
            + (p_away - y_away) ** 2
        )

    return brier_sum / len(rows)


def _compute_brier_score_since(
    model_name: str,
    since_date: str,
    limit: int = 50,
) -> Optional[float]:
    """Compute Brier score for predictions created after a given date."""
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
                Prediction.created_at > since_date,
            )
            .order_by(Prediction.created_at.asc())
            .limit(limit)
            .all()
        )

    if not rows:
        return None

    brier_sum = 0.0
    for p_home, p_draw, p_away, h, a in rows:
        y_home = 1.0 if h > a else 0.0
        y_draw = 1.0 if h == a else 0.0
        y_away = 1.0 if h < a else 0.0
        brier_sum += (
            (p_home - y_home) ** 2
            + (p_draw - y_draw) ** 2
            + (p_away - y_away) ** 2
        )

    return brier_sum / len(rows)


def _count_predictions_since(model_name: str, since_date: str) -> int:
    """Count resolved predictions created after a given date."""
    with get_session() as session:
        return (
            session.query(Prediction)
            .join(Match, Prediction.match_id == Match.id)
            .filter(
                Prediction.model_name == model_name,
                Match.status == "finished",
                Match.home_goals.isnot(None),
                Prediction.created_at > since_date,
            )
            .count()
        )


def _is_in_cooldown(model_name: str, cooldown_days: int) -> bool:
    """Check if the model is within the cooldown period after a retrain."""
    cutoff = (
        datetime.utcnow() - timedelta(days=cooldown_days)
    ).strftime("%Y-%m-%d %H:%M:%S")

    with get_session() as session:
        recent = (
            session.query(RetrainHistory)
            .filter(
                RetrainHistory.model_name == model_name,
                RetrainHistory.trigger_type == "automatic",
                RetrainHistory.created_at > cutoff,
            )
            .first()
        )

    return recent is not None


def _get_latest_retrain(model_name: str) -> Optional[RetrainHistory]:
    """Get the most recent retrain record for a model."""
    with get_session() as session:
        record = (
            session.query(RetrainHistory)
            .filter(
                RetrainHistory.model_name == model_name,
                RetrainHistory.was_rolled_back == 0,
            )
            .order_by(RetrainHistory.created_at.desc())
            .first()
        )
        if record:
            session.expunge(record)
        return record


def _trigger_retrain(
    model_name: str,
    brier_before: float,
    reason: str,
) -> RetrainHistory:
    """Log a retrain event and initiate retraining.

    The actual retraining happens on the next morning pipeline run —
    this function logs the event and sets the trigger.  The morning
    pipeline always trains on the full dataset (use_full_history=true),
    so the retrain is effectively automatic.

    Parameters
    ----------
    model_name : str
        Model to retrain.
    brier_before : float
        Current (degraded) rolling Brier score.
    reason : str
        Human-readable trigger reason.

    Returns
    -------
    RetrainHistory
        The new retrain record.
    """
    with get_session() as session:
        # Count training samples (all finished matches)
        training_samples = (
            session.query(Match)
            .filter(
                Match.status == "finished",
                Match.home_goals.isnot(None),
            )
            .count()
        )

        record = RetrainHistory(
            model_name=model_name,
            trigger_type="automatic",
            trigger_reason=reason,
            brier_before=round(brier_before, 6),
            brier_after=None,  # Evaluated post-retrain
            training_samples=training_samples,
            was_rolled_back=0,
        )
        session.add(record)
        session.flush()

        logger.info(
            "Retrain triggered for %s: %s (training_samples=%d)",
            model_name, reason, training_samples,
        )

        session.expunge(record)

    return record


def _rollback_retrain(retrain: RetrainHistory) -> None:
    """Mark a retrain as rolled back."""
    with get_session() as session:
        record = (
            session.query(RetrainHistory)
            .filter_by(id=retrain.id)
            .first()
        )
        if record:
            record.was_rolled_back = 1
            logger.info(
                "Rolled back retrain %d for %s",
                retrain.id, retrain.model_name,
            )


def _send_retrain_alert(
    model_name: str,
    rolling_brier: float,
    alltime_brier: float,
    degradation: float,
) -> None:
    """Send an email alert to the owner about an automatic retrain.

    Uses the existing email_alerts.send_alert() function.  If email
    sending fails, the error is logged but does not prevent the retrain.
    """
    subject = (
        f"🔄 BetVector auto-retrain triggered for {model_name}"
    )
    body = (
        f"Model {model_name} has been automatically retrained.\n\n"
        f"Rolling Brier score: {rolling_brier:.4f}\n"
        f"All-time average: {alltime_brier:.4f}\n"
        f"Degradation: {degradation:.1%}\n\n"
        f"The model will retrain on the full dataset. "
        f"New model will be active for tomorrow's predictions.\n\n"
        f"Performance will be evaluated after 50 new predictions. "
        f"If the new model is worse, it will be automatically rolled back."
    )

    try:
        from src.delivery.email_alerts import send_alert
        # Send to the owner (user_id=1 by default)
        from src.database.db import get_session
        from src.database.models import User

        with get_session() as session:
            owner = (
                session.query(User)
                .filter_by(role="owner")
                .first()
            )
            if owner:
                send_alert(owner.id, subject, body)
                print(f"  → Retrain alert sent to {owner.name}")
            else:
                print("  → No owner user found, skipping email alert")
    except Exception as e:
        # Email failure should never prevent retrain
        logger.warning("Failed to send retrain alert: %s", e)
        print(f"  → Retrain alert failed: {e} (retrain still proceeding)")
