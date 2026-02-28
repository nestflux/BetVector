"""
BetVector — Value Finder (E6-01)
=================================
Compares model probabilities against bookmaker odds to identify value bets
— situations where our model believes an outcome is more likely than the
bookmaker's price implies.

What is a Value Bet?
--------------------
A **value bet** exists when your estimated probability of an outcome is
higher than the bookmaker's **implied probability**.  You don't need to
think the team will win — you need to think the price is wrong.

Example:
  - Model says Arsenal has a 55% chance of winning (prob_home_win = 0.55)
  - Bet365 offers Arsenal to win at decimal odds of 2.10
  - Implied probability = 1.0 / 2.10 = 47.6%
  - Edge = 55.0% - 47.6% = 7.4%  (positive edge = value!)
  - Expected Value = (0.55 × 2.10) - 1.0 = +15.5% profit per unit

If we bet on enough positive-edge situations, the law of large numbers
means we should profit in the long run, even though individual bets
frequently lose.

What is the Overround (Vig)?
-----------------------------
Bookmakers don't offer fair odds.  For a 1X2 market (home/draw/away),
the implied probabilities will sum to something like 105–110% instead
of 100%.  The excess is the bookmaker's guaranteed profit margin.
Example: home 47.6% + draw 28.6% + away 28.6% = 104.8%.  That extra
4.8% is the **overround** or **vig** (vigorish).

Confidence Tiers
----------------
Each value bet is tagged with a confidence level based on edge size:
  - **high** — edge >= 10%: The bookmaker is substantially mispricing this
  - **medium** — 5% <= edge < 10%: Clear value, standard betting range
  - **low** — edge < 5%: Marginal value, may not survive the overround

Master Plan refs: MP §4 Value Detection, MP §7 Value Finder Interface,
                  MP §6 value_bets table, MP §12 Glossary
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.database.db import get_session
from src.database.models import (
    Match,
    Odds,
    Prediction,
    Team,
    ValueBet as ValueBetORM,
)
from src.models.storage import get_predictions

logger = logging.getLogger(__name__)

# ============================================================================
# Market → Prediction Probability Mapping
# ============================================================================
# Maps (market_type, selection) to the corresponding probability field
# on the MatchPrediction / Prediction object.
#
# This is THE mapping that connects bookmaker markets to model output.
# When a bookmaker offers odds on "1X2 → home", we look up the model's
# prob_home_win.  When they offer "OU25 → over", we use prob_over_25.

MARKET_TO_PROB: Dict[Tuple[str, str], str] = {
    # 1X2 market (match result)
    ("1X2", "home"): "prob_home_win",
    ("1X2", "draw"): "prob_draw",
    ("1X2", "away"): "prob_away_win",
    # Over/Under 2.5 goals
    ("OU25", "over"): "prob_over_25",
    ("OU25", "under"): "prob_under_25",
    # Over/Under 1.5 goals
    ("OU15", "over"): "prob_over_15",
    ("OU15", "under"): "prob_under_15",
    # Over/Under 3.5 goals
    ("OU35", "over"): "prob_over_35",
    ("OU35", "under"): "prob_under_35",
    # Both Teams To Score
    ("BTTS", "yes"): "prob_btts_yes",
    ("BTTS", "no"): "prob_btts_no",
}

# Human-readable market names for explanation strings
MARKET_DISPLAY: Dict[str, str] = {
    "1X2": "Match Result",
    "OU25": "Over/Under 2.5 Goals",
    "OU15": "Over/Under 1.5 Goals",
    "OU35": "Over/Under 3.5 Goals",
    "BTTS": "Both Teams To Score",
}

SELECTION_DISPLAY: Dict[Tuple[str, str], str] = {
    ("1X2", "home"): "Home Win",
    ("1X2", "draw"): "Draw",
    ("1X2", "away"): "Away Win",
    ("OU25", "over"): "Over 2.5 Goals",
    ("OU25", "under"): "Under 2.5 Goals",
    ("OU15", "over"): "Over 1.5 Goals",
    ("OU15", "under"): "Under 1.5 Goals",
    ("OU35", "over"): "Over 3.5 Goals",
    ("OU35", "under"): "Under 3.5 Goals",
    ("BTTS", "yes"): "BTTS Yes",
    ("BTTS", "no"): "BTTS No",
}

# Confidence tiers based on edge size (MP §7)
CONFIDENCE_HIGH_THRESHOLD = 0.10   # 10% edge → high confidence
CONFIDENCE_MEDIUM_THRESHOLD = 0.05  # 5% edge → medium confidence


# ============================================================================
# ValueBet Dataclass (in-memory representation)
# ============================================================================

@dataclass
class ValueBetResult:
    """In-memory value bet result, returned by find_value_bets().

    This is the Python-side representation before/after database storage.
    Matches the fields in the value_bets ORM model.
    """
    match_id: int
    prediction_id: int
    bookmaker: str
    market_type: str
    selection: str
    model_prob: float
    bookmaker_odds: float
    implied_prob: float
    edge: float
    expected_value: float
    confidence: str
    explanation: str


# ============================================================================
# Value Finder
# ============================================================================

class ValueFinder:
    """Compares model predictions to bookmaker odds to find value bets.

    For each match, for each market type, for each bookmaker:
      1. Look up the model's probability for that outcome
      2. Calculate the bookmaker's implied probability from their odds
      3. Compute the edge (model_prob - implied_prob)
      4. If edge >= threshold, flag it as a value bet

    The finder also generates a human-readable explanation for each
    value bet, describing why the model disagrees with the bookmaker.
    """

    def find_value_bets(
        self,
        match_id: int,
        edge_threshold: float = 0.05,
        model_name: Optional[str] = None,
    ) -> List[ValueBetResult]:
        """Find value bets for a specific match.

        Compares the model's predicted probabilities against all available
        bookmaker odds for this match.  Returns value bets where the edge
        (model_prob - implied_prob) meets or exceeds the threshold.

        Parameters
        ----------
        match_id : int
            Database ID of the match to analyse.
        edge_threshold : float
            Minimum edge required to flag a value bet.
            Default 0.05 (5%).  Configurable via user settings.
        model_name : str, optional
            If provided, only use predictions from this model.
            If None, use the most recent prediction for this match.

        Returns
        -------
        list[ValueBetResult]
            Value bets found, sorted by edge descending (best first).
            Empty list if no value bets meet the threshold.
        """
        # Get the prediction for this match
        predictions = get_predictions(match_id, model_name=model_name)
        if not predictions:
            logger.info(
                "find_value_bets: No predictions for match %d", match_id,
            )
            return []

        # Use the first prediction (if model_name is None, get_predictions
        # returns all models sorted by name — use the first one)
        pred = predictions[0]

        # Get the prediction_id from the database (needed for FK)
        prediction_id = self._get_prediction_id(
            match_id, pred.model_name, pred.model_version,
        )
        if prediction_id is None:
            logger.warning(
                "find_value_bets: Prediction record not found in DB for "
                "match=%d, model=%s", match_id, pred.model_name,
            )
            return []

        # Get team names for explanation strings
        home_team, away_team = self._get_team_names(match_id)

        # Get all bookmaker odds for this match
        odds_list = self._get_match_odds(match_id)
        if not odds_list:
            logger.info(
                "find_value_bets: No odds available for match %d", match_id,
            )
            return []

        # Compare each odds entry against the model prediction
        value_bets: List[ValueBetResult] = []

        for odds_row in odds_list:
            # Look up which model probability corresponds to this market+selection
            key = (odds_row["market_type"], odds_row["selection"])
            prob_field = MARKET_TO_PROB.get(key)

            if prob_field is None:
                # Market/selection not supported (e.g., Asian Handicap)
                continue

            # Get the model's probability for this outcome
            model_prob = getattr(pred, prob_field, None)
            if model_prob is None:
                continue

            # Calculate implied probability from bookmaker odds
            # Decimal odds of 2.10 → implied prob = 1/2.10 = 0.4762
            # This implied probability INCLUDES the bookmaker's margin (vig)
            bookmaker_odds = odds_row["odds_decimal"]
            implied_prob = 1.0 / bookmaker_odds

            # Calculate edge: how much more likely we think it is than the bookie
            # Positive edge = the bookmaker is underpricing this outcome
            edge = model_prob - implied_prob

            # Only flag as value bet if edge meets the threshold
            if edge < edge_threshold:
                continue

            # Calculate Expected Value (EV)
            # EV = (model_prob × odds) - 1.0
            # Positive EV means profitable long-term
            # Example: 0.55 probability × 2.10 odds = 1.155 → EV = +15.5%
            expected_value = (model_prob * bookmaker_odds) - 1.0

            # Assign confidence tier
            confidence = _classify_confidence(edge)

            # Generate human-readable explanation
            explanation = _build_explanation(
                home_team=home_team,
                away_team=away_team,
                market_type=odds_row["market_type"],
                selection=odds_row["selection"],
                model_prob=model_prob,
                implied_prob=implied_prob,
                edge=edge,
                bookmaker=odds_row["bookmaker"],
                bookmaker_odds=bookmaker_odds,
            )

            value_bets.append(ValueBetResult(
                match_id=match_id,
                prediction_id=prediction_id,
                bookmaker=odds_row["bookmaker"],
                market_type=odds_row["market_type"],
                selection=odds_row["selection"],
                model_prob=round(model_prob, 6),
                bookmaker_odds=bookmaker_odds,
                implied_prob=round(implied_prob, 6),
                edge=round(edge, 6),
                expected_value=round(expected_value, 6),
                confidence=confidence,
                explanation=explanation,
            ))

        # Sort by edge descending — best value first
        value_bets.sort(key=lambda vb: vb.edge, reverse=True)

        logger.info(
            "find_value_bets: Found %d value bets for match %d "
            "(threshold=%.1f%%)",
            len(value_bets), match_id, edge_threshold * 100,
        )
        return value_bets

    def save_value_bets(
        self,
        value_bets: List[ValueBetResult],
    ) -> Dict[str, int]:
        """Store value bets in the database.

        Inserts each value bet into the ``value_bets`` table.  The unique
        constraint on (match_id, market_type, selection, bookmaker, detected_at)
        prevents exact duplicates within the same second.

        Parameters
        ----------
        value_bets : list[ValueBetResult]
            Value bets to store.

        Returns
        -------
        dict
            Summary with keys: ``"new"``, ``"skipped"``, ``"total"``.
        """
        new_count = 0
        skipped_count = 0

        for vb in value_bets:
            with get_session() as session:
                try:
                    row = ValueBetORM(
                        match_id=vb.match_id,
                        prediction_id=vb.prediction_id,
                        bookmaker=vb.bookmaker,
                        market_type=vb.market_type,
                        selection=vb.selection,
                        model_prob=vb.model_prob,
                        bookmaker_odds=vb.bookmaker_odds,
                        implied_prob=vb.implied_prob,
                        edge=vb.edge,
                        expected_value=vb.expected_value,
                        confidence=vb.confidence,
                        explanation=vb.explanation,
                    )
                    session.add(row)
                    session.flush()
                    new_count += 1
                except Exception:
                    # Likely a unique constraint violation (duplicate)
                    session.rollback()
                    skipped_count += 1

        summary = {
            "new": new_count,
            "skipped": skipped_count,
            "total": len(value_bets),
        }
        logger.info(
            "save_value_bets: Stored %d value bets (%d new, %d skipped)",
            summary["total"], summary["new"], summary["skipped"],
        )
        return summary

    # --- Internal helpers ---------------------------------------------------

    @staticmethod
    def _get_prediction_id(
        match_id: int,
        model_name: str,
        model_version: str,
    ) -> Optional[int]:
        """Look up the database prediction ID for a match + model combo."""
        with get_session() as session:
            row = session.query(Prediction).filter_by(
                match_id=match_id,
                model_name=model_name,
                model_version=model_version,
            ).first()
            return row.id if row else None

    @staticmethod
    def _get_team_names(match_id: int) -> Tuple[str, str]:
        """Get the home and away team names for a match."""
        with get_session() as session:
            match = session.query(Match).filter_by(id=match_id).first()
            if match is None:
                return ("Unknown", "Unknown")

            home = session.query(Team).filter_by(id=match.home_team_id).first()
            away = session.query(Team).filter_by(id=match.away_team_id).first()

            home_name = home.name if home else "Unknown"
            away_name = away.name if away else "Unknown"

        return (home_name, away_name)

    @staticmethod
    def _get_match_odds(match_id: int) -> List[Dict]:
        """Fetch all bookmaker odds for a match.

        Returns a list of dicts with keys: bookmaker, market_type,
        selection, odds_decimal.
        """
        with get_session() as session:
            odds_rows = session.query(Odds).filter_by(
                match_id=match_id,
            ).all()

            return [
                {
                    "bookmaker": o.bookmaker,
                    "market_type": o.market_type,
                    "selection": o.selection,
                    "odds_decimal": o.odds_decimal,
                }
                for o in odds_rows
            ]


# ============================================================================
# Module-level helpers
# ============================================================================

def _classify_confidence(edge: float) -> str:
    """Assign a confidence tier based on edge magnitude.

    - **high** — edge >= 10%: The bookmaker is substantially mispricing this
    - **medium** — 5% <= edge < 10%: Clear value, standard betting range
    - **low** — edge < 5%: Marginal value, close to the noise level
    """
    if edge >= CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    elif edge >= CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    else:
        return "low"


def _build_explanation(
    home_team: str,
    away_team: str,
    market_type: str,
    selection: str,
    model_prob: float,
    implied_prob: float,
    edge: float,
    bookmaker: str,
    bookmaker_odds: float,
) -> str:
    """Generate a human-readable explanation for a value bet.

    Example output:
      "Arsenal vs Chelsea — Home Win: Model gives Arsenal a 55.0% chance
       of winning, but Bet365's odds of 2.10 imply only 47.6%.
       Edge: 7.4% (medium confidence)."
    """
    # Get human-readable labels
    key = (market_type, selection)
    selection_label = SELECTION_DISPLAY.get(key, f"{market_type}/{selection}")
    confidence = _classify_confidence(edge)

    # Build the explanation
    return (
        f"{home_team} vs {away_team} — {selection_label}: "
        f"Model gives {model_prob:.1%} probability, "
        f"but {bookmaker}'s odds of {bookmaker_odds:.2f} imply only "
        f"{implied_prob:.1%}. "
        f"Edge: {edge:.1%} ({confidence} confidence)."
    )
