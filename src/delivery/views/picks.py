"""
BetVector — Today's Picks Page (E9-02, E24-01)
================================================
Displays actionable value bets for upcoming matches.

Primary daily interface — "what should I bet on today?"

**E24-01 fix:** The original triple fallback showed stale 2024 picks when
no upcoming value bets existed.  Now the page has two distinct sections:

1. **Upcoming Picks** — only scheduled matches, sorted by date then edge.
   Fallback expands to 14 days, never further.  No finished matches appear.
2. **Recent Results** — last 7 days of finished matches with outcomes, for
   performance tracking.  "Mark as Placed" only shown for upcoming picks.

Master Plan refs: MP §3 Flow 1 (Morning Picks Review), MP §8 Design System
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

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
    """
    results = []
    for vb, match, league in rows:
        home_team = session.query(Team).filter_by(id=match.home_team_id).first()
        away_team = session.query(Team).filter_by(id=match.away_team_id).first()

        # Weather conditions for this match (E17-02)
        weather = session.query(Weather).filter_by(match_id=match.id).first()
        weather_category = weather.weather_category if weather else None
        is_heavy_weather = False
        if weather:
            cat = (weather.weather_category or "").lower()
            is_heavy_weather = (
                cat in ("rain", "heavy_rain", "snow", "storm")
                or (weather.wind_speed_kmh or 0) > 30
            )

        # Market value ratio from the home team's features (E17-02)
        home_feature = (
            session.query(Feature)
            .filter_by(match_id=match.id, team_id=match.home_team_id)
            .first()
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
            "league": league.short_name,
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
    return results


def get_upcoming_value_bets(edge_threshold: float = 0.0) -> List[Dict]:
    """Fetch value bets for upcoming (scheduled) matches only.

    E24-01: Replaces the old ``get_todays_value_bets()`` which had a
    triple fallback cascade that surfaced stale 2024 data.

    New logic:
    1. Query value bets for scheduled matches from today onward,
       sorted by date ascending (soonest first) then edge descending.
    2. If none found, expand window to next 14 days of scheduled matches.
    3. If still none, return empty list — the page shows a clean empty state.
       No all-time fallback.  No finished matches.

    Parameters
    ----------
    edge_threshold : float
        Minimum edge to display (0.0 shows all).

    Returns
    -------
    list[dict]
        Upcoming value bets enriched with team names, league, and kickoff.
    """
    with get_session() as session:
        today = date.today().isoformat()

        # Primary: scheduled matches from today onward
        query = (
            session.query(ValueBet, Match, League)
            .join(Match, ValueBet.match_id == Match.id)
            .join(League, Match.league_id == League.id)
            .filter(Match.status == "scheduled")
            .filter(Match.date >= today)
        )

        if edge_threshold > 0:
            query = query.filter(ValueBet.edge >= edge_threshold)

        # Sort: soonest date first, then highest edge within same date
        rows = (
            query
            .order_by(Match.date.asc(), ValueBet.edge.desc())
            .limit(50)
            .all()
        )

        # Fallback: expand to next 14 days of scheduled matches
        # (covers international break gaps where no matches are today)
        if not rows:
            future_cutoff = (date.today() + timedelta(days=14)).isoformat()
            query = (
                session.query(ValueBet, Match, League)
                .join(Match, ValueBet.match_id == Match.id)
                .join(League, Match.league_id == League.id)
                .filter(Match.status == "scheduled")
                .filter(Match.date >= today)
                .filter(Match.date <= future_cutoff)
            )
            if edge_threshold > 0:
                query = query.filter(ValueBet.edge >= edge_threshold)

            rows = (
                query
                .order_by(Match.date.asc(), ValueBet.edge.desc())
                .limit(50)
                .all()
            )

        return _enrich_value_bets(session, rows)


def get_recent_results(days: int = 7, limit: int = 20) -> List[Dict]:
    """Fetch value bets for recently finished matches with outcomes.

    E24-01: New function providing a separate "Recent Results" section.
    Shows how past picks performed — win or loss — for performance tracking.

    Parameters
    ----------
    days : int
        How many days back to look (default 7).
    limit : int
        Max results to return.

    Returns
    -------
    list[dict]
        Recent finished value bets with match results.
    """
    with get_session() as session:
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        rows = (
            session.query(ValueBet, Match, League)
            .join(Match, ValueBet.match_id == Match.id)
            .join(League, Match.league_id == League.id)
            .filter(Match.status == "finished")
            .filter(Match.date >= cutoff)
            .order_by(Match.date.desc(), ValueBet.edge.desc())
            .limit(limit)
            .all()
        )

        return _enrich_value_bets(session, rows)


def get_suggested_stake(model_prob: float, odds: float) -> float:
    """Calculate a suggested stake for display purposes.

    Uses the default user's bankroll settings. Falls back to a simple
    2% of $1000 if no user is configured.
    """
    try:
        from src.betting.bankroll import BankrollManager
        manager = BankrollManager()
        with get_session() as session:
            user = session.query(User).filter_by(role="owner").first()
            if user:
                result = manager.calculate_stake(user.id, model_prob, odds)
                return result.stake
    except Exception:
        pass

    # Fallback: 2% of $1000
    return 20.00


def get_default_user_id() -> Optional[int]:
    """Get the owner user ID for bet logging."""
    with get_session() as session:
        user = session.query(User).filter_by(role="owner").first()
        return user.id if user else None


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


def render_value_bet_card(vb: Dict, idx: int) -> None:
    """Render a single value bet as a styled card.

    Shows match info, market details, edge, confidence badge, and
    a "Mark as Placed" button that expands into a form.
    """
    market_label = MARKET_DISPLAY.get(vb["market_type"], vb["market_type"])
    selection_label = SELECTION_DISPLAY.get(
        (vb["market_type"], vb["selection"]),
        f"{vb['market_type']}/{vb['selection']}",
    )
    confidence_badge = render_confidence_badge(vb["confidence"])
    suggested_stake = get_suggested_stake(vb["model_prob"], vb["bookmaker_odds"])

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

    # Card HTML — no leading indentation to avoid markdown code-block interpretation
    card_html = f"""<div class="bv-card">
<div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
<div>
<span style="font-family: 'Inter', sans-serif; font-size: 16px; font-weight: 600; color: #E6EDF3;">
{vb["home_team"]} vs {vb["away_team"]}
</span>
<br>
<span style="font-family: 'Inter', sans-serif; font-size: 12px; color: #8B949E;">
{vb["league"]} &middot; {vb["date"]}{(" &middot; " + vb["kickoff"]) if vb.get("kickoff") and vb["kickoff"] != "TBD" else ""}
</span>
</div>
<div>{confidence_badge}</div>
</div>
{context_badges_html}
<div style="display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 8px;">
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Market</span><br>
<span style="font-family: 'Inter', sans-serif; font-size: 14px; color: #E6EDF3;">{selection_label}</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Model Prob</span><br>
<span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">{vb["model_prob"]:.1%}</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Odds</span><br>
<span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">{vb["bookmaker_odds"]:.2f}</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Edge</span><br>
<span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: {edge_colour};">+{edge_pct:.1f}%</span>
</div>
<div>
<span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Suggested Stake</span><br>
<span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">${suggested_stake:.2f}</span>
</div>
</div>
</div>"""
    st.markdown(card_html, unsafe_allow_html=True)

    # Action row — Deep Dive button + Mark as Placed expander
    # Deep Dive navigates to Match Deep Dive for the full analysis narrative
    if st.button(
        "\U0001F50D Deep Dive",
        key=f"pick_dive_{idx}",
        type="secondary",
    ):
        st.query_params["match_id"] = str(vb["match_id"])
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
                    value=suggested_stake,
                    step=1.0,
                    format="%.2f",
                    key=f"stake_{idx}",
                )

            if st.button("Confirm Bet Placed", key=f"confirm_{idx}", type="primary"):
                user_id = get_default_user_id()
                if user_id is None:
                    st.error("No user found. Run `python run_pipeline.py setup` first.")
                else:
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
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Today\'s Picks</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Upcoming value bets, sorted by matchday then edge</p>',
    unsafe_allow_html=True,
)
st.divider()

# Edge threshold slider — filters picks in real-time.
# Default comes from config so changing settings.yaml propagates here.
try:
    _default_edge_pct = float(config.settings.value_betting.edge_threshold) * 100
except (AttributeError, TypeError, ValueError):
    _default_edge_pct = 5.0
edge_threshold = st.slider(
    "Minimum edge threshold",
    min_value=0.0,
    max_value=20.0,
    value=_default_edge_pct,
    step=0.5,
    format="%.1f%%",
    help="Filter picks by minimum edge. Higher = fewer but stronger picks.",
)
edge_threshold_decimal = edge_threshold / 100.0

# ── Upcoming Picks (actionable) ──────────────────────────────────────────
# Only scheduled matches, sorted by date ascending then edge descending.
# E24-01: No finished matches.  No all-time fallback.
with st.spinner("Loading upcoming picks..."):
    upcoming_bets = get_upcoming_value_bets(edge_threshold=edge_threshold_decimal)

if upcoming_bets:
    # Check if any picks are for today specifically
    today_str = date.today().isoformat()
    today_count = sum(1 for vb in upcoming_bets if vb["date"] == today_str)
    if today_count > 0:
        st.success(f"**{today_count} pick{'s' if today_count != 1 else ''} for today!**")
    else:
        # Picks exist but not for today — show when the next ones are
        next_date = upcoming_bets[0]["date"]
        st.info(f"No picks for today. Next picks: **{next_date}**")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Upcoming Picks", len(upcoming_bets))
    with col2:
        avg_edge = sum(vb["edge"] for vb in upcoming_bets) / len(upcoming_bets)
        st.metric("Avg Edge", f"{avg_edge:.1%}")
    with col3:
        high_conf = sum(1 for vb in upcoming_bets if vb["confidence"] == "high")
        st.metric("High Confidence", high_conf)

    st.divider()

    # Render each upcoming value bet as a card
    for idx, vb in enumerate(upcoming_bets):
        render_value_bet_card(vb, idx)

else:
    # Empty state — no upcoming value bets at all (MP §8)
    st.markdown(
        '<div class="bv-empty-state">'
        "No upcoming value bets found. Check back after the next pipeline run, "
        "or lower the edge threshold above."
        "</div>",
        unsafe_allow_html=True,
    )

# ── Recent Results (performance tracking) ────────────────────────────────
# Last 7 days of finished matches that had value bets — shows how past
# picks performed.  Compact cards, no "Mark as Placed" form.
st.divider()
st.markdown(
    '<div style="font-family: Inter, sans-serif; font-size: 18px; font-weight: 600; '
    'color: #E6EDF3; margin-bottom: 12px;">Recent Results</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted" style="margin-bottom: 12px;">'
    'Past picks from the last 7 days — track how the model performed</p>',
    unsafe_allow_html=True,
)

with st.spinner("Loading recent results..."):
    recent_results = get_recent_results(days=7, limit=20)

if recent_results:
    for idx, vb in enumerate(recent_results):
        render_result_card(vb, idx)
else:
    st.markdown(
        '<div style="font-family: Inter, sans-serif; font-size: 13px; '
        'color: #484F58; padding: 16px 0;">No finished matches with value '
        'bets in the last 7 days.</div>',
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
        'Over/Under 2.5 Goals, or Both Teams to Score (BTTS).</span>'
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
