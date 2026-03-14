"""
BetVector — Today's Picks Page (E9-02, E24-01, E26-01)
========================================================
Displays actionable value bets with a date range filter.

Primary picks interface — "what should I bet on?"

**E26-01 overhaul:** Fixed per-bookmaker duplication (906 cards → ~35 unique
picks) and added date range filter for browsing past and future matchdays.

Key changes:
- Value bets grouped by (match_id, market_type, selection) — one card per
  unique pick showing the best bookmaker and a count of alternatives.
- Date range slider replaces the old "today onward" logic.  Users can
  look backward (recent results) and forward (upcoming picks) seamlessly.
- Finished picks show inline match result and win/loss status.

Master Plan refs: MP §3 Flow 1 (Morning Picks Review), MP §8 Design System
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

import streamlit as st

from src.config import config
from src.database.db import get_session
from src.database.models import (
    BetLog,
    Feature,
    League,
    Match,
    Team,
    User,
    ValueBet,
    Weather,
)
from src.auth import get_session_user_id
from src.delivery.views._badge_helper import render_team_badge


# ============================================================================
# Human-readable display labels
# ============================================================================

MARKET_DISPLAY = {
    "1X2": "Match Result",
    "OU25": "Over/Under 2.5 Goals",
    "OU15": "Over/Under 1.5 Goals",
    "OU35": "Over/Under 3.5 Goals",
    "BTTS": "Both Teams To Score",
}

SELECTION_DISPLAY = {
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

# Confidence badge colours (MP §8)
CONFIDENCE_COLOURS = {
    "high": "#3FB950",    # Green
    "medium": "#D29922",  # Yellow
    "low": "#484F58",     # Muted
}

# Bookmaker display names — clean up raw internal values
BOOKMAKER_DISPLAY = {
    "market_avg": "Market Avg",
    "Bet365": "Bet365",
    "Pinnacle": "Pinnacle",
    "William Hill": "William Hill",
}


# ============================================================================
# Data Loading
# ============================================================================

def _enrich_value_bets(session, rows) -> List[Dict]:
    """Turn raw (ValueBet, Match, League) rows into enriched dicts.

    Shared helper used by both the upcoming-picks and recent-results
    queries so enrichment logic isn't duplicated.

    PC-12-03: Rewrote to use bulk-loading instead of per-row queries.
    Previously ran 4 queries per VB row (Team×2, Weather, Feature) =
    ~12,000 queries for 3,000 VBs. Now runs 3 bulk queries total
    regardless of VB count, then does O(1) dict lookups in the loop.
    """
    if not rows:
        return []

    # ── Step 1: Collect all unique IDs needed for enrichment ──────────
    team_ids: set = set()
    match_ids: set = set()
    home_team_per_match: dict = {}  # match_id → home_team_id

    for vb, match, league in rows:
        team_ids.add(match.home_team_id)
        team_ids.add(match.away_team_id)
        match_ids.add(match.id)
        home_team_per_match[match.id] = match.home_team_id

    # ── Step 2: Bulk-load Teams (1 query) ─────────────────────────────
    teams_by_id: dict = {}
    if team_ids:
        for team in session.query(Team).filter(Team.id.in_(team_ids)).all():
            teams_by_id[team.id] = team

    # ── Step 3: Bulk-load Weather (1 query) ───────────────────────────
    weather_by_match: dict = {}
    if match_ids:
        for w in session.query(Weather).filter(
            Weather.match_id.in_(match_ids)
        ).all():
            weather_by_match[w.match_id] = w

    # ── Step 4: Bulk-load Features for home teams (1 query) ───────────
    # We only need the home team's feature row for market_value_ratio.
    features_by_match: dict = {}
    if match_ids:
        for f in session.query(Feature).filter(
            Feature.match_id.in_(match_ids)
        ).all():
            # Key by (match_id, team_id) so we can look up home team's row
            features_by_match[(f.match_id, f.team_id)] = f

    # ── Step 5: Enrich each row using O(1) dict lookups ───────────────
    results = []
    for vb, match, league in rows:
        try:
            home_team = teams_by_id.get(match.home_team_id)
            away_team = teams_by_id.get(match.away_team_id)

            # Weather conditions for this match (E17-02)
            weather = weather_by_match.get(match.id)
            weather_category = weather.weather_category if weather else None
            is_heavy_weather = False
            if weather:
                cat = (weather.weather_category or "").lower()
                is_heavy_weather = (
                    cat in ("rain", "heavy_rain", "snow", "storm")
                    or (weather.wind_speed_kmh or 0) > 30
                )

            # Market value ratio from the home team's features (E17-02)
            home_feature = features_by_match.get(
                (match.id, match.home_team_id)
            )
            mv_ratio = getattr(home_feature, "market_value_ratio", None) if home_feature else None

            # Match result for finished matches — used in Recent Results section.
            # Guard against NULL goals: a match can be status="finished" but have
            # NULL home_goals/away_goals if the pipeline partially updated.
            match_result = None
            if (match.status == "finished"
                    and match.home_goals is not None
                    and match.away_goals is not None):
                match_result = f"{match.home_goals}-{match.away_goals}"

            results.append({
                "id": vb.id,
                "match_id": vb.match_id,
                "home_team": home_team.name if home_team else "Unknown",
                "away_team": away_team.name if away_team else "Unknown",
                "home_team_id": home_team.id if home_team else None,
                "away_team_id": away_team.id if away_team else None,
                "league": league.short_name if league else "??",
                "date": match.date,
                "kickoff": match.kickoff_time or "TBD",
                "status": match.status,
                "match_result": match_result,
                "market_type": vb.market_type,
                "selection": vb.selection,
                "model_prob": vb.model_prob,
                "bookmaker": vb.bookmaker,
                "bookmaker_odds": vb.bookmaker_odds,
                "implied_prob": vb.implied_prob,
                "edge": vb.edge,
                "expected_value": vb.expected_value,
                "confidence": vb.confidence,
                "explanation": vb.explanation,
                "detected_at": vb.detected_at,
                "is_heavy_weather": is_heavy_weather,
                "weather_summary": weather_category,
                "market_value_ratio": mv_ratio,
            })
        except Exception as exc:
            # PC-07-04: Skip corrupted/incomplete rows instead of crashing
            # the entire page.  Log the error for debugging.
            logger.warning(
                "_enrich_value_bets: Skipping value_bet %s (match %s) — %s",
                getattr(vb, "id", "?"), getattr(match, "id", "?"), exc,
            )
            continue
    return results


def get_value_bets_in_range(
    date_from: date,
    date_to: date,
    edge_threshold: float = 0.0,
) -> List[Dict]:
    """Fetch value bets within a date range, grouped by unique pick.

    E26-01: Replaces the old ``get_upcoming_value_bets()`` and
    ``get_recent_results()`` with a unified date-range query that
    de-duplicates per-bookmaker rows.

    The ValueFinder creates a separate ValueBet per bookmaker — e.g.,
    45 bookmakers offering Wolves Home Win each produce a row.  This
    function groups by (match_id, market_type, selection) and keeps only
    the row with the **highest edge** (best bookmaker), attaching the
    count of alternative bookmakers.

    Covers both scheduled (upcoming) and finished (recent) matches
    within the date range, letting the user slide forward and backward.

    Parameters
    ----------
    date_from : date
        Start of the date range (inclusive).
    date_to : date
        End of the date range (inclusive).
    edge_threshold : float
        Minimum edge to display (0.0 shows all value bets).

    Returns
    -------
    list[dict]
        Unique value bets grouped by pick, enriched with team names,
        league, kickoff, and alt_bookmaker_count.
    """
    try:
        with get_session() as session:
            from_str = date_from.isoformat()
            to_str = date_to.isoformat()

            query = (
                session.query(ValueBet, Match, League)
                .join(Match, ValueBet.match_id == Match.id)
                .join(League, Match.league_id == League.id)
                .filter(Match.date >= from_str)
                .filter(Match.date <= to_str)
            )

            if edge_threshold > 0:
                query = query.filter(ValueBet.edge >= edge_threshold)

            # Fetch all rows — we'll group in Python for flexibility
            # (SQLite GROUP BY with MAX is awkward for returning full row data)
            rows = (
                query
                .order_by(Match.date.asc(), ValueBet.edge.desc())
                .all()
            )

            # Enrich all rows (team names, weather, etc.)
            all_enriched = _enrich_value_bets(session, rows)

    except Exception as exc:
        # PC-07-04: Graceful degradation on DB errors — return empty list
        # instead of crashing the entire Today's Picks page.
        logger.error("get_value_bets_in_range: DB query failed — %s", exc)
        return []

    # --- Group by unique pick (match_id + market_type + selection) ---
    # Keep only the best bookmaker (highest edge) per group.
    # Attach alt_bookmaker_count = how many other bookmakers also offer value.
    grouped: Dict[tuple, Dict] = {}
    counts: Dict[tuple, int] = {}

    for vb in all_enriched:
        key = (vb["match_id"], vb["market_type"], vb["selection"])
        counts[key] = counts.get(key, 0) + 1
        if key not in grouped or vb["edge"] > grouped[key]["edge"]:
            grouped[key] = vb

    # Attach alt_bookmaker_count and sort by date asc, then edge desc
    result = []
    for key, vb in grouped.items():
        vb["alt_bookmaker_count"] = counts[key] - 1  # exclude the best one
        result.append(vb)

    result.sort(key=lambda x: (-_date_sort_key(x["date"]), -x["edge"]))
    # Re-sort: date ascending, then edge descending within each date
    result.sort(key=lambda x: (x["date"], -x["edge"]))

    return result


def _date_sort_key(date_str: str) -> int:
    """Convert date string to sortable integer (for stable sorting)."""
    try:
        return int(date_str.replace("-", ""))
    except (ValueError, AttributeError):
        return 0


def get_suggested_stake(model_prob: float, odds: float) -> float:
    """Calculate a suggested stake for display purposes.

    Uses the logged-in user's bankroll settings. Falls back to a simple
    2% of $1000 if no user is configured.

    NOTE: For bulk usage (rendering many cards), prefer
    ``_precompute_all_stakes()`` which fetches user info once instead
    of hitting the DB per call.
    """
    try:
        from src.betting.bankroll import BankrollManager
        manager = BankrollManager()
        user_id = get_session_user_id()
        with get_session() as session:
            user = session.get(User, user_id)
            if user:
                result = manager.calculate_stake(user.id, model_prob, odds)
                return result.stake
    except Exception:
        pass

    # Fallback: 2% of $1000
    return 20.00


def _precompute_all_stakes(picks: List[Dict]) -> Dict[int, float]:
    """Precompute suggested stakes for all picks in minimal DB round-trips.

    PC-12-03: Replaces the per-card ``get_suggested_stake()`` calls which
    hit the DB 4+ times per card (user × 2, daily_losses, peak_bankroll).
    For 35 deduplicated cards, that was ~140 queries at ~200ms each = 28s.

    Now fetches user info once (1 query), checks safety limits once
    (3 queries), then computes all stakes mathematically (0 queries).
    Total: ~4 queries regardless of card count.

    Parameters
    ----------
    picks : list[dict]
        Enriched value bet dicts from ``get_value_bets_in_range()``.

    Returns
    -------
    dict[int, float]
        Mapping of value_bet ID → suggested stake amount.
    """
    if not picks:
        return {}

    fallback_stake = 20.00  # 2% of $1000

    try:
        from src.betting.bankroll import BankrollManager
        user_id = get_session_user_id()
        manager = BankrollManager()

        # ── 1 query: fetch user staking settings ─────────────────────
        with get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return {vb["id"]: fallback_stake for vb in picks}

        # ── 3 queries: check safety limits (user, daily_losses, peak) ─
        safety = manager.check_safety_limits(user_id)

        # If safety limits are breached, all stakes are $0
        if safety.get("daily_limit_hit") or safety.get("min_bankroll_hit"):
            return {vb["id"]: 0.0 for vb in picks}

        # ── Extract user settings for mathematical computation ────────
        method = user.staking_method or "flat"
        bankroll = user.current_bankroll or 1000.0
        stake_pct = user.stake_percentage or 0.02
        kelly_frac = user.kelly_fraction or 0.25

        # Max bet cap from config (hard safety limit)
        try:
            max_bet_pct = float(config.settings.safety.max_bet_percentage)
        except (AttributeError, TypeError, ValueError):
            max_bet_pct = 0.10
        max_stake = bankroll * max_bet_pct

        # ── Compute all stakes in-memory (0 queries) ─────────────────
        stakes: Dict[int, float] = {}
        for vb in picks:
            model_prob = vb.get("model_prob", 0.0)
            odds = vb.get("bookmaker_odds", 1.0)

            if method == "kelly":
                # Kelly Criterion: f* = (p × b - 1) / (b - 1)
                if model_prob * odds < 1.0 or odds <= 1.0:
                    raw_stake = 0.0
                else:
                    full_kelly = (model_prob * odds - 1.0) / (odds - 1.0)
                    raw_stake = full_kelly * kelly_frac * bankroll
            else:
                # Flat or percentage: bankroll × stake_percentage
                raw_stake = bankroll * stake_pct

            # Apply max bet cap and round
            final_stake = round(max(0.0, min(raw_stake, max_stake)), 2)
            stakes[vb["id"]] = final_stake

        return stakes

    except Exception as exc:
        logger.warning("_precompute_all_stakes: fallback — %s", exc)
        return {vb["id"]: fallback_stake for vb in picks}


# ============================================================================
# Card Rendering
# ============================================================================

def render_confidence_badge(confidence: str) -> str:
    """Return an HTML badge for the confidence level."""
    colour = CONFIDENCE_COLOURS.get(confidence, "#484F58")
    label = confidence.upper()
    return (
        f'<span class="bv-badge" style="background-color: {colour};">'
        f'{label}</span>'
    )


def render_value_bet_card(vb: Dict, idx, precomputed_stake: Optional[float] = None) -> None:
    """Render a single value bet as a styled card.

    Shows match info, market details, edge, confidence badge,
    best bookmaker, alternative count, and a "Mark as Placed" form.

    E26-01: Updated to show best bookmaker prominently, alternative
    bookmaker count, and inline match result for finished matches.

    PC-12-03: Added ``precomputed_stake`` parameter — when provided,
    skips the per-card ``get_suggested_stake()`` DB call.  The page
    layout pre-computes all stakes via ``_precompute_all_stakes()``
    before entering the render loop (4 queries total vs 4 × N).

    Parameters
    ----------
    vb : dict
        Enriched value bet dict from get_value_bets_in_range().
    idx : int or str
        Unique key suffix for Streamlit widgets (avoids key collisions).
    precomputed_stake : float, optional
        Pre-calculated stake from ``_precompute_all_stakes()``.
        Falls back to ``get_suggested_stake()`` if not provided.
    """
    market_label = MARKET_DISPLAY.get(vb["market_type"], vb["market_type"])
    selection_label = SELECTION_DISPLAY.get(
        (vb["market_type"], vb["selection"]),
        f"{vb['market_type']}/{vb['selection']}",
    )
    confidence_badge = render_confidence_badge(vb["confidence"])
    # PC-12-03: Use precomputed stake when available (0 DB queries),
    # else fall back to get_suggested_stake (4+ queries per call).
    suggested_stake = (
        precomputed_stake
        if precomputed_stake is not None
        else get_suggested_stake(vb["model_prob"], vb["bookmaker_odds"])
    )

    # Clean bookmaker name for display — raw values like "market_avg"
    # become "Market Avg", known bookmakers keep their proper names
    bookmaker_raw = vb["bookmaker"]
    bookmaker_display = BOOKMAKER_DISPLAY.get(bookmaker_raw, bookmaker_raw)
    is_fanduel = "fanduel" in bookmaker_raw.lower()
    if is_fanduel:
        bookmaker_display = f'<span style="color: #58A6FF; font-weight: 600;">{bookmaker_display}</span>'

    # Edge colour
    edge_pct = vb["edge"] * 100
    edge_colour = "#3FB950" if edge_pct >= 10 else "#D29922" if edge_pct >= 5 else "#E6EDF3"

    # Context badges — weather and market value indicators (E17-02)
    context_badges_html = ""
    badge_parts = []
    if vb.get("is_heavy_weather"):
        summary = (vb.get("weather_summary") or "adverse").upper()
        badge_parts.append(
            '<span class="bv-badge" style="background-color: #58A6FF; color: #fff; '
            f'margin-right: 6px;">\U0001F327\uFE0F {summary}</span>'
        )
    ratio = vb.get("market_value_ratio")
    if ratio and ratio > 2.0:
        badge_parts.append(
            '<span class="bv-badge" style="background-color: #30363D; color: #8B949E; '
            f'margin-right: 6px;">SQUAD VALUE {ratio:.0f}\u00D7 OPPONENT</span>'
        )
    elif ratio and ratio < 0.5 and ratio > 0:
        inv_ratio = 1.0 / ratio
        badge_parts.append(
            '<span class="bv-badge" style="background-color: #30363D; color: #8B949E; '
            f'margin-right: 6px;">OPPONENT SQUAD {inv_ratio:.0f}\u00D7 VALUE</span>'
        )
    if badge_parts:
        context_badges_html = (
            f'<div style="margin-bottom: 8px;">{"".join(badge_parts)}</div>'
        )

    # Alt bookmaker count — shows how many other bookmakers also offer value
    alt_count = vb.get("alt_bookmaker_count", 0)
    alt_html = ""
    if alt_count > 0:
        alt_html = (
            f'<div style="font-family: Inter, sans-serif; font-size: 11px; '
            f'color: #8B949E; margin-top: 6px;">'
            f'{alt_count} other bookmaker{"s" if alt_count != 1 else ""} also '
            f'offer{"s" if alt_count == 1 else ""} value on this pick</div>'
        )

    # Match result badge for finished matches (inline, E26-01)
    result_badge_html = ""
    if vb.get("status") == "finished" and vb.get("match_result"):
        result_badge_html = (
            f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
            f'color: #8B949E; background-color: #21262D; padding: 2px 8px; '
            f'border-radius: 4px; margin-left: 8px;">FT {vb["match_result"]}</span>'
        )

    # Card border: green for scheduled (actionable), muted for finished (historical)
    border_style = (
        "border-left: 3px solid #484F58;"
        if vb.get("status") == "finished"
        else ""
    )

    # Render badges beside team names on pick cards (20px inline)
    pk_home = render_team_badge(vb.get("home_team_id"), vb["home_team"], size=20)
    pk_away = render_team_badge(vb.get("away_team_id"), vb["away_team"], size=20)

    # Card HTML — no leading indentation to avoid markdown code-block interpretation
    card_html = f"""<div class="bv-card" style="{border_style}">
<div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
<div>
<span style="font-family: 'Inter', sans-serif; font-size: 16px; font-weight: 600; color: #E6EDF3;">
{pk_home} vs {pk_away}
</span>{result_badge_html}
<br>
<span style="font-family: 'Inter', sans-serif; font-size: 12px; color: #8B949E;">
{vb["league"]} &middot; {vb["date"]}{(" &middot; " + vb["kickoff"]) if vb.get("kickoff") and vb["kickoff"] != "TBD" else ""}
</span>
</div>
<div>{confidence_badge}</div>
</div>
{context_badges_html}
<div style="display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 4px;">
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Market</span><br>
<span style="font-family: 'Inter', sans-serif; font-size: 14px; color: #E6EDF3;">{selection_label}</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Model Prob <span style="display:inline-block; background:#3FB950; color:#0D1117; font-family:'JetBrains Mono',monospace; font-size:9px; font-weight:700; padding:1px 5px; border-radius:4px; vertical-align:middle; margin-left:4px; line-height:1.3;">MODEL</span></span><br>
<span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">{vb["model_prob"]:.1%}</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Best Odds</span><br>
<span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">{vb["bookmaker_odds"]:.2f}</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Edge</span><br>
<span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: {edge_colour};">+{edge_pct:.1f}%</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Bookmaker</span><br>
<span style="font-family: 'Inter', sans-serif; font-size: 14px; color: #E6EDF3;">{bookmaker_display}</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Suggested Stake</span><br>
<span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">${suggested_stake:.2f}</span>
</div>
</div>
{alt_html}
</div>"""
    st.markdown(card_html, unsafe_allow_html=True)

    # Action row — Deep Dive button + Mark as Placed expander
    # Deep Dive navigates to Match Deep Dive for the full analysis narrative.
    # E26-02: Use session_state to pass match_id across pages — query_params
    # set before st.switch_page() are lost in Streamlit 1.41.
    if st.button(
        "\U0001F50D Deep Dive",
        key=f"pick_dive_{idx}",
        type="secondary",
    ):
        st.session_state["deep_dive_match_id"] = vb["match_id"]
        st.switch_page("views/match_detail.py")

    # "Mark as Placed" — only for scheduled matches (E24-01)
    # Finished matches can't be bet on, so hide the form
    if vb.get("status") != "finished":
        with st.expander(f"Mark as Placed", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                actual_odds = st.number_input(
                    "Actual odds",
                    min_value=1.01,
                    value=vb["bookmaker_odds"],
                    step=0.01,
                    format="%.2f",
                    key=f"odds_{idx}",
                )
            with col2:
                actual_stake = st.number_input(
                    "Actual stake ($)",
                    min_value=0.01,
                    value=max(suggested_stake, 0.01),
                    step=1.0,
                    format="%.2f",
                    key=f"stake_{idx}",
                )

            if st.button("Confirm Bet Placed", key=f"confirm_{idx}", type="primary"):
                # E34-03: Use the logged-in user's ID, not the DB owner lookup.
                user_id = get_session_user_id()
                try:
                    from src.betting.tracker import log_user_bet
                    bet_id = log_user_bet(
                        value_bet_id=vb["id"],
                        user_id=user_id,
                        actual_odds=actual_odds,
                        actual_stake=actual_stake,
                    )
                    if bet_id:
                        st.success(
                            f"Bet logged (ID: {bet_id}). "
                            f"{vb['home_team']} vs {vb['away_team']} — "
                            f"{selection_label} @ {actual_odds:.2f}, "
                            f"${actual_stake:.2f} staked."
                        )
                    else:
                        st.warning("Bet may already be logged (duplicate).")
                except Exception as e:
                    st.error(f"Failed to log bet: {e}")


def render_result_card(vb: Dict, idx: int) -> None:
    """Render a finished-match value bet as a compact result card.

    E24-01: Shows the outcome (score), whether the pick won or lost,
    and the edge that was identified.  No "Mark as Placed" form since
    the match is already finished.
    """
    selection_label = SELECTION_DISPLAY.get(
        (vb["market_type"], vb["selection"]),
        f"{vb['market_type']}/{vb['selection']}",
    )

    # Determine if the pick won or lost based on match result
    result_text = vb.get("match_result", "?-?")
    edge_pct = vb["edge"] * 100

    # Result badge colour — green for won, red for lost, grey for unknown
    # We don't have bet outcome in ValueBet directly, so just show the score
    # and the edge for reference.  The BetLog tracks actual P&L.
    card_html = f"""<div style="
        background-color: #161B22; border: 1px solid #21262D; border-radius: 8px;
        padding: 14px 18px; margin-bottom: 8px;
        border-left: 3px solid #484F58;
    ">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <span style="font-family: 'Inter', sans-serif; font-size: 14px; color: #E6EDF3;">
                {vb["home_team"]} vs {vb["away_team"]}
            </span>
            <span style="font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #8B949E; margin-left: 10px;">
                {result_text}
            </span>
        </div>
        <div style="display: flex; gap: 12px; align-items: center;">
            <span style="font-family: 'Inter', sans-serif; font-size: 12px; color: #8B949E;">
                {selection_label}
            </span>
            <span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #3FB950;">
                +{edge_pct:.1f}%
            </span>
            <span style="font-family: 'Inter', sans-serif; font-size: 11px; color: #484F58;">
                {vb["date"]}
            </span>
        </div>
    </div>
    </div>"""
    st.markdown(card_html, unsafe_allow_html=True)


# ============================================================================
# Page Layout (E26-01: date range filter + grouped picks)
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Today\'s Picks '
    '<span style="font-size: 14px; font-weight: 700; color: #3FB950; '
    'background: rgba(63,185,80,0.12); padding: 2px 8px; border-radius: 4px; '
    'vertical-align: middle; letter-spacing: 0.5px; text-transform: uppercase;">'
    'Value</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Value bets where the model finds positive edge over bookmaker odds '
    '— slide the date range to browse matchdays</p>',
    unsafe_allow_html=True,
)
st.divider()

# ── Filters ──────────────────────────────────────────────────────────────
# Date range: default today-3 to today+7 (shows recent results + upcoming)
# Edge threshold: minimum edge to display
# PC-19: Default to today + 14 days forward.  Users land on the page and
# immediately see what's actionable now and coming up, not past results.
# They can still slide backward to review recent picks if they want.
_today = date.today()
_default_from = _today
_default_to = _today + timedelta(days=14)

col_date, col_edge = st.columns([2, 1])

with col_date:
    date_range = st.date_input(
        "Date range",
        value=(_default_from, _default_to),
        min_value=_today - timedelta(days=30),
        max_value=_today + timedelta(days=30),
        help="Slide backward to see recent results, forward for upcoming matchdays.",
    )
    # Streamlit returns a tuple of 1 or 2 dates depending on user selection
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        date_from, date_to = date_range
    else:
        # Single date selected — use it as both start and end
        date_from = date_range[0] if isinstance(date_range, (tuple, list)) else date_range
        date_to = date_from

with col_edge:
    try:
        _default_edge_pct = float(config.settings.value_betting.edge_threshold) * 100
    except (AttributeError, TypeError, ValueError):
        _default_edge_pct = 5.0
    edge_threshold = st.slider(
        "Min edge",
        min_value=0.0,
        max_value=20.0,
        value=_default_edge_pct,
        step=0.5,
        format="%.1f%%",
        help="Filter picks by minimum edge. Higher = fewer but stronger picks.",
    )
    edge_threshold_decimal = edge_threshold / 100.0

# ── Load picks (grouped by unique bet, best bookmaker per pick) ──────────
with st.spinner("Loading picks..."):
    all_picks = get_value_bets_in_range(
        date_from=date_from,
        date_to=date_to,
        edge_threshold=edge_threshold_decimal,
    )

if all_picks:
    # PC-12-03: Precompute all suggested stakes once (4 DB queries total)
    # instead of calling get_suggested_stake() per card (4 queries × N cards).
    _stake_map = _precompute_all_stakes(all_picks)

    # Split into upcoming (scheduled) and recent (finished) for summary
    today_str = _today.isoformat()
    upcoming = [vb for vb in all_picks if vb["status"] == "scheduled"]
    finished = [vb for vb in all_picks if vb["status"] == "finished"]
    today_count = sum(1 for vb in upcoming if vb["date"] == today_str)

    if today_count > 0:
        st.success(f"**{today_count} pick{'s' if today_count != 1 else ''} for today!**")
    elif upcoming:
        next_date = upcoming[0]["date"]
        st.info(f"No picks for today. Next picks: **{next_date}**")

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Upcoming", len(upcoming))
    with col2:
        st.metric("Recent Results", len(finished))
    with col3:
        avg_edge = sum(vb["edge"] for vb in all_picks) / len(all_picks)
        st.metric("Avg Edge", f"{avg_edge:.1%}")
    with col4:
        high_conf = sum(1 for vb in all_picks if vb["confidence"] == "high")
        st.metric("High Confidence", high_conf)

    st.divider()

    # Group picks by date for clear visual separation
    from itertools import groupby
    for match_date, group in groupby(all_picks, key=lambda x: x["date"]):
        group_list = list(group)
        # Date header with match count
        is_past = match_date < today_str
        date_label = match_date
        if match_date == today_str:
            date_label = f"{match_date}  (Today)"
        elif is_past:
            date_label = f"{match_date}  (Finished)"

        st.markdown(
            f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
            f'font-weight: 600; color: {"#8B949E" if is_past else "#E6EDF3"}; '
            f'margin: 20px 0 10px; text-transform: uppercase; '
            f'letter-spacing: 0.5px;">{date_label}'
            f'<span style="font-size: 12px; font-weight: 400; color: #484F58; '
            f'margin-left: 8px;">{len(group_list)} pick{"s" if len(group_list) != 1 else ""}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        for idx, vb in enumerate(group_list):
            # Use a globally unique key by combining date and idx
            global_idx = f"{match_date}_{idx}"
            # PC-12-03: Pass precomputed stake (0 DB queries per card)
            render_value_bet_card(
                vb, global_idx,
                precomputed_stake=_stake_map.get(vb["id"]),
            )

else:
    # Empty state — no value bets in the date range (MP §8)
    st.markdown(
        '<div class="bv-empty-state">'
        "No value bets found in this date range. Try expanding the date range "
        "or lowering the edge threshold."
        "</div>",
        unsafe_allow_html=True,
    )

# ============================================================================
# Glossary — explains every term visible on the picks page
# ============================================================================
# Always shown (outside the if/else) so it appears whether or not there
# are picks.  Collapsed by default so it doesn't clutter the view.

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

    # --- The Pick Card ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">The Pick Card</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Value Bet</span>'
        '  <span class="gloss-def">A bet where the model thinks the outcome is more '
        'likely than the bookmaker does. The model found a price that looks too '
        'generous \u2014 that\'s where the profit opportunity is.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Market</span>'
        '  <span class="gloss-def">The type of bet: Home Win / Draw / Away Win (1X2), '
        'Over/Under 1.5 or 2.5 Goals, or Both Teams to Score (BTTS).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Selection</span>'
        '  <span class="gloss-def">The specific outcome the model recommends. '
        'E.g. "Home Win", "Over 2.5 Goals", or "BTTS Yes".</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Key Numbers ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Key Numbers</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Model Prob</span>'
        '  <span class="gloss-def">The model\'s estimated probability of this outcome '
        'actually happening, based on team form, xG, venue, and other features. '
        'E.g. 62% means the model thinks this happens roughly 6 times out of 10.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Odds</span>'
        '  <span class="gloss-def">The decimal odds offered by the bookmaker. '
        'Odds of 2.50 mean you win $2.50 for every $1 staked (including your stake back). '
        'Lower odds = bookmaker thinks it\'s more likely.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Edge</span>'
        '  <span class="gloss-def">The gap between what the model thinks and what the '
        'bookmaker thinks. <span style="color: #3FB950;">Positive edge = the bet is '
        'underpriced.</span> An edge of +8% means the model sees an 8 percentage-point '
        'advantage over the bookmaker\'s price. Higher edge = stronger opportunity.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Suggested Stake</span>'
        '  <span class="gloss-def">How much to bet, calculated from your bankroll settings. '
        'Uses a conservative formula so no single bet risks too much of your bankroll.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Confidence ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Confidence Levels</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #3FB950;">HIGH</span>'
        '  <span class="gloss-def">Large edge with strong model certainty. '
        'These are the bets the model is most confident about.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #D29922;">MEDIUM</span>'
        '  <span class="gloss-def">Moderate edge. Worth considering but '
        'less conviction than high-confidence picks.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #8B949E;">LOW</span>'
        '  <span class="gloss-def">Marginal edge. The model sees slight value '
        'but the signal is weaker. Proceed with caution.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Context Badges ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Context Badges</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">\U0001F327\uFE0F Weather</span>'
        '  <span class="gloss-def">Appears when match-day conditions are extreme '
        '(heavy rain, strong wind, snow). Bad weather typically reduces goal-scoring '
        'and favours defensive teams.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Squad Value</span>'
        '  <span class="gloss-def">Appears when one squad is worth 2\u00D7+ the other '
        '(from Transfermarkt data). A massive value gap suggests a significant '
        'talent difference beyond what recent form shows.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Summary Metrics ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Summary Metrics (Top of Page)</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Value Bets</span>'
        '  <span class="gloss-def">Total number of value bets found above '
        'your edge threshold. More isn\'t always better \u2014 quality matters.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Avg Edge</span>'
        '  <span class="gloss-def">The average edge across all picks shown. '
        'Higher average edge means the model sees stronger overall opportunities today.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">High Confidence</span>'
        '  <span class="gloss-def">How many of today\'s picks the model is most '
        'certain about. These are your best bets to focus on.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Filters & Controls ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Filters &amp; Controls</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Date Range</span>'
        '  <span class="gloss-def">Slide forward to see future matchday picks, or backward to '
        'review recent picks and their results. Defaults to today \u00B1 3 days.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Edge Threshold</span>'
        '  <span class="gloss-def">Minimum edge required to show a pick. '
        'Higher threshold = fewer but stronger picks. Adjust to match your risk appetite.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Best Bookmaker</span>'
        '  <span class="gloss-def">Each pick shows the bookmaker offering the highest edge. '
        'Different bookmakers price the same outcome differently.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Alt. Bookmakers</span>'
        '  <span class="gloss-def">How many additional bookmakers also offer value for this '
        'selection. Shown as "X other bookmakers also offer value" on each card.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
