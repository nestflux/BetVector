"""
BetVector — Feature Importance Tracking (E12-02)
=================================================
Logs and tracks feature importance over time for tree-based models
(XGBoost, LightGBM).  Provides trend analysis and flags features
whose importance has dropped below a threshold for consecutive
training cycles — but NEVER auto-removes them.

The core philosophy: **inform, don't decide**.  This module surfaces
data about which features matter and which don't, then leaves the
decision to the human.  Automated feature removal is explicitly
forbidden by MP §11.2.

How it works:
1. After each training cycle, the model calls ``log_feature_importance()``
   with a dict of feature_name → importance_gain values.
2. The module computes ranks, stores everything in ``feature_importance_log``.
3. ``get_importance_trends()`` returns a DataFrame showing how each
   feature's importance has changed over the last N training cycles.
4. ``get_flagged_features()`` identifies features below the configured
   threshold (1%) for 3+ consecutive cycles and returns warning messages.

Master Plan refs: MP §11.2 Dynamic Feature Importance Tracking
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.config import config
from src.database.db import get_session
from src.database.models import FeatureImportanceLog

logger = logging.getLogger(__name__)


# ============================================================================
# Public API
# ============================================================================

def log_feature_importance(
    model_name: str,
    importance: Dict[str, float],
    training_date: Optional[str] = None,
) -> int:
    """Log feature importance scores after a training cycle.

    Called by tree-based models (XGBoost, LightGBM) after training.
    Computes ranks from the raw importance values and stores all features
    in the ``feature_importance_log`` table.

    Parameters
    ----------
    model_name : str
        Name of the model (e.g. "xgboost_v1", "lightgbm_v1").
    importance : dict
        Mapping of feature_name → importance_gain.  The gain values
        represent how much each feature contributes to the model's
        predictions.  Higher = more important.  These typically come
        from XGBoost's ``get_score(importance_type='gain')`` or
        LightGBM's ``feature_importance(importance_type='gain')``.
    training_date : str, optional
        ISO date string (YYYY-MM-DD) for the training cycle.
        Defaults to today's date if not provided.

    Returns
    -------
    int
        Number of feature importance records stored.
    """
    if not importance:
        logger.warning("No feature importance data to log for %s", model_name)
        return 0

    if training_date is None:
        training_date = datetime.utcnow().strftime("%Y-%m-%d")

    # Normalise importance values so they sum to 1.0 (proportional importance)
    total_gain = sum(importance.values())
    if total_gain <= 0:
        logger.warning("Total importance gain is zero for %s", model_name)
        return 0

    normalised = {
        feat: gain / total_gain for feat, gain in importance.items()
    }

    # Rank features by importance (1 = most important)
    ranked = sorted(normalised.items(), key=lambda x: x[1], reverse=True)

    with get_session() as session:
        # Check for existing entries to avoid duplicates (idempotent)
        existing = (
            session.query(FeatureImportanceLog)
            .filter(
                FeatureImportanceLog.model_name == model_name,
                FeatureImportanceLog.training_date == training_date,
            )
            .count()
        )
        if existing > 0:
            logger.info(
                "Feature importance already logged for %s on %s (%d entries), "
                "skipping duplicate",
                model_name, training_date, existing,
            )
            return 0

        records = []
        for rank, (feature_name, gain) in enumerate(ranked, start=1):
            record = FeatureImportanceLog(
                model_name=model_name,
                training_date=training_date,
                feature_name=feature_name,
                importance_gain=round(gain, 6),
                importance_rank=rank,
            )
            records.append(record)

        session.add_all(records)

    logger.info(
        "Logged %d feature importance entries for %s (date: %s)",
        len(records), model_name, training_date,
    )
    return len(records)


def get_importance_trends(
    model_name: str,
    n_cycles: int = 5,
) -> pd.DataFrame:
    """Get feature importance trends over the last N training cycles.

    Returns a DataFrame with one row per feature and one column per
    training date, showing how importance has shifted over time.  Also
    includes a ``trend`` column indicating direction (↑ rising, ↓ falling,
    → stable) based on the change between the earliest and latest cycles.

    Parameters
    ----------
    model_name : str
        Model to query importance for.
    n_cycles : int
        Number of recent training cycles to include (default: 5).

    Returns
    -------
    pd.DataFrame
        Columns: feature_name, plus one column per training_date,
        plus ``latest_rank``, ``latest_gain``, and ``trend``.
        Sorted by latest importance rank (most important first).
        Empty DataFrame if no data is available.
    """
    with get_session() as session:
        # Get the last N distinct training dates for this model
        dates_query = (
            session.query(FeatureImportanceLog.training_date)
            .filter(FeatureImportanceLog.model_name == model_name)
            .distinct()
            .order_by(FeatureImportanceLog.training_date.desc())
            .limit(n_cycles)
            .all()
        )
        dates = sorted([d[0] for d in dates_query])

        if not dates:
            return pd.DataFrame()

        # Get all feature importance entries for these dates
        entries = (
            session.query(FeatureImportanceLog)
            .filter(
                FeatureImportanceLog.model_name == model_name,
                FeatureImportanceLog.training_date.in_(dates),
            )
            .all()
        )

    if not entries:
        return pd.DataFrame()

    # Build a pivot table: rows = features, columns = dates, values = gain
    rows = []
    for entry in entries:
        rows.append({
            "feature_name": entry.feature_name,
            "training_date": entry.training_date,
            "importance_gain": entry.importance_gain,
            "importance_rank": entry.importance_rank,
        })

    df = pd.DataFrame(rows)

    # Pivot: feature_name as index, training_date as columns, importance_gain as values
    pivot = df.pivot_table(
        index="feature_name",
        columns="training_date",
        values="importance_gain",
        aggfunc="first",
    )

    # Add latest rank and gain
    latest_date = dates[-1]
    latest = df[df["training_date"] == latest_date].set_index("feature_name")
    pivot["latest_rank"] = latest["importance_rank"]
    pivot["latest_gain"] = latest["importance_gain"]

    # Compute trend direction based on change from earliest to latest
    earliest_date = dates[0]
    if len(dates) >= 2:
        # Calculate trend as the difference between latest and earliest gain
        for feat in pivot.index:
            earliest_val = pivot.loc[feat, earliest_date] if earliest_date in pivot.columns else None
            latest_val = pivot.loc[feat, latest_date] if latest_date in pivot.columns else None

            if earliest_val is not None and latest_val is not None:
                diff = latest_val - earliest_val
                # Threshold: ±0.5 percentage points for "stable"
                if diff > 0.005:
                    pivot.loc[feat, "trend"] = "↑"
                elif diff < -0.005:
                    pivot.loc[feat, "trend"] = "↓"
                else:
                    pivot.loc[feat, "trend"] = "→"
            else:
                pivot.loc[feat, "trend"] = "→"
    else:
        pivot["trend"] = "→"

    # Sort by latest rank (most important first)
    pivot = pivot.sort_values("latest_rank", ascending=True)

    # Reset index so feature_name is a column
    pivot = pivot.reset_index()

    return pivot


def get_flagged_features(
    model_name: str,
) -> List[Dict[str, object]]:
    """Identify features flagged for possible removal.

    A feature is flagged if its importance has been below the configured
    threshold (default: 1%) for the configured number of consecutive
    training cycles (default: 3).

    This function only reports — it NEVER removes features.  The decision
    to drop a feature is always made by the human operator.

    Parameters
    ----------
    model_name : str
        Model to check.

    Returns
    -------
    list of dict
        Each dict contains:
        - ``feature_name``: the flagged feature
        - ``consecutive_cycles``: how many cycles it's been below threshold
        - ``latest_gain``: its most recent importance (as a proportion)
        - ``message``: human-readable warning message
    """
    fi_cfg = config.settings.self_improvement.feature_importance
    threshold = fi_cfg.importance_threshold      # 0.01 (1%)
    window = fi_cfg.flagging_window              # 3 consecutive cycles

    with get_session() as session:
        # Get the last `window` distinct training dates
        dates_query = (
            session.query(FeatureImportanceLog.training_date)
            .filter(FeatureImportanceLog.model_name == model_name)
            .distinct()
            .order_by(FeatureImportanceLog.training_date.desc())
            .limit(window)
            .all()
        )
        dates = sorted([d[0] for d in dates_query])

        if len(dates) < window:
            # Not enough cycles to flag anything
            return []

        # Get all features from the latest date as our reference set
        latest_date = dates[-1]
        latest_features = (
            session.query(
                FeatureImportanceLog.feature_name,
                FeatureImportanceLog.importance_gain,
            )
            .filter(
                FeatureImportanceLog.model_name == model_name,
                FeatureImportanceLog.training_date == latest_date,
            )
            .all()
        )

        # For each feature, check if it's been below threshold for all
        # of the last `window` cycles
        flagged = []
        for feat_name, latest_gain in latest_features:
            # Get importance for this feature across the last `window` dates
            entries = (
                session.query(FeatureImportanceLog.importance_gain)
                .filter(
                    FeatureImportanceLog.model_name == model_name,
                    FeatureImportanceLog.feature_name == feat_name,
                    FeatureImportanceLog.training_date.in_(dates),
                )
                .all()
            )

            gains = [e[0] for e in entries]

            # Check: all gains in the window are below threshold
            if len(gains) >= window and all(g < threshold for g in gains):
                flagged.append({
                    "feature_name": feat_name,
                    "consecutive_cycles": len(gains),
                    "latest_gain": latest_gain,
                    "message": (
                        f"Consider removing '{feat_name}' — it has contributed "
                        f"less than {threshold * 100:.0f}% importance for the "
                        f"last {len(gains)} training cycles "
                        f"(latest: {latest_gain * 100:.2f}%)"
                    ),
                })

    if flagged:
        for f in flagged:
            logger.info("Flagged feature: %s", f["message"])

    return flagged
