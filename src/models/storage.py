"""
BetVector — Prediction Storage and Retrieval (E5-03)
=====================================================
Stores model predictions in the database and provides retrieval functions
for downstream modules (value finder, dashboard, backtesting).

Every prediction model outputs a ``MatchPrediction`` dataclass containing a
7×7 scoreline probability matrix and derived market probabilities.  This
module handles:

  - **Serialisation:** The scoreline matrix (a Python list of lists) is
    stored as a JSON string in the ``predictions.scoreline_matrix`` column.
  - **Deserialisation:** On retrieval, the JSON string is parsed back into
    a Python list of lists and wrapped in a ``MatchPrediction`` object.
  - **Upsert logic:** If a prediction already exists for the same
    (match_id, model_name, model_version) triple, it is updated in place
    rather than creating a duplicate row.

The ``predictions`` table has a UNIQUE constraint on
``(match_id, model_name, model_version)`` — see MP §6.  This means each
model can only have one active prediction per match.  Re-running the
prediction pipeline simply overwrites stale predictions.

Master Plan refs: MP §6 predictions table, MP §7 Model Interface
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc

from src.database.db import get_session
from src.database.models import Match, Prediction
from src.models.base_model import MatchPrediction

logger = logging.getLogger(__name__)


# ============================================================================
# Load Active Models
# ============================================================================

def load_active_models() -> Dict[str, Any]:
    """Load all models listed in config.settings.models.active_models.

    E37-03: Wires XGBoost into the production ensemble alongside Poisson.

    Strategy per model type:

    **Poisson** — instantiated fresh; trained at prediction time each morning.
    Training Poisson is fast (< 1 s), so no pkl caching needed.

    **XGBoost** — loaded from ``data/models/xgboost_v1.pkl`` to avoid
    retraining cost in the morning pipeline.  If the pkl file is missing
    (e.g., ``run train`` has never been run), the model is skipped with
    a WARNING so the pipeline can fall back to Poisson-only gracefully.
    Run ``python run_pipeline.py train`` to build / refresh the pkl.

    Returns
    -------
    dict
        Mapping of ``model_name`` (str, e.g. "poisson_v1") → instantiated
        model object.  Missing or failed models are absent from the dict.

    Raises
    ------
    Nothing — all errors are logged as warnings to preserve pipeline
    resilience.  An empty dict is returned only if config is unreadable.
    """
    from src.config import config as _cfg
    from src.models.poisson import PoissonModel
    from src.models.xgboost_model import XGBoostModel

    try:
        active = list(_cfg.settings.models.active_models)
    except (AttributeError, TypeError):
        logger.warning("load_active_models: could not read active_models from config")
        return {"poisson_v1": PoissonModel()}

    loaded: Dict[str, Any] = {}

    for model_key in active:
        if model_key == "poisson_v1":
            # Poisson is always available — it retrains from scratch at prediction time.
            loaded[model_key] = PoissonModel()
            logger.debug("load_active_models: Poisson ready (will retrain at predict time)")

        elif model_key == "xgboost_v1":
            # XGBoost is pre-trained and loaded from disk.  If the pkl is missing,
            # skip it with a warning so the pipeline falls back to Poisson-only.
            pkl_path = Path("data/models/xgboost_v1.pkl")
            if not pkl_path.exists():
                logger.warning(
                    "WARNING: XGBoost model not found at %s, falling back to Poisson. "
                    "Run 'python run_pipeline.py train' to build the XGBoost model.",
                    pkl_path,
                )
                print(
                    f"  ⚠ WARNING: XGBoost model not found ({pkl_path}), "
                    "falling back to Poisson-only"
                )
            else:
                try:
                    xgb = XGBoostModel()
                    xgb.load(pkl_path)
                    loaded[model_key] = xgb
                    logger.info("load_active_models: XGBoost loaded from %s", pkl_path)
                except Exception as exc:
                    logger.warning(
                        "WARNING: Could not load XGBoost model from %s: %s. "
                        "Falling back to Poisson-only.",
                        pkl_path, exc,
                    )
                    print(
                        f"  ⚠ WARNING: XGBoost model failed to load ({exc}), "
                        "falling back to Poisson-only"
                    )
        else:
            logger.warning("load_active_models: unknown model key '%s', skipping", model_key)

    # Always ensure Poisson is present as the ultimate fallback
    if not loaded:
        logger.warning("load_active_models: no models loaded, using Poisson fallback")
        loaded["poisson_v1"] = PoissonModel()

    return loaded


# ============================================================================
# Save Predictions
# ============================================================================

def save_predictions(predictions: List[MatchPrediction]) -> Dict[str, int]:
    """Store model predictions in the database.

    For each ``MatchPrediction``:
      1. Serialise the 7×7 scoreline matrix to a JSON string
      2. Check if a prediction already exists for (match_id, model_name, model_version)
      3. If yes → update the existing row (upsert)
      4. If no → insert a new row

    This makes the function fully idempotent — calling it twice with the
    same predictions produces the same database state.

    Parameters
    ----------
    predictions : list[MatchPrediction]
        Predictions to store.  Each must have a valid ``match_id`` that
        exists in the ``matches`` table.

    Returns
    -------
    dict
        Summary with keys: ``"new"``, ``"updated"``, ``"total"``.
    """
    new_count = 0
    updated_count = 0

    for pred in predictions:
        # Serialise the scoreline matrix to JSON
        # The matrix is a list of 7 lists, each with 7 floats
        matrix_json = json.dumps(pred.scoreline_matrix)

        with get_session() as session:
            # Check for existing prediction (upsert logic)
            existing = session.query(Prediction).filter_by(
                match_id=pred.match_id,
                model_name=pred.model_name,
                model_version=pred.model_version,
            ).first()

            if existing:
                # Update existing prediction with new values
                existing.predicted_home_goals = pred.predicted_home_goals
                existing.predicted_away_goals = pred.predicted_away_goals
                existing.scoreline_matrix = matrix_json
                existing.prob_home_win = pred.prob_home_win
                existing.prob_draw = pred.prob_draw
                existing.prob_away_win = pred.prob_away_win
                existing.prob_over_25 = pred.prob_over_25
                existing.prob_under_25 = pred.prob_under_25
                existing.prob_over_15 = pred.prob_over_15
                existing.prob_under_15 = pred.prob_under_15
                existing.prob_over_35 = pred.prob_over_35
                existing.prob_under_35 = pred.prob_under_35
                existing.prob_btts_yes = pred.prob_btts_yes
                existing.prob_btts_no = pred.prob_btts_no
                updated_count += 1
                logger.debug(
                    "Updated prediction for match=%d, model=%s",
                    pred.match_id, pred.model_name,
                )
            else:
                # Insert new prediction
                row = Prediction(
                    match_id=pred.match_id,
                    model_name=pred.model_name,
                    model_version=pred.model_version,
                    predicted_home_goals=pred.predicted_home_goals,
                    predicted_away_goals=pred.predicted_away_goals,
                    scoreline_matrix=matrix_json,
                    prob_home_win=pred.prob_home_win,
                    prob_draw=pred.prob_draw,
                    prob_away_win=pred.prob_away_win,
                    prob_over_25=pred.prob_over_25,
                    prob_under_25=pred.prob_under_25,
                    prob_over_15=pred.prob_over_15,
                    prob_under_15=pred.prob_under_15,
                    prob_over_35=pred.prob_over_35,
                    prob_under_35=pred.prob_under_35,
                    prob_btts_yes=pred.prob_btts_yes,
                    prob_btts_no=pred.prob_btts_no,
                )
                session.add(row)
                new_count += 1
                logger.debug(
                    "Saved prediction for match=%d, model=%s",
                    pred.match_id, pred.model_name,
                )

    summary = {
        "new": new_count,
        "updated": updated_count,
        "total": len(predictions),
    }
    logger.info(
        "save_predictions: Stored %d predictions (%d new, %d updated)",
        summary["total"], summary["new"], summary["updated"],
    )
    return summary


# ============================================================================
# Get Predictions for a Match
# ============================================================================

def get_predictions(
    match_id: int,
    model_name: Optional[str] = None,
) -> List[MatchPrediction]:
    """Retrieve predictions for a match from the database.

    Returns ``MatchPrediction`` objects with the scoreline matrix
    deserialised from JSON back into a Python list of lists.

    Parameters
    ----------
    match_id : int
        Database ID of the match.
    model_name : str, optional
        If provided, only return predictions from this model.
        If None, return predictions from all models.

    Returns
    -------
    list[MatchPrediction]
        Predictions for the match, ordered by model_name.
        Empty list if no predictions found.
    """
    with get_session() as session:
        query = session.query(Prediction).filter_by(match_id=match_id)

        if model_name is not None:
            query = query.filter_by(model_name=model_name)

        rows = query.order_by(Prediction.model_name).all()

        # Convert ORM objects to MatchPrediction dataclasses
        # Must do this inside the session context while objects are attached
        predictions = [_row_to_prediction(row) for row in rows]

    return predictions


# ============================================================================
# Get Latest Predictions for Upcoming Matches
# ============================================================================

def get_latest_predictions(
    league_id: Optional[int] = None,
) -> List[MatchPrediction]:
    """Retrieve the most recent prediction for each upcoming match.

    "Upcoming" means matches with status = 'scheduled' (not yet played).
    For each match, returns the prediction with the most recent
    ``created_at`` timestamp.  If a match has predictions from multiple
    models, only the most recent one is returned.

    This is used by the dashboard and daily email to show current
    predictions for upcoming fixtures.

    Parameters
    ----------
    league_id : int, optional
        If provided, only return predictions for matches in this league.
        If None, return predictions across all leagues.

    Returns
    -------
    list[MatchPrediction]
        One prediction per upcoming match, most recent first.
        Empty list if no predictions found.
    """
    with get_session() as session:
        # Start with upcoming matches
        match_query = session.query(Match.id).filter(
            Match.status == "scheduled",
        )
        if league_id is not None:
            match_query = match_query.filter(Match.league_id == league_id)

        upcoming_match_ids = [row[0] for row in match_query.all()]

        if not upcoming_match_ids:
            logger.info("get_latest_predictions: No upcoming matches found")
            return []

        # For each upcoming match, get the most recent prediction.
        # We use a subquery approach: for each match_id, find the
        # prediction with the latest created_at.
        predictions = []
        for mid in upcoming_match_ids:
            latest = (
                session.query(Prediction)
                .filter_by(match_id=mid)
                .order_by(desc(Prediction.created_at))
                .first()
            )
            if latest is not None:
                predictions.append(_row_to_prediction(latest))

    logger.info(
        "get_latest_predictions: Found %d predictions for %d upcoming matches",
        len(predictions), len(upcoming_match_ids),
    )
    return predictions


# ============================================================================
# Internal Helpers
# ============================================================================

def _row_to_prediction(row: Prediction) -> MatchPrediction:
    """Convert a database Prediction row to a MatchPrediction dataclass.

    Deserialises the scoreline_matrix from its JSON string representation
    back into a Python list of lists (7×7 matrix of floats).
    """
    # Parse the JSON scoreline matrix back into a list of lists
    # Each cell is a float representing the probability of that scoreline
    matrix = json.loads(row.scoreline_matrix)

    return MatchPrediction(
        match_id=row.match_id,
        model_name=row.model_name,
        model_version=row.model_version,
        predicted_home_goals=row.predicted_home_goals,
        predicted_away_goals=row.predicted_away_goals,
        scoreline_matrix=matrix,
        prob_home_win=row.prob_home_win,
        prob_draw=row.prob_draw,
        prob_away_win=row.prob_away_win,
        prob_over_25=row.prob_over_25,
        prob_under_25=row.prob_under_25,
        prob_over_15=row.prob_over_15,
        prob_under_15=row.prob_under_15,
        prob_over_35=row.prob_over_35,
        prob_under_35=row.prob_under_35,
        prob_btts_yes=row.prob_btts_yes,
        prob_btts_no=row.prob_btts_no,
    )
