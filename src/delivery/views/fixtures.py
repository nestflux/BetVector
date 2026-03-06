"""
BetVector — Fixtures Page (E17-04, E24-03, E24-04, E26-03, E29-02, E30-01, E30-02, E31-01, E31-02)
==================================================================================
All upcoming matches across active leagues, grouped by date.
**E26-03: Now the dashboard landing page.**

Different from Today's Picks:
- **Today's Picks** = "here are the value bets the model likes"
- **Fixtures** = "here are ALL matches happening, with color-coded model
  indicators for every market"

E24-03: Added inline color-coded market indicators per fixture row.
E27-02: Expanded to 9 badges by adding Over/Under 1.5 goals.
For each scheduled match, 9 compact badges show the model's view:
Home/Draw/Away (1X2), Over/Under 1.5, Over/Under 2.5, BTTS Yes/No.
Colour coding:  green = strong edge, yellow = marginal, red = no edge,
grey = no data.

E24-04: Added pipeline health summary and diagnostic badges.
- Pipeline coverage bar at top: "X/Y fixtures have full prediction + odds data"
- Per-fixture diagnostic badges: "No pred", "No odds", "Full data", or "X VB"
- Blue left border for full-data fixtures, green for value bet fixtures
- Info tip when odds coverage is below 70% (explains bookmaker pricing window)

E26-03: Landing page enhancements:
- Top Picks banner: 3-5 highest-edge value bets (grouped by unique pick)
  shown prominently at the top of the page.
- Predicted score per fixture: "Model: X.X - X.X" inline below market badges.
- Fixtures page is now default=True in dashboard.py.

E29-02: Preferred bet ring + rich tooltips:
- The badge with the highest positive edge (≥ threshold) gets a green ring
  (box-shadow) marking it as the model's preferred bet.
- Tooltips enriched with model probability and confidence level from ValueBet

E30-01: Always-ring best badge + editable threshold:
- Every fixture's best badge gets a ring regardless of threshold
- Edge threshold slider (1-15%) lets users adjust what counts as "value"
- Legend dynamically updates to reflect the slider's threshold
- _find_best_badge() extracted as standalone helper for reuse
  records.  Best badge tooltip appends "★ Model's Pick".

E31-01: Badge ring redesign (Option C — owner-approved via mockup):
- Green DOUBLE ring + glow = genuine value bet (edge ≥ threshold)
- Blue ring = model's best guess (below threshold)
- ★ star prefix on best-pick badge label (e.g. "★ H" vs "H")
- Legend updated with two ring swatches: "★ Value Pick" / "★ Best Guess"

E31-02: Fixture card value highlight (two-level visual hierarchy):
- Upcoming: full green card border + glow for value-bet fixtures
- Recent Results: green border = VB profitable, red border = VB lost
- Non-value fixtures use default card styling (no coloured border)

E30-02: Historical fixtures view (Recent Results):
- "Upcoming" / "Recent Results" toggle at the top of the page
- Recent Results shows completed matches from the last 30 days
- Actual score (bold) vs predicted score (muted) with ✅/❌ indicator
- Summary metrics: Matches, Top Pick Accuracy, VB Record, VB Hit Rate
- Green/red/blue left borders based on VB profitability
- Market badges show pre-match edges with ring (same as upcoming)
- Graceful handling for missing predictions, odds, or results

Master Plan refs: MP §3 Flow 4 (Dashboard Exploration), MP §8 Design System
"""

from datetime import date, timedelta
from html import escape as html_escape
from itertools import groupby
from typing import Dict, List, Optional, Tuple

import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import aliased

from src.config import config
from src.database.db import get_session
from src.database.models import League, Match, Odds, Prediction, Team, ValueBet
from src.delivery.views._badge_helper import render_team_badge


# ============================================================================
# Design tokens (MP §8)
# ============================================================================

COLOURS = {
    "bg": "#0D1117",
    "surface": "#161B22",
    "border": "#30363D",
    "text": "#E6EDF3",
    "text_secondary": "#8B949E",
    "green": "#3FB950",
    "red": "#F85149",
    "yellow": "#D29922",
    "blue": "#58A6FF",
    "grey": "#484F58",
}


# ============================================================================
# Edge thresholds — driven from config for consistency with ValueFinder.
# Green = edge at or above the value threshold (worth betting on).
# Yellow = positive edge but below threshold (marginal — model slightly
#   favours the selection but not enough to recommend a bet).
# Red = no edge or negative edge (bookmaker price is fair or better).
# Grey = no data available (odds or prediction missing).
# ============================================================================

try:
    _config_edge_threshold = float(config.settings.value_betting.edge_threshold)
except (AttributeError, TypeError, ValueError):
    _config_edge_threshold = 0.05  # 5% default


def _edge_colour(edge: Optional[float], threshold: float = 0.05) -> str:
    """Return a hex colour based on the edge value.

    E30-01: Now accepts a ``threshold`` parameter so the Fixtures page
    slider can dynamically control what counts as a "value" badge.

    Parameters
    ----------
    edge : float or None
        Model probability minus bookmaker implied probability.
        None means data is unavailable.
    threshold : float
        Minimum edge to qualify as a value bet (green badge).
        Defaults to 0.05 (5%).  Overridden by the user's slider.

    Returns
    -------
    str
        Hex colour code for the badge background.
    """
    if edge is None:
        return COLOURS["grey"]
    if edge >= threshold:
        return COLOURS["green"]
    if edge > 0:
        return COLOURS["yellow"]
    return COLOURS["red"]


# ============================================================================
# Market badge definitions — the 9 selections shown per fixture.
# Each tuple: (market_type_db, selection_db, badge_label)
# These correspond to ValueBet.market_type and ValueBet.selection values.
# Order: 1X2 → O/U 1.5 → O/U 2.5 → BTTS (natural threshold progression)
# ============================================================================

MARKET_BADGES = [
    ("1X2", "home", "H"),
    ("1X2", "draw", "D"),
    ("1X2", "away", "A"),
    ("OU15", "over", "O1.5"),
    ("OU15", "under", "U1.5"),
    ("OU25", "over", "O2.5"),
    ("OU25", "under", "U2.5"),
    ("BTTS", "yes", "BTTS Y"),
    ("BTTS", "no", "BTTS N"),
]

# Map Prediction attributes to (market_type, selection) for probability lookups.
# The Prediction model stores derived probabilities from the scoreline matrix.
PRED_PROB_MAP = {
    ("1X2", "home"): "prob_home_win",
    ("1X2", "draw"): "prob_draw",
    ("1X2", "away"): "prob_away_win",
    ("OU15", "over"): "prob_over_15",
    ("OU15", "under"): "prob_under_15",
    ("OU25", "over"): "prob_over_25",
    ("OU25", "under"): "prob_under_25",
    ("BTTS", "yes"): "prob_btts_yes",
    ("BTTS", "no"): "prob_btts_no",
}


# ============================================================================
# Data Loading
# ============================================================================

def get_all_upcoming_fixtures(days_ahead: int = 14) -> List[Dict]:
    """Fetch all upcoming scheduled matches with prediction + odds data.

    For each match, loads the Prediction record and the best available odds
    per market selection to compute edge.  Returns a list ready for rendering
    with color-coded market indicators.

    Parameters
    ----------
    days_ahead : int
        How many days into the future to look (default 14).

    Returns
    -------
    list[dict]
        Fixture data enriched with team names, league, value bet count,
        and per-market edge values.
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    today_str = date.today().isoformat()
    cutoff_str = (date.today() + timedelta(days=days_ahead)).isoformat()

    with get_session() as session:
        matches = (
            session.query(Match, HomeTeam, AwayTeam, League)
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .join(League, Match.league_id == League.id)
            .filter(
                Match.status == "scheduled",
                Match.date >= today_str,
                Match.date <= cutoff_str,
            )
            .order_by(Match.date.asc(), Match.kickoff_time.asc())
            .all()
        )

        results = []
        for match, home_team, away_team, league in matches:
            # E29-02: Load all ValueBet rows up front — we need them for
            # both the count (diagnostic badges) and the per-market info
            # (tooltip enrichment + model's pick ring).  One query instead
            # of a separate COUNT + SELECT.
            vb_rows = (
                session.query(ValueBet)
                .filter_by(match_id=match.id)
                .all()
            )
            vb_count = len(vb_rows)

            # Load prediction for this match (most recent model)
            prediction = (
                session.query(Prediction)
                .filter_by(match_id=match.id)
                .order_by(Prediction.created_at.desc())
                .first()
            )

            # Check if this match has ANY odds loaded (any source)
            odds_count = (
                session.query(Odds)
                .filter_by(match_id=match.id)
                .count()
            )

            # Compute per-market edges by comparing model probs to best odds.
            # For each of the 9 market selections, we need:
            #   1. model_prob from Prediction attributes
            #   2. best available odds from the Odds table
            #   3. edge = model_prob - (1.0 / odds)
            market_edges = {}
            for market_type, selection, _label in MARKET_BADGES:
                edge = _compute_edge(
                    session, match.id, prediction, market_type, selection,
                )
                market_edges[(market_type, selection)] = edge

            # E26-03: Extract predicted goals for inline display.
            # These come from the Poisson model's expected goals output.
            pred_home_goals = None
            pred_away_goals = None
            if prediction is not None:
                pred_home_goals = getattr(prediction, "predicted_home_goals", None)
                pred_away_goals = getattr(prediction, "predicted_away_goals", None)

            # E29-02: Build per-market model_prob and confidence lookup from
            # the already-loaded ValueBet rows.  This enriches the market
            # badges with tooltip data (model probability, confidence level)
            # and identifies the model's preferred bet (ring highlight).
            market_vb_info: Dict[Tuple[str, str], Dict] = {}
            for vb in vb_rows:
                key = (vb.market_type, vb.selection)
                if key not in market_vb_info or vb.edge > market_vb_info[key]["edge"]:
                    market_vb_info[key] = {
                        "model_prob": vb.model_prob,
                        "confidence": vb.confidence,
                        "edge": vb.edge,
                    }

            # E29-02: Extract model probabilities from the Prediction record
            # for badges that don't have ValueBet entries (e.g., negative edge
            # markets still show model prob in their tooltip).
            market_probs: Dict[Tuple[str, str], float] = {}
            if prediction is not None:
                for (mt, sel), attr in PRED_PROB_MAP.items():
                    val = getattr(prediction, attr, None)
                    if val is not None:
                        market_probs[(mt, sel)] = val

            results.append({
                "match_id": match.id,
                "date": match.date,
                "kickoff": html_escape(match.kickoff_time or "TBD"),
                "home_team": home_team.name,  # Not pre-escaped; badge helper handles escaping
                "away_team": away_team.name,
                "home_team_id": home_team.id,
                "away_team_id": away_team.id,
                "league": html_escape(league.short_name),
                "league_name": html_escape(league.name),
                "has_value_bets": vb_count > 0,
                "value_bet_count": vb_count,
                "has_prediction": prediction is not None,
                "has_odds": odds_count > 0,
                "odds_count": odds_count,
                "market_edges": market_edges,
                "market_vb_info": market_vb_info,
                "market_probs": market_probs,
                "predicted_home_goals": pred_home_goals,
                "predicted_away_goals": pred_away_goals,
            })

    return results


# ── Actual outcome maps (E30-02) ───────────────────────────────────────
# Given a final score, determine the correct selection for each market.
# Used to compare the model's best pick against reality.

def _determine_actual_outcomes(
    home_goals: int, away_goals: int,
) -> Dict[str, str]:
    """Map a finished score to the correct selection per market.

    Returns a dict keyed by market_type → winning selection, e.g.
    ``{"1X2": "home", "OU15": "over", "OU25": "under", "BTTS": "no"}``.

    Parameters
    ----------
    home_goals, away_goals : int
        Final score of the match.

    Returns
    -------
    dict[str, str]
        Market type → actual winning selection.
    """
    total = home_goals + away_goals
    both_scored = home_goals > 0 and away_goals > 0

    # 1X2: who won?
    if home_goals > away_goals:
        result_1x2 = "home"
    elif home_goals == away_goals:
        result_1x2 = "draw"
    else:
        result_1x2 = "away"

    return {
        "1X2": result_1x2,
        "OU15": "over" if total > 1.5 else "under",
        "OU25": "over" if total > 2.5 else "under",
        "BTTS": "yes" if both_scored else "no",
    }


def get_recent_results(days_back: int = 30) -> List[Dict]:
    """Fetch completed matches from the last ``days_back`` days.

    E30-02: Parallel to ``get_all_upcoming_fixtures()`` but queries
    finished matches.  Enriches each result with:
    - Actual score (home_goals, away_goals)
    - Predicted score (from Prediction record)
    - Per-market edges (same computation as upcoming fixtures)
    - Model's best pick correctness (did the top pick match reality?)
    - Value bet profitability (did any VB selection match reality?)

    Parameters
    ----------
    days_back : int
        How many days into the past to look (default 30).

    Returns
    -------
    list[dict]
        Recent results enriched with prediction and accuracy data,
        sorted by date descending (most recent first).
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    today_str = date.today().isoformat()
    cutoff_str = (date.today() - timedelta(days=days_back)).isoformat()

    with get_session() as session:
        matches = (
            session.query(Match, HomeTeam, AwayTeam, League)
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .join(League, Match.league_id == League.id)
            .filter(
                Match.status == "finished",
                Match.date >= cutoff_str,
                Match.date <= today_str,
                Match.home_goals.isnot(None),
            )
            .order_by(Match.date.desc(), Match.kickoff_time.desc())
            .all()
        )

        results = []
        for match, home_team, away_team, league in matches:
            # Load ValueBet rows (same pattern as upcoming fixtures)
            vb_rows = (
                session.query(ValueBet)
                .filter_by(match_id=match.id)
                .all()
            )
            vb_count = len(vb_rows)

            # Load prediction (most recent model)
            prediction = (
                session.query(Prediction)
                .filter_by(match_id=match.id)
                .order_by(Prediction.created_at.desc())
                .first()
            )

            # Check odds availability
            odds_count = (
                session.query(Odds)
                .filter_by(match_id=match.id)
                .count()
            )

            # Compute per-market edges (same as upcoming)
            market_edges: Dict[Tuple[str, str], Optional[float]] = {}
            for market_type, selection, _label in MARKET_BADGES:
                edge = _compute_edge(
                    session, match.id, prediction, market_type, selection,
                )
                market_edges[(market_type, selection)] = edge

            # ValueBet info for tooltips (same as upcoming)
            market_vb_info: Dict[Tuple[str, str], Dict] = {}
            for vb in vb_rows:
                key = (vb.market_type, vb.selection)
                if key not in market_vb_info or vb.edge > market_vb_info[key]["edge"]:
                    market_vb_info[key] = {
                        "model_prob": vb.model_prob,
                        "confidence": vb.confidence,
                        "edge": vb.edge,
                    }

            # Model probabilities from Prediction (for non-VB badges)
            market_probs: Dict[Tuple[str, str], float] = {}
            if prediction is not None:
                for (mt, sel), attr in PRED_PROB_MAP.items():
                    val = getattr(prediction, attr, None)
                    if val is not None:
                        market_probs[(mt, sel)] = val

            # Predicted goals
            pred_home_goals = None
            pred_away_goals = None
            if prediction is not None:
                pred_home_goals = getattr(prediction, "predicted_home_goals", None)
                pred_away_goals = getattr(prediction, "predicted_away_goals", None)

            # ── Actual outcome analysis ─────────────────────────────────
            actual_outcomes = _determine_actual_outcomes(
                match.home_goals, match.away_goals,
            )

            # Did the model's top pick (highest edge badge) match reality?
            best_key, best_edge = _find_best_badge(market_edges)
            top_pick_correct: Optional[bool] = None
            if best_key is not None:
                best_market, best_sel = best_key
                actual_sel = actual_outcomes.get(best_market)
                if actual_sel is not None:
                    top_pick_correct = (best_sel == actual_sel)

            # Did any value bet selection match reality?
            # A value bet is "profitable" if its selection was the actual outcome.
            vb_profitable: Optional[bool] = None
            vb_wins = 0
            vb_total = 0
            if vb_rows:
                # Deduplicate by (market_type, selection) — same logic as Top Picks
                seen_vb_keys: set = set()
                for vb in vb_rows:
                    vb_key = (vb.market_type, vb.selection)
                    if vb_key in seen_vb_keys:
                        continue
                    seen_vb_keys.add(vb_key)
                    actual_sel = actual_outcomes.get(vb.market_type)
                    if actual_sel is not None:
                        vb_total += 1
                        if vb.selection == actual_sel:
                            vb_wins += 1
                vb_profitable = vb_wins > 0 if vb_total > 0 else None

            results.append({
                "match_id": match.id,
                "date": match.date,
                "kickoff": html_escape(match.kickoff_time or "FT"),
                "home_team": home_team.name,
                "away_team": away_team.name,
                "home_team_id": home_team.id,
                "away_team_id": away_team.id,
                "league": html_escape(league.short_name),
                "league_name": html_escape(league.name),
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
                "has_value_bets": vb_count > 0,
                "value_bet_count": vb_count,
                "has_prediction": prediction is not None,
                "has_odds": odds_count > 0,
                "odds_count": odds_count,
                "market_edges": market_edges,
                "market_vb_info": market_vb_info,
                "market_probs": market_probs,
                "predicted_home_goals": pred_home_goals,
                "predicted_away_goals": pred_away_goals,
                "top_pick_correct": top_pick_correct,
                "vb_profitable": vb_profitable,
                "vb_wins": vb_wins,
                "vb_total": vb_total,
            })

    return results


def _compute_edge(
    session,
    match_id: int,
    prediction: Optional[Prediction],
    market_type: str,
    selection: str,
) -> Optional[float]:
    """Compute the edge for a specific market selection.

    Edge = model_prob - implied_prob, where implied_prob = 1/odds.
    Returns None if either the prediction or odds are unavailable.

    Parameters
    ----------
    session : Session
        Active DB session.
    match_id : int
        Match ID.
    prediction : Prediction or None
        The Prediction record.
    market_type : str
        Market type (e.g., "1X2", "BTTS", "OU25").
    selection : str
        Selection (e.g., "home", "draw", "over").

    Returns
    -------
    float or None
        Edge as a decimal (e.g., 0.08 for 8%), or None if data missing.
    """
    if prediction is None:
        return None

    # Get model probability from the Prediction attributes
    prob_attr = PRED_PROB_MAP.get((market_type, selection))
    if not prob_attr:
        return None
    model_prob = getattr(prediction, prob_attr, None)
    if model_prob is None:
        return None

    # Get the best available odds for this market + selection.
    # "Best" = highest odds (most generous to the bettor) because
    # higher odds mean lower implied probability, so the edge is larger.
    best_odds_row = (
        session.query(func.max(Odds.odds_decimal))
        .filter(
            Odds.match_id == match_id,
            Odds.market_type == market_type,
            Odds.selection == selection,
        )
        .scalar()
    )

    if not best_odds_row or best_odds_row <= 1.0:
        return None

    implied_prob = 1.0 / best_odds_row
    return model_prob - implied_prob


def get_top_picks(max_picks: int = 5) -> List[Dict]:
    """Fetch the highest-edge value bets across all upcoming fixtures.

    E26-03: Used for the Top Picks banner at the top of the Fixtures page.
    Groups by (match_id, market_type, selection) to avoid per-bookmaker
    duplication (same logic as picks.py E26-01).  Returns the top N picks
    sorted by edge descending.

    Parameters
    ----------
    max_picks : int
        Maximum number of top picks to return (default 5).

    Returns
    -------
    list[dict]
        Top value bet picks with team names, market, bookmaker, odds, edge.
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)
    today_str = date.today().isoformat()

    with get_session() as session:
        rows = (
            session.query(
                ValueBet, Match, League,
                HomeTeam.name, AwayTeam.name,
                HomeTeam.id, AwayTeam.id,
            )
            .join(Match, ValueBet.match_id == Match.id)
            .join(League, Match.league_id == League.id)
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .filter(
                Match.status == "scheduled",
                Match.date >= today_str,
            )
            .order_by(ValueBet.edge.desc())
            .all()
        )

        # Group by (match_id, market_type, selection) — keep highest edge per group.
        # HTML-escape all string values that will be rendered in templates
        # (consistent with get_all_upcoming_fixtures escaping pattern).
        grouped: Dict[tuple, Dict] = {}
        for vb, match, league, home_name, away_name, home_id, away_id in rows:
            key = (vb.match_id, vb.market_type, vb.selection)
            if key not in grouped or vb.edge > grouped[key]["edge"]:
                grouped[key] = {
                    "match_id": vb.match_id,
                    "home_team": home_name,  # Not pre-escaped; badge helper handles escaping
                    "away_team": away_name,
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "date": match.date,
                    "league": html_escape(league.short_name),
                    "market_type": html_escape(vb.market_type),
                    "selection": html_escape(vb.selection),
                    "bookmaker": html_escape(vb.bookmaker),
                    "bookmaker_odds": vb.bookmaker_odds,
                    "edge": vb.edge,
                    "confidence": vb.confidence,
                }

    # Sort by edge descending and take top N
    result = sorted(grouped.values(), key=lambda x: -x["edge"])
    return result[:max_picks]


# Market + selection display labels for the Top Picks banner
_SELECTION_LABELS = {
    ("1X2", "home"): "Home Win",
    ("1X2", "draw"): "Draw",
    ("1X2", "away"): "Away Win",
    ("OU25", "over"): "O2.5",
    ("OU25", "under"): "U2.5",
    ("OU15", "over"): "O1.5",
    ("OU15", "under"): "U1.5",
    ("OU35", "over"): "O3.5",
    ("OU35", "under"): "U3.5",
    ("BTTS", "yes"): "BTTS Y",
    ("BTTS", "no"): "BTTS N",
}


# ============================================================================
# Badge Rendering
# ============================================================================

def _find_best_badge(
    market_edges: Dict[Tuple[str, str], Optional[float]],
) -> Tuple[Optional[Tuple[str, str]], Optional[float]]:
    """Find the badge with the highest edge — the model's preferred pick.

    E30-01: Finds the best badge **regardless of threshold** — even negative
    edges are considered.  This ensures every fixture with edge data has a
    "Model's Pick" ring.  The ring *style* (green double vs blue) is
    determined separately based on whether the best edge meets the threshold.

    Parameters
    ----------
    market_edges : dict
        Keys are (market_type, selection) tuples, values are edge floats
        or None.

    Returns
    -------
    tuple
        ``(best_key, best_edge)`` where ``best_key`` is the (market_type,
        selection) tuple with the highest edge, and ``best_edge`` is the
        float.  Returns ``(None, None)`` if no edges are available.
    """
    best_key: Optional[Tuple[str, str]] = None
    best_edge: Optional[float] = None
    for (mt, sel), edge in market_edges.items():
        if edge is not None:
            if best_edge is None or edge > best_edge:
                best_edge = edge
                best_key = (mt, sel)
    return best_key, best_edge


def _render_market_badges(
    market_edges: Dict[Tuple[str, str], Optional[float]],
    market_vb_info: Optional[Dict[Tuple[str, str], Dict]] = None,
    market_probs: Optional[Dict[Tuple[str, str], float]] = None,
    threshold: float = 0.05,
) -> str:
    """Build HTML for the 9 color-coded market indicator badges.

    Each badge is a compact pill showing the selection label (H, D, A,
    O1.5, U1.5, O2.5, U2.5, BTTS Y, BTTS N) with a background colour
    indicating the model's edge.

    E29-02: Tooltips include model probability and confidence level.
    E30-01/E31-01: The best badge ALWAYS gets a ring — green double ring
    if it meets the threshold (value), blue ring if below (best guess).
    Threshold is now a runtime parameter driven by the user's slider.

    E32-04: Replaced native ``title`` tooltips with CSS-styled dark surface
    cards.  Hover reveals model probability, edge (colour-coded), confidence,
    and Model's Pick indicator.  Uses ``.bv-badge-wrap`` / ``.bv-tooltip``
    CSS classes injected at page level.

    Parameters
    ----------
    market_edges : dict
        Keys are (market_type, selection) tuples, values are edge floats
        or None.
    market_vb_info : dict, optional
        Per-market ValueBet data: {(market_type, selection): {"model_prob",
        "confidence", "edge"}}.
    market_probs : dict, optional
        Model probabilities from the Prediction record.
    threshold : float
        Minimum edge to qualify as a value bet.  Controls badge colour
        (green vs yellow) and ring style (green double vs blue).  Defaults
        to 0.05 (5%).  Overridden by the user's slider.

    Returns
    -------
    str
        HTML string of badge spans wrapped in tooltip containers.
    """
    _vb_info = market_vb_info or {}
    _probs = market_probs or {}

    # E30-01: Find the model's preferred bet — the badge with the highest
    # edge, regardless of sign or threshold.  Every fixture with edge data
    # gets a "Model's Pick" ring; the ring STYLE depends on threshold.
    best_key, best_edge = _find_best_badge(market_edges)

    badges = []
    for market_type, selection, label in MARKET_BADGES:
        key = (market_type, selection)
        edge = market_edges.get(key)
        bg = _edge_colour(edge, threshold=threshold)

        # --- Build CSS tooltip content (E32-04) ---
        # Each line is a formatted HTML fragment shown inside the styled
        # tooltip card on hover.  Replaces the old plain-text title attr.
        tooltip_lines: list[str] = []
        if edge is not None:
            edge_pct = edge * 100

            # Model probability — sourced from ValueBet first, then Prediction
            vb_data = _vb_info.get(key)
            prob = _probs.get(key)
            prob_val: float | None = None
            if vb_data and vb_data.get("model_prob") is not None:
                prob_val = vb_data["model_prob"]
            elif prob is not None:
                prob_val = prob

            if prob_val is not None:
                tooltip_lines.append(
                    f'<span style="color: #8B949E;">Model:</span> '
                    f'<span style="color: #E6EDF3; font-weight: 700;">'
                    f'{prob_val * 100:.0f}%</span>'
                )

            # Edge — colour-coded green (positive) or red (negative)
            edge_colour = COLOURS["green"] if edge_pct > 0 else COLOURS["red"]
            tooltip_lines.append(
                f'<span style="color: #8B949E;">Edge:</span> '
                f'<span style="color: {edge_colour}; font-weight: 700;">'
                f'{edge_pct:+.1f}%</span>'
            )

            # Confidence level (only for value bets with confidence data)
            if vb_data and vb_data.get("confidence"):
                conf = vb_data["confidence"].capitalize()
                conf_colour = (
                    COLOURS["green"] if conf == "High"
                    else COLOURS["yellow"] if conf == "Medium"
                    else "#8B949E"
                )
                tooltip_lines.append(
                    f'<span style="color: #8B949E;">Confidence:</span> '
                    f'<span style="color: {conf_colour}; font-weight: 600;">'
                    f'{conf}</span>'
                )

            # Model's Pick marker for the best badge
            if key == best_key:
                tooltip_lines.append(
                    f'<span style="color: {COLOURS["green"]};">'
                    f'\u2605 Model\u2019s Pick</span>'
                )
        else:
            tooltip_lines.append(
                '<span style="color: #8B949E;">No data</span>'
            )

        tooltip_html = "<br>".join(tooltip_lines)

        # --- Ring effect for the model's preferred bet (E31-01) ---
        # CSS box-shadow creates a ring without changing element size.
        # Two-tier system approved via owner mockup (Option C):
        #   Green DOUBLE ring + glow = genuine value bet (edge >= threshold)
        #   Blue ring = model's best guess (below threshold)
        ring_style = ""
        if key == best_key and best_edge is not None:
            if best_edge >= threshold:
                # Green double ring with glow — genuine value bet.
                # Two concentric rings (2px solid + 4px translucent) plus
                # outer glow make this unmistakable at a glance.
                ring_style = (
                    f"box-shadow: 0 0 0 2px {COLOURS['green']}, "
                    f"0 0 0 4px rgba(63, 185, 80, 0.35), "
                    f"0 0 10px rgba(63, 185, 80, 0.4); "
                )
            else:
                # Blue ring — model's best guess, below value threshold.
                # Blue (#58A6FF) is highly visible on the dark bg (#0D1117),
                # unlike the previous grey ring which was nearly invisible.
                ring_style = (
                    f"box-shadow: 0 0 0 2px {COLOURS['blue']}, "
                    f"0 0 6px rgba(88, 166, 255, 0.35); "
                )

        # Star prefix on the model's best pick for instant visual identification.
        # "★ H" is immediately recognisable vs plain "H" even at small sizes.
        display_label = f"\u2605 {label}" if key == best_key else label

        # E32-04: Wrap each badge in .bv-badge-wrap with a .bv-tooltip child.
        # The CSS classes are injected at page level (see _TOOLTIP_CSS below).
        badges.append(
            f'<span class="bv-badge-wrap">'
            f'<span class="bv-tooltip">{tooltip_html}</span>'
            f'<span style="'
            f"display: inline-block; padding: 2px 6px; margin: 0 2px; "
            f"border-radius: 4px; font-family: 'JetBrains Mono', monospace; "
            f"font-size: 10px; font-weight: 600; color: #fff; "
            f"background-color: {bg}; cursor: help; {ring_style}"
            f'">{display_label}</span>'
            f'</span>'
        )
    return "".join(badges)


# E32-04: CSS for styled tooltips on market badges.  Injected once at page
# level via st.markdown().  Uses a nested .bv-tooltip span inside each
# .bv-badge-wrap container — hover reveals the tooltip above the badge
# with a dark surface card and small arrow pointer.
_TOOLTIP_CSS = (
    '<style>'
    '.bv-badge-wrap { position: relative; display: inline-block; cursor: help; }'
    '.bv-badge-wrap .bv-tooltip {'
    '  visibility: hidden; opacity: 0;'
    '  position: absolute; bottom: calc(100% + 6px); left: 50%;'
    '  transform: translateX(-50%);'
    '  background-color: #161B22; border: 1px solid #30363D;'
    '  border-radius: 6px; padding: 6px 10px;'
    '  font-family: "JetBrains Mono", monospace; font-size: 11px;'
    '  color: #E6EDF3; white-space: normal; min-width: 120px; max-width: 200px;'
    '  z-index: 1000; pointer-events: none;'
    '  transition: opacity 0.15s ease-in-out, visibility 0.15s ease-in-out;'
    '  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);'
    '}'
    '.bv-badge-wrap .bv-tooltip::after {'
    '  content: ""; position: absolute; top: 100%; left: 50%;'
    '  transform: translateX(-50%);'
    '  border-width: 4px; border-style: solid;'
    '  border-color: #30363D transparent transparent transparent;'
    '}'
    '.bv-badge-wrap:hover .bv-tooltip { visibility: visible; opacity: 1; }'
    '</style>'
)


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Fixtures</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">'
    "All upcoming matches with predicted scores and color-coded model indicators"
    "</p>",
    unsafe_allow_html=True,
)
# E32-04: Inject CSS for styled tooltips on market badges.
st.markdown(_TOOLTIP_CSS, unsafe_allow_html=True)

# ── E30-02: View mode toggle ─────────────────────────────────────────────
# "Upcoming" (default) shows scheduled matches with Top Picks and pipeline health.
# "Recent Results" shows completed matches with actual vs predicted scores,
# correctness indicators, and accuracy metrics.
view_mode = st.radio(
    "View",
    ["Upcoming", "Recent Results"],
    horizontal=True,
    label_visibility="collapsed",
)

if view_mode == "Upcoming":
    # ══════════════════════════════════════════════════════════════════════
    # UPCOMING VIEW — scheduled matches (existing behaviour)
    # ══════════════════════════════════════════════════════════════════════

    # ── E26-03: Top Picks Banner ─────────────────────────────────────
    # Show the 3-5 highest-edge value bets as a compact banner.
    with st.spinner("Loading top picks..."):
        top_picks = get_top_picks(max_picks=5)

    if top_picks:
        st.markdown(
            f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
            f'font-weight: 700; color: {COLOURS["green"]}; text-transform: uppercase; '
            f'letter-spacing: 0.5px; margin-bottom: 8px;">'
            f'Top Picks</div>',
            unsafe_allow_html=True,
        )

        # Render each top pick as a compact inline card
        picks_html_parts = []
        for pick in top_picks:
            sel_label = _SELECTION_LABELS.get(
                (pick["market_type"], pick["selection"]),
                f'{pick["market_type"]}/{pick["selection"]}',
            )
            edge_pct = pick["edge"] * 100
            # Green if edge is at least 2× the configured threshold (strong pick),
            # yellow otherwise (still a value bet, but less emphatic).
            # _config_edge_threshold is loaded from config at module level (e.g. 0.05 = 5%).
            # Top Picks uses the *config* threshold, not the user's slider — system
            # picks are stable and shouldn't shift when the slider moves.
            _strong_edge_pct = _config_edge_threshold * 200  # 2× threshold as %
            edge_colour = COLOURS["green"] if edge_pct >= _strong_edge_pct else COLOURS["yellow"]
            conf_colour = (
                COLOURS["green"] if pick["confidence"] == "high"
                else COLOURS["yellow"] if pick["confidence"] == "medium"
                else COLOURS["grey"]
            )

            # Render badges beside team names in top picks (20px inline)
            tp_home = render_team_badge(pick["home_team_id"], pick["home_team"], size=20)
            tp_away = render_team_badge(pick["away_team_id"], pick["away_team"], size=20)

            picks_html_parts.append(
                f'<div style="background-color: {COLOURS["surface"]}; '
                f'border: 1px solid {COLOURS["border"]}; border-radius: 8px; '
                f'padding: 10px 14px; flex: 1 1 220px; min-width: 220px;">'
                f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
                f'font-weight: 600; color: {COLOURS["text"]}; margin-bottom: 4px;">'
                f'{tp_home} vs {tp_away}</div>'
                f'<div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">'
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]};">{sel_label}</span>'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                f'color: {COLOURS["text"]};">{pick["bookmaker_odds"]:.2f}</span>'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                f'font-weight: 700; color: {edge_colour};">+{edge_pct:.1f}%</span>'
                f'<span style="font-family: Inter, sans-serif; font-size: 10px; '
                f'color: {COLOURS["text_secondary"]};">{pick["bookmaker"]}</span>'
                f'<span style="display: inline-block; width: 8px; height: 8px; '
                f'border-radius: 50%; background-color: {conf_colour};"></span>'
                f'</div>'
                f'</div>'
            )

        st.markdown(
            f'<div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;">'
            f'{"".join(picks_html_parts)}'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        # Empty state: no value bets found across upcoming fixtures
        st.markdown(
            f'<div style="background-color: {COLOURS["surface"]}; '
            f'border: 1px solid {COLOURS["border"]}; border-radius: 8px; '
            f'padding: 14px 18px; margin-bottom: 16px; text-align: center;">'
            f'<span style="font-family: Inter, sans-serif; font-size: 13px; '
            f'color: {COLOURS["text_secondary"]};">'
            f'No value bets found across upcoming fixtures. '
            f'The pipeline will identify opportunities when odds are available.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ── E30-01: Dual sliders — days ahead + edge threshold ─────────────
    # Side-by-side controls: left = date range, right = value threshold.
    col_days, col_edge = st.columns(2)
    with col_days:
        days_ahead = st.slider(
            "Days ahead",
            min_value=7,
            max_value=28,
            value=14,
            step=7,
            help="How far ahead to show fixtures.",
        )
    with col_edge:
        edge_threshold_pct = st.slider(
            "Edge threshold (%)",
            min_value=1,
            max_value=15,
            value=int(_config_edge_threshold * 100),
            step=1,
            help=(
                "Minimum edge to colour a badge green (value bet). "
                "Lower it to see near-misses; raise it to be stricter."
            ),
        )
    # Convert percentage to decimal for internal use
    edge_threshold = edge_threshold_pct / 100.0

    # Legend — explains badge colours and ring indicators (E31-01).
    # Two ring styles: green double ring = value pick, blue ring = best guess.
    st.markdown(
        '<div style="font-family: Inter, sans-serif; font-size: 12px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px; '
        'display: flex; gap: 16px; flex-wrap: wrap; align-items: center;">'
        '<span style="font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; '
        'margin-right: 4px;">Legend:</span>'
        # Badge colour swatches (edge-based fill colours)
        f'<span><span style="display: inline-block; width: 10px; height: 10px; '
        f'border-radius: 2px; background-color: {COLOURS["green"]}; margin-right: 4px; '
        f'vertical-align: middle;"></span>Value (edge &ge; {edge_threshold_pct}%)</span>'
        f'<span><span style="display: inline-block; width: 10px; height: 10px; '
        f'border-radius: 2px; background-color: {COLOURS["yellow"]}; margin-right: 4px; '
        f'vertical-align: middle;"></span>Marginal (0–{edge_threshold_pct}%)</span>'
        f'<span><span style="display: inline-block; width: 10px; height: 10px; '
        f'border-radius: 2px; background-color: {COLOURS["red"]}; margin-right: 4px; '
        f'vertical-align: middle;"></span>No Value (&le; 0%)</span>'
        f'<span><span style="display: inline-block; width: 10px; height: 10px; '
        f'border-radius: 2px; background-color: {COLOURS["grey"]}; margin-right: 4px; '
        f'vertical-align: middle;"></span>No Data</span>'
        # Ring indicator swatches (model's best pick identification)
        f'<span><span style="display: inline-block; width: 10px; height: 10px; '
        f'border-radius: 2px; background-color: {COLOURS["green"]}; margin-right: 4px; '
        f'vertical-align: middle; '
        f'box-shadow: 0 0 0 2px {COLOURS["green"]}, '
        f'0 0 0 4px rgba(63, 185, 80, 0.35), '
        f'0 0 10px rgba(63, 185, 80, 0.4); '
        f'"></span>\u2605 Value Pick (edge &ge; {edge_threshold_pct}%)</span>'
        f'<span><span style="display: inline-block; width: 10px; height: 10px; '
        f'border-radius: 2px; background-color: {COLOURS["yellow"]}; margin-right: 4px; '
        f'vertical-align: middle; '
        f'box-shadow: 0 0 0 2px {COLOURS["blue"]}, '
        f'0 0 6px rgba(88, 166, 255, 0.35); '
        f'"></span>\u2605 Best Guess (below threshold)</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Load fixtures
    with st.spinner("Loading fixtures..."):
        fixtures = get_all_upcoming_fixtures(days_ahead=days_ahead)

    if not fixtures:
        st.markdown(
            '<div class="bv-empty-state">'
            "No upcoming fixtures found. The season may be between matchdays, "
            "or the pipeline hasn't scraped fixture data yet."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        # ────────────────────────────────────────────────────────────────
        # Pipeline Health Summary (E24-04)
        # ────────────────────────────────────────────────────────────────
        total = len(fixtures)
        with_prediction = sum(1 for f in fixtures if f["has_prediction"])
        with_odds = sum(1 for f in fixtures if f["has_odds"])
        with_value = sum(1 for f in fixtures if f["has_value_bets"])
        full_data = sum(
            1 for f in fixtures if f["has_prediction"] and f["has_odds"]
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Upcoming Matches", total)
        with col2:
            st.metric("With Predictions", with_prediction)
        with col3:
            st.metric("With Odds", with_odds)
        with col4:
            st.metric("With Value Bets", with_value)

        # Pipeline health bar
        if total > 0:
            coverage_pct = (full_data / total) * 100
            if coverage_pct >= 70:
                bar_colour = COLOURS["green"]
            elif coverage_pct >= 30:
                bar_colour = COLOURS["yellow"]
            else:
                bar_colour = COLOURS["red"]

            st.markdown(
                f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]}; margin: 8px 0 4px;">'
                f'Pipeline Coverage: <strong style="color: {COLOURS["text"]};">'
                f'{full_data}/{total}</strong> fixtures have full prediction + odds data'
                f'</div>'
                f'<div style="background-color: {COLOURS["border"]}; border-radius: 4px; '
                f'height: 6px; overflow: hidden; margin-bottom: 8px;">'
                f'<div style="width: {coverage_pct:.0f}%; height: 100%; '
                f'background-color: {bar_colour}; border-radius: 4px; '
                f'transition: width 0.3s ease;"></div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            if coverage_pct < 70:
                st.markdown(
                    f'<div style="font-family: Inter, sans-serif; font-size: 11px; '
                    f'color: {COLOURS["text_secondary"]}; margin-bottom: 12px; '
                    f'padding: 6px 10px; border-left: 2px solid {COLOURS["blue"]}; '
                    f'background-color: rgba(88, 166, 255, 0.05);">'
                    f'\U0001F4A1 Bookmakers typically price matches 1\u20132 weeks ahead. '
                    f'Fixtures further out show grey badges until odds become available. '
                    f'The pipeline refreshes odds automatically each morning.'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # Group fixtures by date and render
        for match_date, group in groupby(fixtures, key=lambda x: x["date"]):
            st.markdown(
                f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
                f'font-weight: 600; color: {COLOURS["text"]}; '
                f'margin: 20px 0 10px; text-transform: uppercase; '
                f'letter-spacing: 0.5px;">{match_date}</div>',
                unsafe_allow_html=True,
            )

            for fix in group:
                # Card border — two-level visual hierarchy (E31-02):
                # 1. Value-bet fixtures get a full green card border + subtle
                #    glow so users can scan the page at-a-glance for value.
                # 2. Non-value fixtures keep the default card styling — the
                #    ★ blue-ringed best-guess badge inside provides the detail.
                if fix["has_value_bets"]:
                    border_style = (
                        f"border: 1.5px solid {COLOURS['green']}; "
                        f"box-shadow: 0 0 0 1px rgba(63, 185, 80, 0.2), "
                        f"0 0 12px rgba(63, 185, 80, 0.12);"
                    )
                else:
                    border_style = ""

                kickoff_html = ""
                if fix["kickoff"] and fix["kickoff"] != "TBD":
                    kickoff_html = (
                        f'<span style="font-family: JetBrains Mono, monospace; font-size: 13px; '
                        f'color: {COLOURS["text_secondary"]}; min-width: 50px;">'
                        f'{fix["kickoff"]}</span>'
                    )

                league_badge = (
                    f'<span class="bv-badge" style="background-color: {COLOURS["border"]}; '
                    f'color: {COLOURS["text_secondary"]};">{fix["league"]}</span>'
                )

                # Diagnostic badges (E24-04)
                diag_badges = []
                if not fix["has_prediction"]:
                    diag_badges.append(
                        f'<span title="No prediction available" style="'
                        f"display: inline-block; padding: 1px 5px; margin-left: 4px; "
                        f"border-radius: 3px; font-family: 'JetBrains Mono', monospace; "
                        f"font-size: 9px; font-weight: 600; color: {COLOURS['red']}; "
                        f'border: 1px solid {COLOURS["red"]}; cursor: help;">'
                        f"No pred</span>"
                    )
                if not fix["has_odds"]:
                    diag_badges.append(
                        f'<span title="No odds loaded" style="'
                        f"display: inline-block; padding: 1px 5px; margin-left: 4px; "
                        f"border-radius: 3px; font-family: 'JetBrains Mono', monospace; "
                        f"font-size: 9px; font-weight: 600; color: {COLOURS['yellow']}; "
                        f'border: 1px solid {COLOURS["yellow"]}; cursor: help;">'
                        f"No odds</span>"
                    )
                if fix["has_prediction"] and fix["has_odds"]:
                    vb_label = (
                        f'{fix["value_bet_count"]} VB'
                        if fix["has_value_bets"]
                        else "Full data"
                    )
                    vb_title = (
                        f'{fix["value_bet_count"]} value bet(s) identified'
                        if fix["has_value_bets"]
                        else "Prediction + odds loaded"
                    )
                    diag_badges.append(
                        f'<span title="{vb_title}" style="'
                        f"display: inline-block; padding: 1px 5px; margin-left: 4px; "
                        f"border-radius: 3px; font-family: 'JetBrains Mono', monospace; "
                        f"font-size: 9px; font-weight: 600; color: {COLOURS['green']}; "
                        f'border: 1px solid {COLOURS["green"]}; cursor: help;">'
                        f"{vb_label}</span>"
                    )
                diag_html = "".join(diag_badges)

                # Market badges with dynamic threshold (E30-01)
                market_html = _render_market_badges(
                    fix["market_edges"],
                    market_vb_info=fix.get("market_vb_info"),
                    market_probs=fix.get("market_probs"),
                    threshold=edge_threshold,
                )

                # Predicted score inline
                pred_html = ""
                pred_h = fix.get("predicted_home_goals")
                pred_a = fix.get("predicted_away_goals")
                if pred_h is not None and pred_a is not None:
                    pred_html = (
                        f'<span style="font-family: JetBrains Mono, monospace; '
                        f'font-size: 11px; color: {COLOURS["text_secondary"]}; '
                        f'margin-left: 12px;" '
                        f'title="Model predicted expected goals (xG-based)">'
                        f'Model: {pred_h:.1f} \u2013 {pred_a:.1f}</span>'
                    )

                fix_home = render_team_badge(fix["home_team_id"], fix["home_team"], size=20)
                fix_away = render_team_badge(fix["away_team_id"], fix["away_team"], size=20)

                # Fixture card
                st.markdown(
                    f'<div class="bv-card" style="padding: 12px 16px; {border_style}">'
                    f'<div style="display: flex; justify-content: space-between; '
                    f'align-items: center; margin-bottom: 6px;">'
                    f'<div style="display: flex; align-items: center; gap: 12px;">'
                    f'{kickoff_html}'
                    f'<span style="font-family: Inter, sans-serif; font-size: 15px; '
                    f'font-weight: 600; color: {COLOURS["text"]};">'
                    f'{fix_home} vs {fix_away}</span>'
                    f'{pred_html}'
                    f'</div>'
                    f'<div style="display: flex; align-items: center;">'
                    f'{league_badge}{diag_html}'
                    f'</div>'
                    f'</div>'
                    f'<div style="display: flex; align-items: center; gap: 4px; '
                    f'padding-left: 62px;">'
                    f'{market_html}'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # Deep Dive button
                if st.button(
                    "\U0001F50D Deep Dive",
                    key=f"fixture_dive_{fix['match_id']}",
                    type="secondary",
                ):
                    st.session_state["deep_dive_match_id"] = fix["match_id"]
                    st.switch_page("views/match_detail.py")

else:
    # ══════════════════════════════════════════════════════════════════════
    # RECENT RESULTS VIEW (E30-02) — completed matches
    # ══════════════════════════════════════════════════════════════════════

    # ── Edge threshold slider (shared with Upcoming) ─────────────────
    edge_threshold_pct = st.slider(
        "Edge threshold (%)",
        min_value=1,
        max_value=15,
        value=int(_config_edge_threshold * 100),
        step=1,
        help=(
            "Minimum edge to colour a badge green (value bet). "
            "Controls badge colours and ring styles for historical matches."
        ),
        key="recent_edge_threshold",
    )
    edge_threshold = edge_threshold_pct / 100.0

    # Load recent results
    with st.spinner("Loading recent results..."):
        recent = get_recent_results(days_back=30)

    if not recent:
        st.markdown(
            '<div class="bv-empty-state">'
            "No completed matches found in the last 30 days. "
            "Results will appear here once matches have been played."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        # ── Summary metrics (E30-02) ─────────────────────────────────
        # Replace Pipeline Health with accuracy metrics for historical view.
        total_recent = len(recent)
        # Top Pick accuracy: how often was the model's best badge correct?
        tp_with_data = [r for r in recent if r["top_pick_correct"] is not None]
        tp_correct = sum(1 for r in tp_with_data if r["top_pick_correct"])
        tp_total = len(tp_with_data)

        # Value bet record: wins / total across all matches with VB
        vb_matches = [r for r in recent if r["vb_total"] > 0]
        total_vb_wins = sum(r["vb_wins"] for r in vb_matches)
        total_vb_bets = sum(r["vb_total"] for r in vb_matches)
        vb_hit_rate = (total_vb_wins / total_vb_bets * 100) if total_vb_bets > 0 else 0.0

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Matches", total_recent)
        with col2:
            st.metric(
                "Top Pick Accuracy",
                f"{tp_correct}/{tp_total}" if tp_total > 0 else "N/A",
            )
        with col3:
            st.metric(
                "VB Record",
                f"{total_vb_wins}/{total_vb_bets}" if total_vb_bets > 0 else "N/A",
            )
        with col4:
            st.metric(
                "VB Hit Rate",
                f"{vb_hit_rate:.0f}%" if total_vb_bets > 0 else "N/A",
            )

        st.divider()

        # ── Render completed fixture cards ───────────────────────────
        for match_date, group in groupby(recent, key=lambda x: x["date"]):
            st.markdown(
                f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
                f'font-weight: 600; color: {COLOURS["text"]}; '
                f'margin: 20px 0 10px; text-transform: uppercase; '
                f'letter-spacing: 0.5px;">{match_date}</div>',
                unsafe_allow_html=True,
            )

            for fix in group:
                # Card border for completed matches (E31-02):
                # Green full border = value bet was profitable (nice!)
                # Red full border = value bet existed but lost
                # Default = no value bet existed, or partial data
                if fix["vb_profitable"] is True:
                    border_style = (
                        f"border: 1.5px solid {COLOURS['green']}; "
                        f"box-shadow: 0 0 0 1px rgba(63, 185, 80, 0.2), "
                        f"0 0 12px rgba(63, 185, 80, 0.12);"
                    )
                elif fix["vb_profitable"] is False:
                    border_style = (
                        f"border: 1.5px solid {COLOURS['red']}; "
                        f"box-shadow: 0 0 0 1px rgba(248, 81, 73, 0.2), "
                        f"0 0 12px rgba(248, 81, 73, 0.12);"
                    )
                else:
                    border_style = ""

                # Actual score — displayed prominently
                hg = fix["home_goals"]
                ag = fix["away_goals"]
                score_html = (
                    f'<span style="font-family: JetBrains Mono, monospace; '
                    f'font-size: 18px; font-weight: 700; color: {COLOURS["text"]}; '
                    f'min-width: 60px; text-align: center;">'
                    f'{hg} \u2013 {ag}</span>'
                )

                # ✅/❌ indicator for top pick correctness
                result_icon = ""
                if fix["top_pick_correct"] is True:
                    result_icon = (
                        f'<span style="font-size: 16px; margin-left: 6px;" '
                        f'title="Model\'s top pick was correct">\u2705</span>'
                    )
                elif fix["top_pick_correct"] is False:
                    result_icon = (
                        f'<span style="font-size: 16px; margin-left: 6px;" '
                        f'title="Model\'s top pick was wrong">\u274C</span>'
                    )

                # Predicted score (muted, below actual)
                pred_text = ""
                pred_h = fix.get("predicted_home_goals")
                pred_a = fix.get("predicted_away_goals")
                if pred_h is not None and pred_a is not None:
                    pred_text = (
                        f'<div style="font-family: JetBrains Mono, monospace; '
                        f'font-size: 11px; color: {COLOURS["text_secondary"]}; '
                        f'margin-top: 2px;">'
                        f'Predicted: {pred_h:.1f} \u2013 {pred_a:.1f}</div>'
                    )
                elif not fix["has_prediction"]:
                    pred_text = (
                        f'<div style="font-family: Inter, sans-serif; '
                        f'font-size: 11px; color: {COLOURS["text_secondary"]}; '
                        f'margin-top: 2px;">No prediction</div>'
                    )

                # League badge
                league_badge = (
                    f'<span class="bv-badge" style="background-color: {COLOURS["border"]}; '
                    f'color: {COLOURS["text_secondary"]};">{fix["league"]}</span>'
                )

                # Market badges (pre-match edges, same ring logic)
                market_html = _render_market_badges(
                    fix["market_edges"],
                    market_vb_info=fix.get("market_vb_info"),
                    market_probs=fix.get("market_probs"),
                    threshold=edge_threshold,
                )

                fix_home = render_team_badge(
                    fix["home_team_id"], fix["home_team"], size=20,
                )
                fix_away = render_team_badge(
                    fix["away_team_id"], fix["away_team"], size=20,
                )

                # Result card — four rows:
                # Row 1: Teams + Score + Result icon + League badge
                # Row 2: Predicted score (muted)
                # Row 3: Market badges
                st.markdown(
                    f'<div class="bv-card" style="padding: 12px 16px; {border_style}">'
                    # Row 1: match header with actual score
                    f'<div style="display: flex; justify-content: space-between; '
                    f'align-items: center; margin-bottom: 4px;">'
                    f'<div style="display: flex; align-items: center; gap: 12px;">'
                    f'<span style="font-family: Inter, sans-serif; font-size: 15px; '
                    f'font-weight: 600; color: {COLOURS["text"]};">'
                    f'{fix_home}</span>'
                    f'{score_html}{result_icon}'
                    f'<span style="font-family: Inter, sans-serif; font-size: 15px; '
                    f'font-weight: 600; color: {COLOURS["text"]};">'
                    f'{fix_away}</span>'
                    f'</div>'
                    f'<div style="display: flex; align-items: center;">'
                    f'{league_badge}'
                    f'</div>'
                    f'</div>'
                    # Row 2: predicted score
                    f'<div style="padding-left: 4px;">{pred_text}</div>'
                    # Row 3: market badges
                    f'<div style="display: flex; align-items: center; gap: 4px; '
                    f'margin-top: 6px; padding-left: 4px;">'
                    f'{market_html}'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # Deep Dive button (also available for completed matches)
                if st.button(
                    "\U0001F50D Deep Dive",
                    key=f"result_dive_{fix['match_id']}",
                    type="secondary",
                ):
                    st.session_state["deep_dive_match_id"] = fix["match_id"]
                    st.switch_page("views/match_detail.py")

# ============================================================================
# Glossary — explains every term, badge, and indicator on this page (E27-03)
# ============================================================================
# The owner is learning (MP §12). This glossary defines every visible element
# so anyone can understand the fixtures overview without prior betting knowledge.

st.divider()
with st.expander("Glossary — What do these terms mean?", expanded=False):
    st.markdown(
        '<style>'
        '.gloss-section { margin-bottom: 18px; }'
        '.gloss-title {'
        '  font-family: Inter, sans-serif; font-size: 14px; font-weight: 700;'
        '  color: #3FB950; text-transform: uppercase; letter-spacing: 0.5px;'
        '  margin-bottom: 8px; border-bottom: 1px solid #21262D; padding-bottom: 4px;'
        '}'
        '.gloss-row {'
        '  display: flex; gap: 8px; margin-bottom: 6px; line-height: 1.45;'
        '}'
        '.gloss-term {'
        '  font-family: "JetBrains Mono", monospace; font-size: 12px;'
        '  font-weight: 600; color: #E6EDF3; min-width: 140px; flex-shrink: 0;'
        '}'
        '.gloss-def {'
        '  font-family: Inter, sans-serif; font-size: 12px; color: #8B949E;'
        '}'
        '</style>',
        unsafe_allow_html=True,
    )

    # --- Market Badges ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Market Badges</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">H / D / A</span>'
        '  <span class="gloss-def">Home Win / Draw / Away Win (1X2 match result market). '
        'The most common betting market — who wins the match.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">O1.5 / U1.5</span>'
        '  <span class="gloss-def">Over/Under 1.5 Goals. Over 1.5 means 2 or more goals total. '
        'Under 1.5 means 0 or 1 goals (rare, ~15-20% of EPL matches).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">O2.5 / U2.5</span>'
        '  <span class="gloss-def">Over/Under 2.5 Goals. Over 2.5 means 3 or more goals total. '
        'The most popular goals line in betting (~50/50 split in the EPL).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">BTTS Y / BTTS N</span>'
        '  <span class="gloss-def">Both Teams to Score — Yes or No. '
        'BTTS Yes means each team scores at least one goal.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Badge Colours ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Badge Colours</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #3FB950;">Green</span>'
        '  <span class="gloss-def">The model sees a strong edge — the bookmaker\'s odds are '
        'significantly more generous than the model thinks they should be.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #D29922;">Yellow</span>'
        '  <span class="gloss-def">Marginal edge — there\'s some value but the gap between '
        'model and bookmaker is small. Proceed with caution.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #F85149;">Red</span>'
        '  <span class="gloss-def">No edge — the bookmaker\'s price is equal to or below '
        'what the model thinks. Not a value bet.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #8B949E;">Grey</span>'
        '  <span class="gloss-def">No data — either the prediction hasn\'t been generated yet '
        'or odds haven\'t been loaded for this market.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Fixture Data ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Fixture Data</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Predicted Score</span>'
        '  <span class="gloss-def">The model\'s expected goals for each team '
        '(e.g. "Model: 1.4 – 0.8"). This is the Poisson model\'s lambda (\u03BB) — '
        'the average goals the model expects, not a specific scoreline prediction.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Edge (tooltip)</span>'
        '  <span class="gloss-def">Hover over any badge to see the exact edge percentage. '
        'E.g. "+8.2% edge" means the model thinks the outcome is 8.2 percentage points '
        'more likely than the bookmaker\'s odds imply.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Diagnostic Badges ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Diagnostic Badges</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">No pred</span>'
        '  <span class="gloss-def">The model hasn\'t generated a prediction for this match yet. '
        'Predictions run during the morning pipeline (6 AM).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">No odds</span>'
        '  <span class="gloss-def">No bookmaker odds have been loaded. '
        'Odds are typically available 1-2 weeks before kickoff.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Full data</span>'
        '  <span class="gloss-def">Both prediction and odds exist — the model can compute edges '
        'and identify value bets for this match.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">X VB</span>'
        '  <span class="gloss-def">Number of value bets identified. A value bet is a selection '
        'where the model\'s probability exceeds the bookmaker\'s implied probability.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Top Picks ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Top Picks Banner</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Top Picks</span>'
        '  <span class="gloss-def">The 3\u20135 highest-edge value bets across all upcoming fixtures. '
        'Shows the best opportunities at a glance without scrolling through every match.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Best Bookmaker</span>'
        '  <span class="gloss-def">The bookmaker offering the best odds (highest edge) for each '
        'pick. Different bookmakers price the same outcome differently.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Pipeline Coverage</span>'
        '  <span class="gloss-def">How many upcoming fixtures have both model predictions and '
        'bookmaker odds loaded. Higher coverage means more fixtures can be analysed for value.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
