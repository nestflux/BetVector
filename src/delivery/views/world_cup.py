"""
BetVector — World Cup 2026 Dashboard Page (WC-06-01)
=====================================================
Tournament hub: today's matches with predictions, group standings,
value bets, model performance, and winner probability chart.
"""

from datetime import datetime, timedelta
from html import escape

import plotly.graph_objects as go
import streamlit as st

from src.delivery._cache import CACHE_TTL_SLOW
from sqlalchemy import func as sa_func, select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.flags import render_flag
from src.world_cup.models import (
    WCMatch, WCPrediction, WCTeam, WCValueBet,
)
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.timeutil import (
    EASTERN, days_to_final, eastern_date, format_kickoff_et,
)
from src.world_cup.value_finder import (
    _load_betting_config,
    classify_fixture_verdict,
)

# Design system (CLAUDE.md Rule 5)
BG = "#0D1117"
SURFACE = "#161B22"
TEXT = "#E6EDF3"
TEXT_DIM = "#8B949E"
GREEN = "#3FB950"
RED = "#F85149"
YELLOW = "#D29922"
BORDER = "#30363D"
ACCENT = "#58A6FF"        # neutral model-bar colour when there's no actionable lean
MARKET_GREY = "#8B949E"   # de-vigged market bar (always grey, so the model gap pops)
BAR_TRACK = "#21262D"
_MOVE_EPS = 0.005         # ignore sub-0.5pp line drift as noise when showing movement

TOTAL_MATCHES = 104  # FIFA 2026: 48 group + 16 R32 + 8 R16 + 4 QF + 2 SF + 2 (3rd/Final)


def _section_header(title: str) -> None:
    st.markdown(
        f'<h2 class="bv-page-title" style="margin-top:1.5rem;">{title}</h2>',
        unsafe_allow_html=True,
    )


# ============================================================================
# Section 1 — Header + Tournament Progress
# ============================================================================

def _render_header() -> None:
    with get_session() as session:
        played = session.execute(
            select(sa_func.count())
            .select_from(WCMatch)
            .where(WCMatch.status == "finished")
        ).scalar() or 0

    # "Days to final" counts to the configured tournament end date (the final),
    # NOT the latest fixture in the DB. Early in the tournament the Odds API has
    # published only a rolling window of group fixtures (no knockout bracket yet),
    # so max(WCMatch.date) would point at a group game weeks before the real final
    # and badly understate the countdown. config/worldcup_2026.yaml is the source.
    dtf = days_to_final()
    countdown = (
        f" · {dtf} day{'s' if dtf != 1 else ''} to final" if dtf is not None else ""
    )

    # Slim one-line header — replaces the former 3-metric block + progress bar
    # so the page leads with content, not chrome (WC-08-03).
    st.markdown(
        "#### 🏆 FIFA World Cup 2026 "
        f"<span style='color:{TEXT_DIM};font-weight:400;font-size:0.85rem'>"
        f"· {played}/{TOTAL_MATCHES} played{countdown}</span>",
        unsafe_allow_html=True,
    )


# ============================================================================
# Section 2 — Upcoming Fixtures (Tab 1)
# ============================================================================

# Verdict tier → (accent colour, glyph). value = actionable shadow edge;
# capped = edge too big to trust (re-check); none = no model edge.
_VERDICT_STYLE = {
    "value":  (GREEN, "✓"),
    "capped": (YELLOW, "⚠"),
    "none":   (TEXT_DIM, "—"),
}


def _verdict_chip_html(v) -> str:
    """One at-a-glance, colour-tiered verdict for a fixture (DF-04): the model's
    single best shadow pick as selection · edge · best price. Capped edges are
    flagged as re-check (likely model noise), never dressed up as value."""
    colour, glyph = _VERDICT_STYLE.get(v.tier, _VERDICT_STYLE["none"])
    if v.tier == "none" or v.label is None:
        return f'<span style="color:{TEXT_DIM};font-size:0.8rem;">{glyph} no model edge</span>'
    label = escape(v.label)
    edge = f"{v.edge:+.1%}"
    if v.tier == "capped":
        return (
            f'<span style="color:{colour};font-weight:700;">{glyph} {label} {edge}</span> '
            f'<span style="color:{TEXT_DIM};font-size:0.72rem;">re-check · likely model noise</span>'
        )
    # value
    price = f'@ {v.best_odds:.2f}' if v.best_odds else ""
    return (
        f'<span style="color:{colour};font-weight:700;">{glyph} {label} {edge}</span> '
        f'<span style="color:{TEXT_DIM};font-size:0.72rem;">{escape(price)}</span>'
    )


# Note: _pct (percent-or-em-dash) is defined once near the model-performance
# section below and reused here — no duplicate definition.
def _verdict_detail_html(pred, v, home_name: str, away_name: str) -> str:
    """Full model probabilities behind the per-fixture expander (DF-04):
    1X2, goals, BTTS, expected goals, and the verdict pick's price vs market."""
    if not pred:
        return f'<span style="color:{TEXT_DIM};font-size:0.8rem;">No model prediction for this fixture.</span>'

    def row(label, body):
        return (
            f'<div style="margin:2px 0;font-size:0.8rem;">'
            f'<span style="color:{TEXT_DIM};display:inline-block;min-width:96px;">{label}</span>'
            f'<span style="color:{TEXT};">{body}</span></div>'
        )

    o25 = pred.over_25_prob
    btts = pred.btts_prob
    rows = [
        row("Match result",
            f'{escape(home_name)} {_pct(pred.home_win_prob)} · '
            f'Draw {_pct(pred.draw_prob)} · '
            f'{escape(away_name)} {_pct(pred.away_win_prob)}'),
        row("Goals O/U 2.5",
            f'Over {_pct(o25)} · Under {_pct(1 - o25 if o25 is not None else None)}'),
        row("Both score",
            f'Yes {_pct(btts)} · No {_pct(1 - btts if btts is not None else None)}'),
        row("Expected goals",
            f'{escape(home_name)} {pred.home_expected_goals:.2f} · '
            f'{escape(away_name)} {pred.away_expected_goals:.2f}'),
    ]
    if v.tier in ("value", "capped") and v.label:
        book = f' ({escape(v.bookmaker)})' if v.bookmaker else ""
        rows.append(row(
            "Verdict pick",
            f'{escape(v.label)} @ {v.best_odds:.2f}{book} — '
            f'model {_pct(v.model_prob)} vs market {_pct(v.implied_prob)} '
            f'(edge {v.edge:+.1%})'))
    return "".join(rows)


def _render_todays_matches() -> None:
    """Decision-first upcoming-fixtures strip for Tab 1 — today + the next 2 days
    in US Eastern. Each row leads with one colour-tiered shadow verdict (value /
    re-check / no-edge) from the model's best pick; full probabilities sit behind
    a per-fixture expander. Today's games are highlighted (DF-04)."""
    _section_header("Upcoming Fixtures")

    today_et = datetime.now(EASTERN).date()
    window_end = today_et + timedelta(days=2)
    # Load ONLY the date window (with a ±1-day buffer to cover the UTC↔ET
    # boundary) instead of every WC match. WCMatch.date is an ISO "YYYY-MM-DD"
    # string, so lexical >=/<= bounds are chronological on both SQLite and
    # Postgres. This is the single biggest Neon-egress cut on this page (~10
    # rows + their odds, not all ~104 matches); the precise ET filter below is
    # unchanged.
    sql_from = (today_et - timedelta(days=1)).isoformat()
    sql_to = (window_end + timedelta(days=1)).isoformat()

    with get_session() as session:
        matches = session.execute(
            select(WCMatch)
            .options(
                joinedload(WCMatch.home_team),
                joinedload(WCMatch.away_team),
                joinedload(WCMatch.predictions),
                joinedload(WCMatch.odds),
            )
            .where(WCMatch.date >= sql_from, WCMatch.date <= sql_to)
            .order_by(WCMatch.date, WCMatch.kickoff_time)
        ).unique().scalars().all()

        # today + next 2 Eastern days, not yet finished
        upcoming = []
        for m in matches:
            if m.status == "finished":
                continue
            ed = eastern_date(m.date, m.kickoff_time)
            if not ed:
                continue
            ed_date = datetime.strptime(ed, "%Y-%m-%d").date()
            if today_et <= ed_date <= window_end:
                upcoming.append((m, ed_date))

        if not upcoming:
            st.info("No World Cup matches in the next 3 days.")
            return

        st.caption(
            f"Next 3 days · times in ET · {len(upcoming)} fixtures · "
            "verdicts are shadow (track-only) — decision-support, not staked"
        )

        # Edge band/ceiling loaded once; the verdict reuses the value finder's math.
        cfg = _load_betting_config()

        for m, ed_date in upcoming:
            home, away = m.home_team, m.away_team
            home_name = home.name if home else "?"
            away_name = away.name if away else "?"
            home_flag = render_flag(home.fifa_code) if home else ""
            away_flag = render_flag(away.fifa_code) if away else ""
            kickoff = format_kickoff_et(m.date, m.kickoff_time)
            pred = next((p for p in m.predictions if p.model_name == MODEL_NAME), None)
            verdict = classify_fixture_verdict(pred, list(m.odds), home_name, away_name, cfg)

            is_today = ed_date == today_et
            bg = SURFACE if is_today else "transparent"
            accent = GREEN if is_today else BORDER

            st.markdown(
                f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;'
                f'padding:6px 10px;margin-bottom:2px;background:{bg};'
                f'border-left:3px solid {accent};border-radius:4px;font-size:0.85rem;">'
                f'<span style="color:{TEXT_DIM};min-width:96px;font-size:0.72rem;">{kickoff}</span>'
                f'<span style="flex:1;min-width:160px;">{home_flag} {escape(home_name)} '
                f'<span style="color:{TEXT_DIM};font-size:0.75rem;">v</span> '
                f'{escape(away_name)} {away_flag}</span>'
                f'<span style="flex:1;min-width:180px;text-align:right;">{_verdict_chip_html(verdict)}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            with st.expander("Model probabilities", expanded=False):
                st.markdown(
                    _verdict_detail_html(pred, verdict, home_name, away_name),
                    unsafe_allow_html=True,
                )
                # DF-08: open the full read-only deep dive (heatmap + model-vs-books)
                # for this fixture. Lives in the expander so the strip stays clean.
                if st.button("🔍 Open full deep dive", key=f"wc_dd_fx_{m.id}",
                             use_container_width=True):
                    st.session_state["wc_deep_dive_match_id"] = m.id
                    st.switch_page("views/wc_deep_dive.py")


# ============================================================================
# Shared — Group standings computation (used by sections 3 and 3b)
# ============================================================================

@st.cache_data(ttl=CACHE_TTL_SLOW, show_spinner=False)
def _compute_group_standings() -> dict[str, list[dict]]:
    """Compute group standings from DB. Returns {group: [sorted team dicts]}."""
    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()
        finished = session.execute(
            select(WCMatch)
            .where(WCMatch.status == "finished", WCMatch.stage == "group")
        ).scalars().all()

    raw: dict[str, dict[int, dict]] = {}
    for t in teams:
        if t.group_letter not in raw:
            raw[t.group_letter] = {}
        raw[t.group_letter][t.id] = {
            "name": t.name, "fifa_code": t.fifa_code,
            "pts": 0, "gd": 0, "gf": 0, "mp": 0, "w": 0, "d": 0, "l": 0,
        }

    for m in finished:
        if m.home_goals is None or not m.group_letter:
            continue
        g = m.group_letter
        h = raw.get(g, {}).get(m.home_team_id)
        a = raw.get(g, {}).get(m.away_team_id)
        if not h or not a:
            continue

        h["mp"] += 1
        a["mp"] += 1
        h["gf"] += m.home_goals
        a["gf"] += m.away_goals
        h["gd"] += m.home_goals - m.away_goals
        a["gd"] += m.away_goals - m.home_goals

        if m.home_goals > m.away_goals:
            h["pts"] += 3
            h["w"] += 1
            a["l"] += 1
        elif m.home_goals == m.away_goals:
            h["pts"] += 1
            a["pts"] += 1
            h["d"] += 1
            a["d"] += 1
        else:
            a["pts"] += 3
            a["w"] += 1
            h["l"] += 1

    result: dict[str, list[dict]] = {}
    for g, teams_dict in raw.items():
        result[g] = sorted(
            teams_dict.values(),
            key=lambda x: (-x["pts"], -x["gd"], -x["gf"]),
        )
    return result


# ============================================================================
# Section 3 — Group Standings
# ============================================================================

def _render_group_standings() -> None:
    standings = _compute_group_standings()

    # Display in 2-column grid (6 rows)
    # Color-coding: top 2 = green (qualified), 3rd = yellow (possible R32),
    # 4th = red (eliminated). FIFA 2026: top 2 + best 8 third-place teams advance.
    sorted_groups = sorted(standings.keys())
    for i in range(0, len(sorted_groups), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(sorted_groups):
                break
            g = sorted_groups[idx]
            teams_sorted = standings[g]
            with col:
                st.markdown(f"**Group {g}**")
                has_results = any(t["mp"] > 0 for t in teams_sorted)
                rows_html = ""
                for rank, t in enumerate(teams_sorted):
                    gd_str = f"{t['gd']:+d}" if t["mp"] > 0 else "0"
                    if has_results:
                        if rank < 2:
                            color = GREEN
                        elif rank == 2:
                            color = YELLOW
                        else:
                            color = RED
                        name_cell = (f'{render_flag(t["fifa_code"])} '
                                     f'<span style="color:{color}">●</span> {escape(t["name"])}')
                    else:
                        name_cell = f'{render_flag(t["fifa_code"])} {escape(t["name"])}'
                    rows_html += (
                        f"<tr>"
                        f"<td>{name_cell}</td>"
                        f"<td>{t['mp']}</td><td>{t['w']}</td>"
                        f"<td>{t['d']}</td><td>{t['l']}</td>"
                        f"<td>{gd_str}</td><td><b>{t['pts']}</b></td>"
                        f"</tr>"
                    )
                st.markdown(
                    f'<table style="width:100%;font-size:0.85rem;border-collapse:collapse;">'
                    f'<thead><tr style="color:{TEXT_DIM};border-bottom:1px solid {BORDER};">'
                    f"<th style='text-align:left'>Team</th>"
                    f"<th>MP</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th>"
                    f"</tr></thead><tbody>{rows_html}</tbody></table>",
                    unsafe_allow_html=True,
                )


# ============================================================================
# Section 3b — Group Advancement Probabilities (WC-06-02)
# ============================================================================

def _color_for_prob(p: float) -> str:
    if p >= 0.8:
        return GREEN
    if p >= 0.3:
        return YELLOW
    return RED


def _render_group_advancement() -> None:
    try:
        result = _cached_simulation()
        probs = result.get("team_probs", {})
        pos_probs = result.get("position_probs", {})
        if not probs:
            st.info("No simulation data available.")
            return
    except Exception as e:
        st.warning(f"Could not load simulation: {e}")
        return

    # Extract team→group mapping from standings (no extra DB query)
    standings = _compute_group_standings()
    team_group_map: dict[str, str] = {}
    for g, team_list in standings.items():
        for t in team_list:
            team_group_map[t["name"]] = g

    # Build per-group advancement data with position breakdown
    groups_data: dict[str, list[dict]] = {}
    for name, sp in probs.items():
        g = team_group_map.get(name)
        if not g:
            continue
        pp = pos_probs.get(name, {})
        groups_data.setdefault(g, []).append({
            "name": name,
            "advance": sp.get("group", 0),
            "p_1st": pp.get("p_1st", 0),
            "p_2nd": pp.get("p_2nd", 0),
            "p_3rd_q": pp.get("p_3rd_qualify", 0),
            "p_elim": pp.get("p_4th", 0) + (1 - sp.get("group", 0) - pp.get("p_4th", 0)),
        })

    # Display in 2-column grid with expanders
    sorted_groups = sorted(groups_data.keys())
    for i in range(0, len(sorted_groups), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(sorted_groups):
                break
            g = sorted_groups[idx]
            teams_sorted = sorted(groups_data[g], key=lambda x: -x["advance"])

            with col:
                # Plain group block (no inner expander — the whole section sits
                # inside a top-level expander, and Streamlit forbids nesting them).
                st.markdown(f"**Group {g}**")
                for t in teams_sorted:
                    adv = t["advance"]
                    color = _color_for_prob(adv)
                    st.markdown(
                        f'<span style="color:{color}">●</span> '
                        f'**{escape(t["name"])}** — P(advance) = {adv:.0%}',
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"1st: {t['p_1st']:.0%} · 2nd: {t['p_2nd']:.0%} · "
                        f"3rd-Q: {t['p_3rd_q']:.0%} · Elim: {1 - adv:.0%}"
                    )
                st.write("")

    # What-if scenario selector
    _section_header("What-If Scenario")
    st.caption("Pick a hypothetical result for a remaining match to see how it affects group standings.")

    with get_session() as session:
        scheduled = session.execute(
            select(WCMatch)
            .where(WCMatch.status != "finished", WCMatch.stage == "group")
            .options(joinedload(WCMatch.home_team), joinedload(WCMatch.away_team))
            .order_by(WCMatch.date, WCMatch.kickoff_time)
        ).unique().scalars().all()

    if not scheduled:
        st.info("All group matches have been played.")
    else:
        match_labels = {
            m.id: f"{m.home_team.name if m.home_team else '?'} vs "
                  f"{m.away_team.name if m.away_team else '?'} ({m.date})"
            for m in scheduled
        }
        selected_id = st.selectbox(
            "Select a match",
            options=list(match_labels.keys()),
            format_func=lambda x: match_labels[x],
        )
        c1, c2 = st.columns(2)
        home_goals = c1.number_input("Home goals", min_value=0, max_value=10, value=1, key="wif_hg")
        away_goals = c2.number_input("Away goals", min_value=0, max_value=10, value=0, key="wif_ag")

        if st.button("Simulate with this result"):
            sel_match = next((m for m in scheduled if m.id == selected_id), None)
            if sel_match:
                # Recompute standings with the hypothetical result injected
                what_if_standings = _compute_group_standings()
                g = sel_match.group_letter
                if g and g in what_if_standings:
                    h_team = sel_match.home_team.name if sel_match.home_team else None
                    a_team = sel_match.away_team.name if sel_match.away_team else None
                    for t in what_if_standings[g]:
                        if t["name"] == h_team:
                            t["gf"] += home_goals
                            t["gd"] += home_goals - away_goals
                            t["mp"] += 1
                            if home_goals > away_goals:
                                t["pts"] += 3
                            elif home_goals == away_goals:
                                t["pts"] += 1
                        elif t["name"] == a_team:
                            t["gf"] += away_goals
                            t["gd"] += away_goals - home_goals
                            t["mp"] += 1
                            if away_goals > home_goals:
                                t["pts"] += 3
                            elif home_goals == away_goals:
                                t["pts"] += 1

                    what_if_standings[g].sort(
                        key=lambda x: (-x["pts"], -x["gd"], -x["gf"]),
                    )
                    st.markdown(f"**Group {g} — with {h_team} {home_goals}-{away_goals} {a_team}:**")
                    for rank, t in enumerate(what_if_standings[g]):
                        color = GREEN if rank < 2 else (YELLOW if rank == 2 else RED)
                        st.markdown(
                            f'<span style="color:{color}">●</span> '
                            f'{t["name"]} — {t["pts"]} pts, GD {t["gd"]:+d}',
                            unsafe_allow_html=True,
                        )


def _render_third_place() -> None:
    """Third-place race — teams currently ranked 3rd in their group, sorted by
    simulated P(qualify as one of the best-8 third-placed teams). Its own
    collapsible on the Groups tab (WC-08-05)."""
    try:
        pos_probs = _cached_simulation().get("position_probs", {})
    except Exception as e:
        st.warning(f"Could not load simulation: {e}")
        return
    standings = _compute_group_standings()

    st.caption(
        "Best 8 of 12 third-placed teams advance to the Round of 32. "
        "Teams shown are currently ranked 3rd in their group."
    )

    third_place_rows = []
    for g in sorted(standings.keys()):
        group_teams = standings[g]
        if len(group_teams) >= 3:
            third = group_teams[2]
            pp = pos_probs.get(third["name"], {})
            p_3rd_q = pp.get("p_3rd_qualify", 0)
            exp_pts = pp.get("expected_pts", 0)
            exp_gd = pp.get("expected_gd", 0)
            third_place_rows.append({
                "Team": third["name"],
                "Group": g,
                "Pts": third["pts"],
                "GD": f"{third['gd']:+d}" if third["mp"] > 0 else "0",
                "E[Pts]": f"{exp_pts:.1f}",
                "E[GD]": f"{exp_gd:+.1f}",
                "P(Qualify 3rd)": f"{p_3rd_q:.0%}",
                "_sort": p_3rd_q,
            })

    if third_place_rows:
        third_place_rows.sort(key=lambda x: -x["_sort"])
        display_rows = [{k: v for k, v in r.items() if k != "_sort"} for r in third_place_rows]
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Third-place standings appear once group matches are played.")


# ============================================================================
# Section 4 — Value Bets
# ============================================================================

# --- Log-from-advice (WC-BET-03): turn a model value pick into a tracked bet ----
_VB_MARKET_MAP = {"h2h": "1X2", "totals": "OU25", "btts": "BTTS"}


def _vb_to_canon(market_type, selection):
    """Map a WCValueBet (market_type/selection) to the bet-tracker canonical
    (market, selection), or None if not a loggable single. Value bets cover 1X2,
    O/U 2.5 (the only totals line the model prices), and BTTS."""
    m = _VB_MARKET_MAP.get((market_type or "").lower())
    sel = (selection or "").lower()
    if m and sel in {"home", "draw", "away", "over", "under", "yes", "no"}:
        return (m, sel)
    return None


def _render_log_pick_control(picks: list) -> None:
    """Inline 'log one of these picks to My Bets' control under the value bets:
    choose a model pick (odds pre-filled from the best book), set your stake, and
    it's logged to the user's WC bets tagged 🎯 (from a model tip). Empty → silent."""
    if not picks:
        return
    from src.auth import get_session_user_id
    from src.world_cup.bets import MARKET_LABELS, log_wc_bet
    with st.expander("➕ Log one of these picks to My Bets"):
        labels, by_label = [], {}
        for p in picks:
            lbl = (f'{p["home"]} v {p["away"]} · '
                   f'{MARKET_LABELS.get(p["market"], p["market"])} '
                   f'{_SEL_LABELS.get(p["selection"], p["selection"])} · '
                   f'@{p["odds"]:.2f} (+{(p["edge"] or 0) * 100:.0f}%)')
            labels.append(lbl)
            by_label[lbl] = p
        choice = st.selectbox("Model pick", labels, key="wc_logpick_sel")
        p = by_label[choice]
        c1, c2 = st.columns(2)
        with c1:
            odds = st.number_input("Your odds", min_value=1.01,
                                   value=float(p["odds"]), step=0.05,
                                   key="wc_logpick_odds")
        with c2:
            stake = st.number_input("Stake ($)", min_value=0.0, value=10.0,
                                    step=5.0, key="wc_logpick_stake")
        b1, b2 = st.columns(2)
        with b1:
            if st.button("➕ Log this pick", type="primary", key="wc_logpick_btn"):
                bid = log_wc_bet(
                    get_session_user_id(), p["match_id"], p["market"], p["selection"],
                    float(odds), float(stake), bookmaker=p.get("bookmaker"),
                    model_prob=p.get("model_prob"), edge=p.get("edge"),
                    source="research_card")
                if bid:
                    st.toast("🎯 Logged to My Bets", icon="🎯")
                    st.rerun()
                else:
                    st.error("Couldn't log — odds must be > 1 and stake > 0.")
        with b2:
            # WC-ACC-03: stage this pick as a leg on the accumulator slip (assembled
            # in the 🎟️ My Bets tab). Captures model_prob / edge frozen at add time.
            if st.button("➕ Add to slip", key="wc_addslip_btn"):
                slip = st.session_state.setdefault("wc_acca_slip", [])
                slip.append({
                    "match_id": p["match_id"], "home": p["home"], "away": p["away"],
                    "market_type": p["market"],
                    "market_label": MARKET_LABELS.get(p["market"], p["market"]),
                    "selection": p["selection"], "odds": float(odds),
                    "model_prob": p.get("model_prob"), "edge": p.get("edge"),
                    "bookmaker": p.get("bookmaker"), "source": "research_card",
                })
                st.session_state["wc_acca_slip"] = slip
                st.toast("🎫 Added to slip — build it in 🎟️ My Bets", icon="🎫")
                st.rerun()
        st.caption("Odds default to the best book price — edit to what you actually "
                   "got. **Log** tracks it as a single 🎯 bet; **Add to slip** stages "
                   "it as an accumulator leg in 🎟️ My Bets.")


def _render_value_bets() -> None:
    _section_header("Value Bets")
    st.caption(
        "⚠️ Tracked / shadow picks — the WC model is not yet calibrated against a "
        "sharp market on this little data. Monitor CLV before staking real money."
    )

    picks: list = []
    with get_session() as session:
        vbs = session.execute(
            select(WCValueBet)
            .join(WCMatch)
            .where(WCMatch.status != "finished")
            .options(
                joinedload(WCValueBet.match).joinedload(WCMatch.home_team),
                joinedload(WCValueBet.match).joinedload(WCMatch.away_team),
            )
            .order_by(WCValueBet.edge.desc())
            .limit(20)
        ).unique().scalars().all()

        if not vbs:
            st.info("No value bets found for upcoming matches.")
            return

        rows = []
        for vb in vbs:
            home = vb.match.home_team if vb.match else None
            away = vb.match.away_team if vb.match else None
            hn = home.name if home else "?"
            an = away.name if away else "?"
            rows.append({
                "Match": f"{hn} vs {an}",
                "Market": f"{vb.market_type}/{vb.selection}",
                "Edge": f"+{vb.edge:.1%}",
                "Odds": f"{vb.best_odds:.2f}",
                "Bookmaker": vb.bookmaker,
                "Kelly": f"{vb.kelly_stake:.2%}" if vb.kelly_stake else "—",
            })
            mapped = _vb_to_canon(vb.market_type, vb.selection)
            if mapped and vb.best_odds:
                picks.append({
                    "match_id": vb.match_id, "home": hn, "away": an,
                    "market": mapped[0], "selection": mapped[1],
                    "odds": vb.best_odds, "edge": vb.edge,
                    "model_prob": vb.model_prob, "bookmaker": vb.bookmaker,
                })

    st.dataframe(rows, use_container_width=True, hide_index=True)
    _render_log_pick_control(picks)


# ============================================================================
# Section 4b — Research Card (WC-09-04) + lineup rotation flag (WC-10-07)
# ============================================================================

def _render_lineup_flag(match_id: int) -> None:
    """Confirmed XI + a rotation/absence flag for the selected match (WC-10-07).
    Decision-support only — a hypothesis to re-check, never a model input."""
    from src.world_cup.lineups import lineup_signal

    sig = lineup_signal(match_id)
    if not sig:
        return
    teams = sig["teams"]
    if not any(t.get("status") == "announced" for t in teams):
        st.caption("🔒 Lineups not announced yet — ESPN posts the XI ~1h before kickoff.")
        return

    st.markdown("**Confirmed lineups**")
    heavy = False
    for t in teams:
        if t.get("status") != "announced":
            st.caption(f"{t['team']}: XI not announced yet")
            continue
        note = ""
        if t.get("heavy_rotation"):
            heavy = True
            note = f"  —  ⚠️ **heavy rotation: {t['changes']} changes vs last XI**"
        elif t.get("changes") is not None:
            note = f"  ({t['changes']} change{'s' if t['changes'] != 1 else ''} vs last XI)"
        st.markdown(f"**{t['team']}** · {t.get('formation') or '?'}{note}")
        st.caption(", ".join(t["xi"]))

    if heavy:
        st.warning(
            "Heavy rotation is a hypothesis to re-check — a rested XI can invalidate a "
            "value pick. Decision-support only; the model and value bets are unchanged."
        )


# ---------------------------------------------------------------------------
# DF-06 — Research card: grouped model-vs-market paired bars
# ---------------------------------------------------------------------------
# The card groups selections into Match result / Goals / BTTS blocks. Each
# selection draws two stacked bars — model (accent) over de-vigged market (grey)
# — so the GAP between them is the visual; the edge is highlighted only inside
# the trust range, and a gap past the ceiling is labelled likely model error.
# All the grouping / wording / trust logic lives in research.summarize_card; here
# we only turn its blocks + headline into HTML.

def _pill(text: str, colour: str, filled: bool = False) -> str:
    """Small mono pill — filled (highlight) or outlined."""
    if filled:
        return (f'<span style="background:{colour};color:{BG};border-radius:4px;'
                f'padding:1px 6px;font-size:0.72rem;font-weight:700;'
                f'font-family:JetBrains Mono,monospace;">{escape(text)}</span>')
    return (f'<span style="border:1px solid {colour};color:{colour};border-radius:4px;'
            f'padding:0 5px;font-size:0.72rem;font-weight:600;'
            f'font-family:JetBrains Mono,monospace;">{escape(text)}</span>')


def _research_edge_tag(row: dict) -> str:
    """Right-aligned edge marker for one selection: a filled green pill when it's a
    trustworthy lean (with the best price), an amber 'likely model error' pill when
    capped, dim text otherwise; plus a tiny ▲/▼ market-move-since-open marker."""
    edge = row.get("edge")
    if edge is None:
        return f'<span style="color:{TEXT_DIM};font-size:0.7rem;">no price</span>'
    trust = row.get("trust", "none")
    parts = []
    if trust == "value":
        parts.append(_pill(f"{edge:+.0%}", GREEN, filled=True))
        if row.get("best_odds"):
            book = f" {escape(row['best_book'])}" if row.get("best_book") else ""
            parts.append(f'<span style="color:{TEXT_DIM};font-size:0.7rem;">'
                         f'@ {row["best_odds"]:.2f}{book}</span>')
    elif trust == "capped":
        parts.append(_pill(f"{edge:+.0%} ⚠", YELLOW))
        parts.append(f'<span style="color:{TEXT_DIM};font-size:0.68rem;">likely model error</span>')
    else:
        parts.append(f'<span style="color:{TEXT_DIM};font-size:0.72rem;'
                     f'font-family:JetBrains Mono,monospace;">{edge:+.0%}</span>')
    move = row.get("movement")
    if move is not None and abs(move) >= _MOVE_EPS:
        arrow = "▲" if move > 0 else "▼"
        mcol = GREEN if move > 0 else TEXT_DIM
        parts.append(f'<span style="color:{mcol};font-size:0.66rem;" '
                     f'title="market move toward this selection since open">'
                     f'{arrow}{abs(move):.0%}</span>')
    return " ".join(parts)


def _research_bar_html(row: dict) -> str:
    """One selection: label + edge tag, then a model bar (accent) stacked over a
    market bar (grey). The two widths differing IS the edge, made visual."""
    label = escape(row.get("label") or row.get("selection") or "")
    model_col = {"value": GREEN, "capped": YELLOW}.get(row.get("trust"), ACCENT)

    def bar(caption: str, val, fill: str) -> str:
        pct = f"{val:.0%}" if val is not None else "—"
        width = max(0.0, min(1.0, val)) * 100 if val is not None else 0.0
        return (
            f'<div style="display:flex;align-items:center;gap:8px;margin:2px 0;">'
            f'<span style="width:48px;color:{TEXT_DIM};font-size:0.64rem;'
            f'text-transform:uppercase;letter-spacing:0.03em;">{caption}</span>'
            f'<div style="flex:1;background:{BAR_TRACK};border-radius:3px;height:11px;'
            f'overflow:hidden;">'
            f'<div style="width:{width:.1f}%;background:{fill};height:100%;'
            f'border-radius:3px;"></div></div>'
            f'<span style="width:40px;text-align:right;font-family:JetBrains Mono,monospace;'
            f'font-size:0.72rem;color:{TEXT};">{pct}</span></div>'
        )

    return (
        f'<div style="margin:9px 0 12px 0;">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
        f'margin-bottom:2px;gap:8px;">'
        f'<span style="color:{TEXT};font-size:0.85rem;font-weight:600;">{label}</span>'
        f'<span style="text-align:right;">{_research_edge_tag(row)}</span></div>'
        f'{bar("Model", row.get("model_prob"), model_col)}'
        f'{bar("Market", row.get("market_prob"), MARKET_GREY)}'
        f'</div>'
    )


def _research_block_html(block: dict) -> str:
    """A market block: title, its one-line plain-English read, then the bars."""
    read = block.get("read") or {}
    read_col = {"value": GREEN, "capped": YELLOW}.get(read.get("class"), TEXT_DIM)
    bars = "".join(_research_bar_html(r) for r in block.get("selections", []))
    return (
        f'<div style="margin:14px 0 4px 0;">'
        f'<div style="color:{TEXT};font-weight:700;font-size:0.95rem;'
        f'border-bottom:1px solid {BORDER};padding-bottom:4px;margin-bottom:4px;">'
        f'{escape(block.get("title", ""))}</div>'
        f'<div style="color:{read_col};font-size:0.8rem;margin:4px 0 8px 0;">'
        f'{escape(read.get("text", ""))}</div>'
        f'{bars}</div>'
    )


def _research_headline_html(h: dict) -> str:
    """The card's headline lean banner — green when it names a trustworthy lean,
    amber when the biggest gap is past the ceiling, neutral on agreement. Line
    movement is folded in as the confirmation signal for a trustworthy lean."""
    cls = h.get("class", "none")
    if cls == "value":
        icon, col, bg = "🟢", GREEN, "rgba(63,185,80,0.10)"
    elif cls == "capped":
        icon, col, bg = "⚠", YELLOW, "rgba(210,153,34,0.10)"
    else:
        icon, col, bg = "•", TEXT_DIM, "rgba(139,148,158,0.07)"

    conf = ""
    if cls == "value":
        move = h.get("movement")
        if move is not None and move > _MOVE_EPS:
            conf = (f'<div style="color:{TEXT_DIM};font-size:0.74rem;margin-top:3px;">'
                    f'Line confirms — market has drifted toward it since open '
                    f'({move:+.0%}).</div>')
        elif move is not None and move < -_MOVE_EPS:
            conf = (f'<div style="color:{TEXT_DIM};font-size:0.74rem;margin-top:3px;">'
                    f'Caution — market has drifted away since open ({move:+.0%}); '
                    f'the edge may be going stale.</div>')

    return (
        f'<div style="background:{bg};border:1px solid {col};border-left:3px solid {col};'
        f'border-radius:8px;padding:10px 14px;margin:4px 0 12px 0;">'
        f'<span style="color:{col};font-weight:700;font-size:0.9rem;">'
        f'{icon} {escape(h.get("text", ""))}</span>{conf}</div>'
    )


def _disagreement_row_html(d: dict) -> str:
    """One disagreement as a verdict-tagged, ranked sentence (DF-07): ✓ green
    conviction (edge within the ceiling — a backable shadow lean) or ⚠ amber
    likely-model-error (edge past the ceiling). The signed edge leads as a
    scannable, colour-coded rank marker; the sentence carries the call."""
    if d.get("trust") == "capped":
        glyph, colour = "⚠", YELLOW
    else:
        glyph, colour = "✓", GREEN
    edge = f'{d["edge"]:+.0%}'
    return (
        f'<div style="display:flex;gap:10px;align-items:baseline;padding:6px 0;'
        f'border-bottom:1px solid {BORDER};">'
        f'<span style="color:{colour};font-weight:700;flex-shrink:0;width:14px;">{glyph}</span>'
        f'<span style="color:{colour};font-weight:700;font-family:JetBrains Mono,monospace;'
        f'flex-shrink:0;width:46px;text-align:right;">{edge}</span>'
        f'<span style="color:{TEXT};font-size:0.86rem;line-height:1.35;">'
        f'{escape(d.get("text", ""))}</span>'
        f'</div>'
    )


def _render_research_card() -> None:
    """Per-match decision support: model vs de-vigged market, edge, line movement,
    and best price across books. Where you disagree with the consensus — a thing
    to investigate, not an auto-bet."""
    _section_header("🔍 Research Card")
    st.caption(
        "Model vs market for one match — your disagreement with the consensus and "
        "the best available price. A hypothesis to investigate, not a bet."
    )

    with get_session() as session:
        upcoming = session.execute(
            select(WCMatch)
            .where(WCMatch.status != "finished")
            .options(joinedload(WCMatch.home_team), joinedload(WCMatch.away_team))
            .order_by(WCMatch.date, WCMatch.kickoff_time)
        ).unique().scalars().all()
        labels = {
            m.id: f"{m.home_team.name if m.home_team else '?'} v "
                  f"{m.away_team.name if m.away_team else '?'} "
                  f"({format_kickoff_et(m.date, m.kickoff_time, with_day=True)})"
            for m in upcoming
        }

    if not labels:
        st.info("No upcoming matches to research.")
        return

    sel_id = st.selectbox("Match", options=list(labels.keys()),
                          format_func=lambda x: labels[x], key="research_match")

    # DF-08: the research card's primary entry to the full deep dive — heatmap +
    # model-vs-every-book for the match selected above (session-state + nav switch).
    if st.button("🔍 Open full deep dive", key="wc_dd_research"):
        st.session_state["wc_deep_dive_match_id"] = sel_id
        st.switch_page("views/wc_deep_dive.py")

    from src.world_cup.research import build_research_card
    card = build_research_card(sel_id)
    if not card or not card["selections"]:
        st.info("No odds / prediction data for this match yet.")
        return

    # DF-06: lead with one headline lean, then a block per market (Match result /
    # Goals / BTTS). Each selection is a model-vs-market paired bar so the gap is
    # the visual; a one-line read says where the edge is. Grouping + wording come
    # from research.summarize_card (attached to the card as blocks/headline).
    headline_html = _research_headline_html(card.get("headline", {}))
    blocks_html = "".join(_research_block_html(b) for b in card.get("blocks", []))
    st.markdown(
        f'<div style="background:{SURFACE};border:1px solid {BORDER};border-radius:10px;'
        f'padding:12px 18px 16px 18px;">{headline_html}{blocks_html}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Each selection shows the model probability (accent) over the de-vigged "
        "market (grey) — the gap between the bars is the edge. A lean is highlighted "
        "only inside the trust range; a gap past the ceiling is flagged likely model "
        "error, not a bet. ▲/▼ = market move since open (the confirmation signal). "
        "xG form: no reliable WC source — deferred."
    )

    _render_lineup_flag(sel_id)

    # Review queue — biggest model-market disagreements across upcoming matches
    # (DF-07). Each row is a ranked sentence with an explicit verdict: ✓ conviction
    # (edge within the trust ceiling) vs ⚠ likely model error (past it), collapsed
    # to the side the model favours and ordered so trustworthy calls lead.
    st.markdown("**Biggest disagreements to review**")
    from src.world_cup.research import build_disagreements
    disagreements = build_disagreements(limit=10)
    if not disagreements:
        st.caption(
            "No notable disagreements right now — the model is broadly in line with "
            "the market (or odds / predictions aren't in for these fixtures yet)."
        )
        return
    st.markdown(
        "".join(_disagreement_row_html(d) for d in disagreements),
        unsafe_allow_html=True,
    )
    st.caption(
        "✓ conviction = a model edge inside the trust range — a shadow lean to "
        "investigate. ⚠ likely model error = a gap past the ceiling, too big to "
        "trust. Ranked by trustworthy edge, convictions first. Not bets."
    )


# ============================================================================
# Section 5a — Shadow Scorecard (WC-09-02)
# ============================================================================

def _render_scorecard() -> None:
    """CLV · calibration · paper P&L on tracked/shadow picks — the self-assessment
    rig (CLV is the leading edge indicator, not realized money)."""
    _section_header("Shadow Scorecard")
    st.caption(
        "Self-assessment on tracked / shadow picks. CLV (closing-line value) is the "
        "leading indicator of edge — not realized money."
    )

    from src.world_cup.scorecard import compute_wc_scorecard
    sc = compute_wc_scorecard()

    if sc.get("n", 0) == 0:
        st.info(
            "No settled shadow picks yet — the scorecard fills as tracked picks' "
            "matches finish. CLV needs ~30+ picks before it means much."
        )
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Picks settled", sc["n"])
    if sc.get("mean_clv") is not None:
        c2.metric("Mean CLV", f"{sc['mean_clv']:+.3f}",
                  help="(1/close) − (1/entry); positive = beat the closing line")
        c3.metric("% positive CLV", f"{sc['pct_positive_clv']:.0%}")
    c4.metric("Paper P&L (1u flat)", f"{sc['pnl_units']:+.1f}u", f"{sc['roi']:+.1%} ROI")

    if sc.get("calibration"):
        st.caption("Calibration — predicted vs actual hit rate")
        st.dataframe(sc["calibration"], use_container_width=True, hide_index=True)

    if sc["n"] < 30:
        st.caption(
            f"⚠️ Only {sc['n']} settled picks — too few to conclude; "
            f"CLV stabilizes around 30–50+."
        )


# ============================================================================
# Section 4b — Bayesian vs Poisson (shadow comparison, WC-09-07)
# ============================================================================

def _pct(x) -> str:
    return f"{x:.0%}" if x is not None else "—"


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_live_metrics() -> dict:
    from src.world_cup.bayesian_validation import live_model_metrics
    return live_model_metrics()


@st.cache_data(ttl=3600, show_spinner="Backtesting both models on the 2022 WC…")
def _cached_holdout() -> dict:
    from src.world_cup.bayesian_validation import run_holdout_comparison
    return run_holdout_comparison()


def _render_model_comparison() -> None:
    """Bayesian (shadow) vs Poisson (staked): a leak-free holdout backtest plus a
    live tracker over finished WC matches, so we can see whether the shadow model
    earns promotion. No auto-promotion — the Poisson stays the only staked model."""
    _section_header("Bayesian vs Poisson — shadow comparison")
    st.caption(
        "The Bayesian model runs in shadow (never staked). This is whether it actually "
        "predicts better than the staked Poisson. **Promotion is manual** — these numbers "
        "inform a decision; they never change which model places bets."
    )

    live = _cached_live_metrics()
    st.markdown(f"**Live — finished 2026 WC matches** ({live['n_matches']} so far)")
    if live["n_matches"] == 0:
        st.info("No finished WC matches with both models' predictions yet.")
    else:
        p, b = live["poisson"], live["bayesian"]
        st.dataframe([
            {"Model": "Poisson (staked)", "Brier": p["brier"], "Log-loss": p["log_loss"],
             "Accuracy": _pct(p["accuracy"]), "n": p["n"]},
            {"Model": "Bayesian (shadow)", "Brier": b["brier"], "Log-loss": b["log_loss"],
             "Accuracy": _pct(b["accuracy"]), "n": b["n"]},
        ], use_container_width=True, hide_index=True)
        st.caption(
            "Lower Brier / log-loss = better-calibrated probabilities. "
            + (f"⚠️ Only {live['n_matches']} matches, and live predictions refresh each run "
               "— directional, not proof. The holdout below is the clean test."
               if live["n_matches"] < 30 else "")
        )

    with st.expander("Holdout backtest — 2022 World Cup (leak-free)", expanded=False):
        h = _cached_holdout()
        p, b = h.get("poisson"), h.get("bayesian")
        if not p or not b:
            st.info("Backtest unavailable (a model failed to fit).")
        else:
            st.dataframe([
                {"Model": "Poisson", "Brier": round(p["brier"], 4),
                 "Accuracy": _pct(p.get("accuracy")), "matches scored": p.get("n_evaluated")},
                {"Model": "Bayesian", "Brier": b["brier"],
                 "Accuracy": _pct(b.get("accuracy")), "matches scored": b.get("n_evaluated")},
            ], use_container_width=True, hide_index=True)
            winner = h.get("brier_winner")
            if winner:
                better = "Bayesian" if winner == "bayesian" else "Poisson"
                st.caption(
                    f"Lower Brier wins: **{better}** (Δ {h.get('brier_delta'):+.4f}). "
                    "The two models score different match counts — the Poisson skips matches "
                    "it can't build features for, the Bayesian needs only team names — so read "
                    "this as directional, not a perfectly controlled head-to-head."
                )

    with st.expander("Promotion criteria (manual — never automatic)", expanded=False):
        from src.world_cup.bayesian_validation import PROMOTION_CRITERIA
        st.text(PROMOTION_CRITERIA)


# ============================================================================
# Section 5 — Model Performance
# ============================================================================

def _render_model_performance() -> None:
    _section_header("Model Performance")

    with get_session() as session:
        rows = session.execute(
            select(WCPrediction, WCMatch)
            .join(WCMatch)
            .where(
                WCPrediction.model_name == MODEL_NAME,
                WCMatch.status == "finished",
                WCMatch.home_goals.isnot(None),
            )
        ).all()

    correct = 0
    total = 0
    brier_sum = 0.0
    cal_bins: dict[int, list[tuple[float, int]]] = {i: [] for i in range(10)}

    for p, match in rows:
        total += 1
        probs = [p.home_win_prob, p.draw_prob, p.away_win_prob]

        if match.home_goals > match.away_goals:
            actual = [1, 0, 0]
        elif match.home_goals == match.away_goals:
            actual = [0, 1, 0]
        else:
            actual = [0, 0, 1]

        brier_sum += sum((probs[i] - actual[i]) ** 2 for i in range(3))
        pred_idx = probs.index(max(probs))
        if actual[pred_idx] == 1:
            correct += 1

        for i, prob in enumerate(probs):
            bin_idx = min(int(prob * 10), 9)
            cal_bins[bin_idx].append((prob, actual[i]))

    if total == 0:
        st.info("No finished matches with predictions yet.")
        return

    brier = brier_sum / total
    accuracy = correct / total

    c1, c2, c3 = st.columns(3)
    c1.metric("Brier Score", f"{brier:.4f}")
    c2.metric("Accuracy", f"{accuracy:.0%}")
    c3.metric("Matches", total)

    # Calibration chart — predicted probability vs actual frequency
    cal_x, cal_y = [], []
    for b in range(10):
        entries = cal_bins[b]
        if not entries:
            continue
        avg_pred = sum(e[0] for e in entries) / len(entries)
        avg_actual = sum(e[1] for e in entries) / len(entries)
        cal_x.append(avg_pred)
        cal_y.append(avg_actual)

    if cal_x:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[0, 1], y=[0, 1], mode="lines",
            line=dict(color=TEXT_DIM, dash="dash", width=1),
            name="Perfect",
        ))
        fig.add_trace(go.Scatter(
            x=cal_x, y=cal_y, mode="markers+lines",
            marker=dict(color=GREEN, size=8),
            line=dict(color=GREEN),
            name="Model",
        ))
        fig.update_layout(
            plot_bgcolor=SURFACE, paper_bgcolor=BG,
            font=dict(color=TEXT, family="JetBrains Mono, monospace"),
            xaxis=dict(title="Predicted Probability", range=[0, 1], gridcolor=BORDER),
            yaxis=dict(title="Actual Frequency", range=[0, 1], gridcolor=BORDER),
            height=300, margin=dict(l=0, r=0, t=10, b=40),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# Section 6 — Tournament Winner Probabilities
# ============================================================================

@st.cache_data(ttl=3600, show_spinner="Running tournament simulation...")
def _cached_simulation() -> dict:
    from src.world_cup.predictor import WCPoissonPredictor
    from src.world_cup.simulator import simulate_tournament

    predictor = WCPoissonPredictor(alpha=1.0)
    predictor.fit()
    return simulate_tournament(predictor, n_sims=1000, seed=42)


def _render_winner_chart() -> None:
    _section_header("Tournament Winner Probabilities")

    try:
        result = _cached_simulation()

        probs = result.get("team_probs", {})
        if not probs:
            st.info("No simulation data available.")
            return

        # Top 16 by winner probability
        sorted_teams = sorted(probs.items(), key=lambda x: -x[1].get("winner", 0))[:16]
        names = [t[0] for t in sorted_teams]
        win_probs = [t[1].get("winner", 0) for t in sorted_teams]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=win_probs,
            y=names,
            orientation="h",
            marker_color=GREEN,
            text=[f"{p:.1%}" for p in win_probs],
            textposition="outside",
            textfont=dict(color=TEXT, size=11),
        ))

        fig.update_layout(
            plot_bgcolor=SURFACE,
            paper_bgcolor=BG,
            font=dict(color=TEXT, family="JetBrains Mono, monospace"),
            xaxis=dict(
                title="P(Win Tournament)",
                tickformat=".0%",
                gridcolor=BORDER,
                zerolinecolor=BORDER,
            ),
            yaxis=dict(autorange="reversed"),
            margin=dict(l=0, r=40, t=10, b=40),
            height=500,
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.warning(f"Could not run tournament simulation: {e}")


# ============================================================================
# Section 7 — Knockout Bracket Visualization (WC-06-03)
# ============================================================================

@st.cache_data(ttl=3600)
def _team_fifa_map() -> dict:
    """Map team name → FIFA code, for flags in the bracket (which works in names)."""
    with get_session() as session:
        return {t.name: t.fifa_code for t in session.execute(select(WCTeam)).scalars().all()}


def _flag_for_name(name: str) -> str:
    """Inline flag for a team name, or '' for TBD/unknown (with a trailing space)."""
    fifa = _team_fifa_map().get(name)
    return f"{render_flag(fifa)} " if fifa else ""


def _render_knockout_bracket() -> None:
    _section_header("Knockout Bracket")

    with get_session() as session:
        ko_matches = session.execute(
            select(WCMatch)
            .where(WCMatch.stage != "group")
            .options(
                joinedload(WCMatch.home_team),
                joinedload(WCMatch.away_team),
                joinedload(WCMatch.value_bets),
                joinedload(WCMatch.odds),
            )
            .order_by(WCMatch.stage, WCMatch.match_number)
        ).unique().scalars().all()

    try:
        result = _cached_simulation()
        probs = result.get("team_probs", {})
    except Exception:
        probs = {}

    # If no knockout matches in DB yet, build projected bracket from standings
    if not ko_matches:
        try:
            standings = _compute_group_standings()
            projected = _build_projected_bracket(standings, probs)
            if projected:
                st.caption("Projected bracket based on current group standings. Updates as matches are played.")
                _render_projected_bracket_html(projected, probs)
            else:
                st.info("Knockout bracket will appear once group results determine the matchups.")
        except Exception as e:
            st.warning(f"Could not build projected bracket: {e}")
        return

    # Organize by stage
    stages = {"r32": [], "r16": [], "qf": [], "sf": [], "final": []}
    for m in ko_matches:
        if m.stage in stages:
            stages[m.stage].append(m)

    stage_labels = {"r32": "Round of 32", "r16": "Round of 16", "qf": "Quarter-Finals",
                    "sf": "Semi-Finals", "final": "Final"}

    for stage_key, label in stage_labels.items():
        matches = stages.get(stage_key, [])
        if not matches:
            continue

        st.markdown(f"**{label}**")
        for m in matches:
            h_name = escape(m.home_team.name) if m.home_team else "TBD"
            a_name = escape(m.away_team.name) if m.away_team else "TBD"

            h_elo = (m.home_team.elo_rating or 0) if m.home_team else 0
            a_elo = (m.away_team.elo_rating or 0) if m.away_team else 0

            h_adv = probs.get(h_name, {}).get(stage_key, 0)
            a_adv = probs.get(a_name, {}).get(stage_key, 0)

            has_vb = len(m.value_bets) > 0

            if m.status == "finished" and m.home_goals is not None:
                score = f"{m.home_goals} - {m.away_goals}"
                # Knockout draws go to ET/pens — DB stores final result
                winner = h_name if m.home_goals > m.away_goals else (
                    a_name if m.away_goals > m.home_goals else None)
                result_color = GREEN
            else:
                score = "vs"
                winner = None
                result_color = TEXT_DIM

            vb_flag = f' <span style="color:{YELLOW}">★</span>' if has_vb else ""

            # Best h2h odds for unfinished matches
            odds_line = ""
            if m.status != "finished" and m.odds:
                best_by_sel: dict[str, float] = {}
                for o in m.odds:
                    if o.market_type == "h2h":
                        if o.selection not in best_by_sel or o.odds_decimal > best_by_sel[o.selection]:
                            best_by_sel[o.selection] = o.odds_decimal
                if best_by_sel:
                    parts = [f"{sel}: {dec:.2f}" for sel, dec in sorted(best_by_sel.items())]
                    odds_line = (
                        f'<div style="font-size:0.75rem;color:{TEXT_DIM};text-align:center;">'
                        f'Odds: {" · ".join(parts)}</div>'
                    )

            h_flag = _flag_for_name(m.home_team.name) if m.home_team else ""
            a_flag = _flag_for_name(m.away_team.name) if m.away_team else ""
            h_info = f"{h_flag}{h_name} ({h_elo:.0f}, {h_adv:.0%})"
            a_info = f"{a_flag}{a_name} ({a_elo:.0f}, {a_adv:.0%})"

            st.markdown(
                f'<div style="border:1px solid {BORDER};border-radius:4px;margin-bottom:4px;'
                f'padding:4px 8px;font-size:0.85rem;">'
                f'<div style="display:flex;justify-content:space-between;">'
                f'<span style="color:{GREEN if winner == h_name else TEXT}">{h_info}</span>'
                f'<span style="color:{result_color}">{score}</span>'
                f'<span style="color:{GREEN if winner == a_name else TEXT}">{a_info}</span>'
                f'{vb_flag}</div>{odds_line}</div>',
                unsafe_allow_html=True,
            )


def _build_projected_bracket(
    standings: dict[str, list[dict]],
    probs: dict,
) -> list[dict]:
    """Build projected R32 matchups from current group standings."""
    winners = {}
    runners = {}
    for g, teams in standings.items():
        if len(teams) >= 2:
            winners[g] = teams[0]["name"]
            runners[g] = teams[1]["name"]

    # Third-place teams sorted by pts/GD/GF then top-8 (matches simulator logic)
    thirds_raw = []
    for g, teams in standings.items():
        if len(teams) >= 3:
            thirds_raw.append(teams[2])
    thirds_raw.sort(key=lambda x: (-x["pts"], -x["gd"], -x["gf"]))
    thirds = [t["name"] for t in thirds_raw[:8]]

    # Cross-group pairings (same as simulator _build_r32)
    wr_pairs = [
        ("C", "D"), ("D", "C"), ("G", "H"), ("H", "G"),
        ("I", "K"), ("K", "I"), ("J", "L"), ("L", "J"),
    ]
    matchups = []
    for w_group, r_group in wr_pairs:
        w = winners.get(w_group, "TBD")
        r = runners.get(r_group, "TBD")
        matchups.append({"home": w, "away": r, "type": "W vs R"})

    wt_groups = ["A", "B", "E", "F"]
    for i, gl in enumerate(wt_groups):
        w = winners.get(gl, "TBD")
        t = thirds[i] if i < len(thirds) else "TBD"
        matchups.append({"home": w, "away": t, "type": "W vs 3rd"})

    rt_groups = ["A", "B", "E", "F"]
    for i, gl in enumerate(rt_groups):
        r = runners.get(gl, "TBD")
        idx = i + 4
        t = thirds[idx] if idx < len(thirds) else "TBD"
        matchups.append({"home": r, "away": t, "type": "R vs 3rd"})

    return matchups


def _render_projected_bracket_html(matchups: list[dict], probs: dict) -> None:
    """Render projected bracket as styled HTML matchup cards."""
    for i, m in enumerate(matchups):
        h_adv = probs.get(m["home"], {}).get("r32", 0)
        a_adv = probs.get(m["away"], {}).get("r32", 0)

        h_color = GREEN if h_adv > a_adv else TEXT
        a_color = GREEN if a_adv > h_adv else TEXT

        st.markdown(
            f'<div style="display:flex;justify-content:space-between;padding:4px 8px;'
            f'border:1px solid {BORDER};border-radius:4px;margin-bottom:4px;font-size:0.85rem;">'
            f'<span style="color:{h_color}">{_flag_for_name(m["home"])}{escape(m["home"])} ({h_adv:.0%})</span>'
            f'<span style="color:{TEXT_DIM}">vs</span>'
            f'<span style="color:{a_color}">{_flag_for_name(m["away"])}{escape(m["away"])} ({a_adv:.0%})</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ============================================================================
# Section 8 — Results (completed matches + model scorecard)  [Results tab]
# ============================================================================
# What happened, most recent first, with the model's ✓/✗ on every game it had a
# pre-match call for. Pure helpers below (outcome / pick / row HTML) are escaped and
# Streamlit-free so they can be unit-tested; _render_results does the DB read + chrome.

_OUTCOME_WORD = {"H": "home win", "D": "draw", "A": "away win"}


def _result_outcome(home_goals, away_goals):
    """Final-score 1X2 outcome: 'H' home win, 'A' away win, 'D' draw (None if unscored)."""
    if home_goals is None or away_goals is None:
        return None
    if home_goals > away_goals:
        return "H"
    if away_goals > home_goals:
        return "A"
    return "D"


def _model_pick(pred):
    """The side the model rated most likely pre-match (argmax of its 1X2 probs), as
    'H'/'D'/'A'. None when there's no usable pre-match prediction — either no stored
    row, or one that was back-filled after kickoff and gated out upstream by
    _was_pred_prematch."""
    if pred is None:
        return None
    probs = {
        "H": pred.home_win_prob or 0.0,
        "D": pred.draw_prob or 0.0,
        "A": pred.away_win_prob or 0.0,
    }
    return max(probs, key=probs.get)


def _pick_conf(pred, pick):
    """The model's probability for the outcome it favoured (None when no call)."""
    if pred is None or pick is None:
        return None
    return {"H": pred.home_win_prob, "D": pred.draw_prob, "A": pred.away_win_prob}.get(pick)


def _parse_ts(ts):
    """Tolerant parse of a stored timestamp to a naive datetime, or None. Handles
    'YYYY-MM-DD HH:MM[:SS]' with a space or 'T' separator, dropping any fractional or
    timezone suffix. created_at and kickoff are both stored UTC, so a naive compare
    is correct."""
    if not ts:
        return None
    s = str(ts).strip().replace("T", " ").split("+")[0].split(".")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _was_pred_prematch(pred, match) -> bool:
    """True only if the prediction was created BEFORE the match kicked off — i.e. a
    genuine pre-match call. This is the temporal-integrity guard (Rule 6) for the
    Results scorecard: a back-filled prediction (created after the match) must never
    count as a model call. When the kickoff time is unknown we fall back to
    end-of-day, so a prediction made ON the match date still counts but one made on a
    LATER date does not."""
    if pred is None or not getattr(pred, "created_at", None):
        return False
    made = _parse_ts(pred.created_at)
    ko = _parse_ts(f"{match.date} {match.kickoff_time or '23:59'}")
    return made is not None and ko is not None and made < ko


def _short_date(iso):
    """'2026-06-19' → '19 Jun' for a compact row label; passthrough on bad input."""
    try:
        return datetime.strptime((iso or "")[:10], "%Y-%m-%d").strftime("%d %b")
    except (ValueError, TypeError):
        return iso or ""


def _result_row_html(date_label, home_name, away_name, home_flag, away_flag,
                     home_goals, away_goals, model_pick, model_conf):
    """One completed-match row: date · teams + score (winner emboldened) · the model's
    ✓/✗, the outcome it favoured, and its confidence in that call. We show the
    favoured-OUTCOME probability (not the modal scoreline, which for Poisson is often a
    draw even when a win is likeliest — that pairing reads as contradictory). All
    dynamic text escaped; flags are trusted markup."""
    actual = _result_outcome(home_goals, away_goals)
    home_weight = "700" if actual == "H" else "400"
    away_weight = "700" if actual == "A" else "400"
    if actual is None:
        score = "—"
    else:
        score = f'{int(home_goals)}<span style="color:{TEXT_DIM};">–</span>{int(away_goals)}'

    if model_pick is None:
        chip = f'<span style="color:{TEXT_DIM};font-size:0.72rem;">no model call</span>'
    else:
        correct = model_pick == actual
        colour = GREEN if correct else RED
        glyph = "✓" if correct else "✗"
        called = _OUTCOME_WORD.get(model_pick, "?")
        conf = f' · {model_conf:.0%}' if model_conf is not None else ""
        chip = (
            f'<span style="color:{colour};font-weight:700;">Model {glyph}</span> '
            f'<span style="color:{TEXT_DIM};font-size:0.72rem;">called {escape(called)}{conf}</span>'
        )

    return (
        f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;'
        f'padding:6px 10px;margin-bottom:2px;background:transparent;'
        f'border-left:3px solid {BORDER};border-radius:4px;font-size:0.85rem;">'
        f'<span style="color:{TEXT_DIM};min-width:64px;font-size:0.72rem;">{escape(date_label)}</span>'
        f'<span style="flex:1;min-width:200px;">{home_flag} '
        f'<span style="font-weight:{home_weight};">{escape(home_name)}</span> '
        f'<span style="color:{TEXT};font-weight:700;margin:0 4px;">{score}</span> '
        f'<span style="font-weight:{away_weight};">{escape(away_name)}</span> {away_flag}</span>'
        f'<span style="flex:1;min-width:170px;text-align:right;">{chip}</span>'
        f'</div>'
    )


def _render_results() -> None:
    """Completed matches, most recent first, with a ✓/✗ on every game the model
    called and a mini hit-rate scorecard. A group filter narrows the list; a picker
    opens any match's full deep dive. Read-only (no model/value/pipeline writes)."""
    _section_header("Results")

    with get_session() as session:
        matches = session.execute(
            select(WCMatch)
            .options(
                joinedload(WCMatch.home_team),
                joinedload(WCMatch.away_team),
                joinedload(WCMatch.predictions),
            )
            .where(WCMatch.status == "finished")
            .order_by(WCMatch.date.desc(), WCMatch.kickoff_time.desc())
        ).unique().scalars().all()

        if not matches:
            st.info("No completed World Cup matches yet — results appear here as games finish.")
            return

        # One pass: collect render data + the model hit-rate over CALLED games.
        rows, groups_present = [], set()
        called = correct = 0
        for m in matches:
            if m.group_letter:
                groups_present.add(m.group_letter)
            pred = next((p for p in m.predictions if p.model_name == MODEL_NAME), None)
            # Temporal-integrity guard: a prediction created AFTER kickoff is
            # back-filled, not a real call — drop it so the row shows "no model
            # call" and it's excluded from the hit-rate.
            if not _was_pred_prematch(pred, m):
                pred = None
            pick = _model_pick(pred)
            actual = _result_outcome(m.home_goals, m.away_goals)
            if pick is not None and actual is not None:
                called += 1
                correct += int(pick == actual)
            rows.append((m, pred, pick))

        opts = ["All groups"] + [f"Group {g}" for g in sorted(groups_present)]
        choice = st.selectbox("Filter by group", opts, key="wc_results_group",
                              label_visibility="collapsed")
        sel_group = None if choice == "All groups" else choice.split()[-1]

        hit = f"{correct}/{called} ({correct / called:.0%})" if called else "—"
        st.caption(
            f"{len(matches)} matches played · model called {hit} correct where it had a "
            "genuine pre-match read (predictions made after a match are excluded) · "
            "dates ET · newest first"
        )

        label_to_id = {}
        shown = 0
        for m, pred, pick in rows:
            if sel_group and m.group_letter != sel_group:
                continue
            shown += 1
            home, away = m.home_team, m.away_team
            home_name = home.name if home else "?"
            away_name = away.name if away else "?"
            home_flag = render_flag(home.fifa_code) if home else ""
            away_flag = render_flag(away.fifa_code) if away else ""
            st.markdown(
                _result_row_html(
                    _short_date(m.date), home_name, away_name, home_flag, away_flag,
                    m.home_goals, m.away_goals, pick, _pick_conf(pred, pick)),
                unsafe_allow_html=True,
            )
            label_to_id[f"{home_name} {m.home_goals}–{m.away_goals} {away_name} · "
                        f"{_short_date(m.date)}"] = m.id

        if sel_group and shown == 0:
            st.info("No completed matches in this group yet.")
            return

        # Drill-down without a button per row: pick a match, open its deep dive.
        st.markdown(
            f'<div style="color:{TEXT_DIM};font-size:0.78rem;margin-top:0.5rem;">'
            'Open a match for the full breakdown (heatmap, model vs books, line movement, '
            'lineups):</div>', unsafe_allow_html=True)
        sel = st.selectbox("Match", ["—"] + list(label_to_id), key="wc_results_dd_sel",
                           label_visibility="collapsed")
        if st.button("🔍 Open full deep dive", key="wc_results_dd_btn",
                     disabled=(sel == "—"), use_container_width=True):
            st.session_state["wc_deep_dive_match_id"] = label_to_id[sel]
            st.switch_page("views/wc_deep_dive.py")


# ============================================================================
# Section 9 — My Bets (personal WC bet tracker)  [My Bets tab — WC-BET-02]
# ============================================================================
# A user's OWN World Cup bets: log a selection, watch it auto-settle off the final
# score, track running P&L. Self-contained in this tab and scoped to the logged-in
# user. Reads/writes only wc_bet_log (the user's data) via world_cup.bets — it never
# touches the model / value / prediction path.

_SEL_LABELS = {"home": "Home", "draw": "Draw", "away": "Away",
               "over": "Over", "under": "Under", "yes": "Yes", "no": "No"}


def _wc_betting_fixtures() -> list:
    """WC matches a user can log a bet on: upcoming (scheduled) plus recently
    finished (so a past bet can be backfilled), earliest first. Each: id, date,
    status, label. Read-only; returns [] on error."""
    out = []
    try:
        recent = (datetime.utcnow().date() - timedelta(days=5)).isoformat()
        with get_session() as session:
            matches = session.execute(
                select(WCMatch)
                .options(joinedload(WCMatch.home_team), joinedload(WCMatch.away_team))
                .where(WCMatch.status.in_(["scheduled", "finished"]))
                .order_by(WCMatch.date, WCMatch.kickoff_time)
            ).unique().scalars().all()
        for m in matches:
            if m.status == "finished" and (m.date or "") < recent:
                continue
            home = m.home_team.name if m.home_team else "?"
            away = m.away_team.name if m.away_team else "?"
            tag = "" if m.status == "scheduled" else " (FT)"
            out.append({"id": m.id, "date": m.date, "status": m.status,
                        "home": home, "away": away,
                        "label": f"{m.date} · {home} v {away}{tag}"})
    except Exception:
        return []
    return out


def _bet_summary_html(s: dict) -> str:
    """Running-P&L scoreboard strip. Net P&L / ROI coloured green(+) / red(−)."""
    net = s["net_pnl"]
    col = GREEN if net > 0 else (RED if net < 0 else TEXT_DIM)
    roi = f"{s['roi'] * 100:+.1f}%" if s["roi"] is not None else "—"
    wr = f"{s['win_rate'] * 100:.0f}%" if s["win_rate"] is not None else "—"
    record = f"{s['won']}–{s['lost']}" + (f" ({s['void']}v)" if s["void"] else "")
    sign = "+" if net >= 0 else "−"
    cells = [
        ("Net P&L", f"{sign}${abs(net):,.2f}", col),
        ("ROI", roi, col),
        ("Record W–L", record, TEXT),
        ("Win rate", wr, TEXT),
        ("Staked", f"${s['staked_total']:,.2f}", TEXT),
        ("Pending", str(s["pending"]), TEXT_DIM),
    ]
    inner = "".join(
        f'<div style="flex:1;min-width:84px;text-align:center;padding:8px 6px;">'
        f'<div style="color:{c};font-family:JetBrains Mono,monospace;font-weight:700;'
        f'font-size:1.02rem;">{escape(v)}</div>'
        f'<div style="color:{TEXT_DIM};font-size:0.68rem;text-transform:uppercase;'
        f'letter-spacing:0.5px;margin-top:2px;">{escape(label)}</div></div>'
        for label, v, c in cells
    )
    return (f'<div style="display:flex;flex-wrap:wrap;gap:4px;border:1px solid {BORDER};'
            f'border-radius:8px;background:{SURFACE};margin-bottom:10px;">{inner}</div>')


def _bet_row_html(b: dict) -> str:
    """One logged bet row: date · teams · pick · price/stake · status · P&L. 🎯 marks
    a bet logged from a model tip. All dynamic text escaped."""
    status = b["status"]
    if status == "won":
        badge = f'<span style="color:{GREEN};font-weight:700;">✓ won</span>'
        pnl = f'<span style="color:{GREEN};font-weight:700;">+${b["pnl"]:,.2f}</span>'
    elif status == "lost":
        badge = f'<span style="color:{RED};font-weight:700;">✗ lost</span>'
        pnl = f'<span style="color:{RED};font-weight:700;">−${abs(b["pnl"]):,.2f}</span>'
    elif status == "void":
        badge = f'<span style="color:{TEXT_DIM};">void</span>'
        pnl = f'<span style="color:{TEXT_DIM};">$0.00</span>'
    else:
        badge = f'<span style="color:{YELLOW};">pending</span>'
        pnl = f'<span style="color:{TEXT_DIM};">—</span>'
    advised = "" if (b.get("source") or "manual") == "manual" else \
        f' <span title="logged from a model tip" style="color:{ACCENT};">🎯</span>'
    teams = escape(f'{b["home"]} v {b["away"]}')
    pick = escape(f'{b["market_label"]} · {_SEL_LABELS.get(b["selection"], b["selection"])}')
    book = f' · {escape(b["bookmaker"])}' if b.get("bookmaker") else ""
    return (
        f'<div style="display:flex;align-items:center;gap:10px;padding:7px 10px;'
        f'border-bottom:1px solid {BORDER};font-size:0.84rem;">'
        f'<span style="color:{TEXT_DIM};min-width:60px;font-size:0.74rem;">'
        f'{escape(_short_date(b["date"]))}</span>'
        f'<span style="flex:2;color:{TEXT};">{teams}</span>'
        f'<span style="flex:2;color:{TEXT_DIM};">{pick}{advised}</span>'
        f'<span style="flex:1;color:{TEXT_DIM};font-family:JetBrains Mono,monospace;'
        f'font-size:0.76rem;">@{b["odds"]:.2f} · ${b["stake"]:,.0f}{book}</span>'
        f'<span style="min-width:64px;text-align:right;">{badge}</span>'
        f'<span style="min-width:78px;text-align:right;'
        f'font-family:JetBrains Mono,monospace;">{pnl}</span></div>'
    )


# --- Accumulator (parlay) slip builder — WC-ACC-03 ---------------------------

def _slip_leg_row_html(lg: dict) -> str:
    """One leg on the accumulator slip: teams · market/selection · odds. 🎯 marks a
    leg staged from a model pick. All dynamic text escaped."""
    mk = escape(lg.get("market_label", lg["market_type"]))
    sel = escape(_SEL_LABELS.get(lg["selection"], lg["selection"]))
    teams = escape(f'{lg.get("home", "?")} v {lg.get("away", "?")}')
    tip = (f' <span style="color:{ACCENT};" title="from a model pick">🎯</span>'
           if (lg.get("source") or "manual") != "manual" else "")
    return (
        f'<div style="display:flex;gap:10px;align-items:center;padding:5px 8px;'
        f'border-bottom:1px solid {BORDER};font-size:0.82rem;">'
        f'<span style="flex:2;color:{TEXT};">{teams}{tip}</span>'
        f'<span style="flex:2;color:{TEXT_DIM};">{mk} · {sel}</span>'
        f'<span style="color:{TEXT};font-family:JetBrains Mono,monospace;">'
        f'@{lg["odds"]:.2f}</span></div>'
    )


def _slip_readout_html(readout: dict, stake: float, payout: float) -> str:
    """Combined-slip readout strip: legs · combined odds · potential payout · and,
    when EVERY leg has a model estimate, the INFORMATIVE combined model prob + edge.
    Edge coloured green(+)/red(−). All escaped."""
    cells = [
        ("Legs", str(readout["n_legs"]), TEXT),
        ("Combined odds", f'{readout["combined_odds"]:.2f}', TEXT),
        ("Stake", f"${stake:,.2f}", TEXT_DIM),
        ("Potential payout", f"${payout:,.2f}", GREEN),
    ]
    if readout["model_prob"] is not None:
        edge = readout["edge"] or 0.0
        ecol = GREEN if edge > 0 else (RED if edge < 0 else TEXT_DIM)
        cells.append(("Model prob", f'{readout["model_prob"] * 100:.1f}%', TEXT))
        cells.append(("Combined edge", f'{edge * 100:+.1f}%', ecol))
    inner = "".join(
        f'<div style="flex:1;min-width:80px;text-align:center;padding:8px 6px;">'
        f'<div style="color:{c};font-family:JetBrains Mono,monospace;font-weight:700;'
        f'font-size:1.0rem;">{escape(v)}</div>'
        f'<div style="color:{TEXT_DIM};font-size:0.66rem;text-transform:uppercase;'
        f'letter-spacing:0.5px;margin-top:2px;">{escape(label)}</div></div>'
        for label, v, c in cells
    )
    return (f'<div style="display:flex;flex-wrap:wrap;gap:4px;border:1px solid {BORDER};'
            f'border-radius:8px;background:{SURFACE};margin:8px 0;">{inner}</div>')


def _render_bet_slip(uid: int) -> None:
    """WC-ACC-03: build an accumulator (parlay). Add legs (manually or staged from a
    model pick in the Today & Bets tab), see combined odds / payout / an INFORMATIVE
    combined edge, get a same-match correlation warning, and log it as a tracked
    accumulator. Calculator + tracker only — it prices the slip you built, never
    suggests a combination."""
    from src.world_cup.bets import (
        MARKET_LABELS, WC_MARKETS, accumulator_slip_readout, log_wc_accumulator,
    )
    slip = st.session_state.setdefault("wc_acca_slip", [])
    title = "🎫 Build an accumulator (parlay)" + (f" · {len(slip)} legs" if slip else "")
    with st.expander(title, expanded=bool(slip)):
        st.caption("Combine 2+ selections into one bet — every leg must win and the "
                   "odds multiply. This prices the slip you build; it never suggests "
                   "combinations.")

        # --- add a leg manually ---
        fixtures = _wc_betting_fixtures()
        if fixtures:
            labels = [f["label"] for f in fixtures]
            fmeta = {f["label"]: f for f in fixtures}
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            with c1:
                fx = st.selectbox("Match", labels, key="wcacca_match")
            with c2:
                market = st.selectbox("Market", list(WC_MARKETS.keys()),
                                      key="wcacca_market",
                                      format_func=lambda m: MARKET_LABELS.get(m, m))
            with c3:
                selection = st.selectbox("Selection", list(WC_MARKETS[market]),
                                         key="wcacca_sel",
                                         format_func=lambda x: _SEL_LABELS.get(x, x))
            with c4:
                odds = st.number_input("Odds", min_value=1.01, value=2.00, step=0.05,
                                       key="wcacca_odds")
            if st.button("➕ Add leg", key="wcacca_addleg"):
                fm = fmeta[fx]
                slip.append({
                    "match_id": fm["id"], "home": fm.get("home"),
                    "away": fm.get("away"), "market_type": market,
                    "market_label": MARKET_LABELS.get(market, market),
                    "selection": selection, "odds": float(odds),
                    "model_prob": None, "edge": None, "source": "manual",
                })
                st.session_state["wc_acca_slip"] = slip
                st.rerun()

        if not slip:
            st.caption("No legs yet. Add one above, or tap **➕ Add to slip** on a "
                       "model value pick in the 📋 Today & Bets tab.")
            return

        # --- current legs (each removable) ---
        st.markdown(
            f'<div style="border:1px solid {BORDER};border-radius:8px;'
            f'overflow:hidden;margin-bottom:4px;">'
            + "".join(_slip_leg_row_html(lg) for lg in slip) + "</div>",
            unsafe_allow_html=True,
        )
        rm_cols = st.columns(min(len(slip), 6) or 1)
        for i, lg in enumerate(slip):
            with rm_cols[i % len(rm_cols)]:
                if st.button(f"✕ leg {i + 1}", key=f"wcacca_rm_{i}"):
                    slip.pop(i)
                    st.session_state["wc_acca_slip"] = slip
                    st.rerun()

        readout = accumulator_slip_readout(slip)

        # Same-match correlation warning (multiplying correlated odds is invalid).
        for cor in readout["correlated"]:
            # st.warning renders Markdown (not raw HTML), and WC team names are
            # curated — pass the label through as the rest of the file does.
            st.warning(
                f"⚠️ {cor['count']} legs are on the same match ({cor['label']}). "
                "Same-match outcomes are correlated, so the combined odds and edge "
                "below assume independence and aren't accurate — books usually price "
                "these separately as a 'same-game multi'."
            )

        c1, c2 = st.columns([1, 2])
        with c1:
            stake = st.number_input("Stake ($)", min_value=0.0, value=10.0, step=5.0,
                                    key="wcacca_stake")
        payout = float(stake) * readout["combined_odds"]
        with c2:
            st.markdown(_slip_readout_html(readout, float(stake), payout),
                        unsafe_allow_html=True)

        if readout["model_prob"] is not None:
            st.caption("Combined model prob / edge are INFORMATIVE — the model's joint "
                       "estimate assuming the legs are independent (uncertainty and "
                       "margin compound across legs). Not a recommendation.")
        else:
            st.caption("Add all legs from model picks to see an informative combined "
                       "edge (manual legs have no model estimate).")

        can_log = len(slip) >= 2 and stake > 0
        lc, cc = st.columns([2, 1])
        with lc:
            if st.button("🎫 Log accumulator", type="primary", disabled=not can_log,
                         key="wcacca_log"):
                src = ("research_card"
                       if any((lg.get("source") or "manual") != "manual" for lg in slip)
                       else "manual")
                aid = log_wc_accumulator(uid, slip, float(stake), source=src)
                if aid:
                    st.session_state["wc_acca_slip"] = []
                    st.toast("🎫 Accumulator logged", icon="🎫")
                    st.rerun()
                else:
                    st.error("Couldn't log — need ≥ 2 valid legs (each at odds > 1) "
                             "and a stake > 0.")
        with cc:
            if st.button("Clear slip", key="wcacca_clear"):
                st.session_state["wc_acca_slip"] = []
                st.rerun()
        if len(slip) < 2:
            st.caption("Add at least 2 legs to log an accumulator.")


def _acca_leg_row_html(leg: dict) -> str:
    """One leg inside an expanded accumulator: teams · market/selection · odds · the
    leg's own settled status (won/lost/void/pending). All escaped."""
    st_ = leg.get("status", "pending")
    scol = {"won": GREEN, "lost": RED, "void": TEXT_DIM}.get(st_, YELLOW)
    mk = escape(leg.get("market_label", leg["market_type"]))
    sel = escape(_SEL_LABELS.get(leg["selection"], leg["selection"]))
    teams = escape(f'{leg.get("home", "?")} v {leg.get("away", "?")}')
    return (
        f'<div style="display:flex;gap:10px;align-items:center;padding:4px 8px;'
        f'border-bottom:1px solid {BORDER};font-size:0.8rem;">'
        f'<span style="flex:2;color:{TEXT};">{teams}</span>'
        f'<span style="flex:2;color:{TEXT_DIM};">{mk} · {sel}</span>'
        f'<span style="color:{TEXT};font-family:JetBrains Mono,monospace;">'
        f'@{leg["odds"]:.2f}</span>'
        f'<span style="min-width:56px;text-align:right;color:{scol};">'
        f'{escape(st_)}</span></div>'
    )


def _acca_expander_label(a: dict) -> str:
    """Plain-text header for an accumulator's expander: status icon · N-leg · combined
    odds · stake · P&L (once settled) or potential payout (while pending)."""
    status = a["status"]
    icon = {"won": "✓", "lost": "✗", "void": "•"}.get(status, "⏳")
    if status in ("won", "lost"):
        tail = f'{a["pnl"]:+.2f}'
    elif status == "pending":
        tail = f'→ ${a["stake"] * a["combined_odds"]:,.0f} potential'
    else:
        tail = "$0.00"
    return (f'{icon} {a["n_legs"]}-leg acca · @{a["combined_odds"]:.2f} · '
            f'${a["stake"]:,.0f} · {status} · {tail}')


def _render_my_bets() -> None:
    """My Bets tab: scoreboard + log-a-bet form + the user's bet list. Scoped to the
    logged-in user; bets auto-settle off final scores (read-time + pipeline)."""
    from src.auth import get_session_user_id
    from src.world_cup.bets import (
        MARKET_LABELS, WC_MARKETS, combined_bet_summary, combined_pnl_timeline,
        load_wc_accumulators, load_wc_bets, log_wc_bet,
    )
    _section_header("My Bets")
    uid = get_session_user_id()
    singles = load_wc_bets(uid)
    accas = load_wc_accumulators(uid)
    summ = combined_bet_summary(singles, accas)   # scoreboard across both (WC-ACC-04)

    if summ["total"]:
        st.markdown(_bet_summary_html(summ), unsafe_allow_html=True)
        if summ["accas"]:
            st.caption(f"Across {summ['singles']} single"
                       f"{'s' if summ['singles'] != 1 else ''} + {summ['accas']} "
                       f"accumulator{'s' if summ['accas'] != 1 else ''}.")
        if summ["advised_settled"]:
            awr = (f"{summ['advised_win_rate'] * 100:.0f}%"
                   if summ["advised_win_rate"] is not None else "—")
            st.caption(f"🎯 Of your model-advised bets: {summ['advised_won']}/"
                       f"{summ['advised_settled']} won ({awr}).")

    # Cumulative P&L over time (settled singles + accumulators) — running curve.
    timeline = combined_pnl_timeline(singles, accas)
    if len(timeline) >= 2:
        ys = [t["cumulative"] for t in timeline]
        line_col = GREEN if ys[-1] >= 0 else RED
        fig = go.Figure(go.Scatter(
            x=list(range(1, len(ys) + 1)), y=ys, mode="lines+markers",
            line=dict(color=line_col, width=2), marker=dict(size=5, color=line_col),
            hovertext=[f'#{i + 1} · {t["date"]} · cum {t["cumulative"]:+.2f}'
                       for i, t in enumerate(timeline)],
            hoverinfo="text"))
        fig.add_hline(y=0, line=dict(color=BORDER, width=1, dash="dot"))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="JetBrains Mono, monospace", color=TEXT_DIM, size=11),
            xaxis=dict(title="settled bet #", showgrid=False, zeroline=False),
            yaxis=dict(title="cumulative P&L ($)", gridcolor=BORDER, zeroline=False),
            margin=dict(l=50, r=16, t=18, b=34), height=230, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # Log a bet — reactive widgets (not a form) so Selection follows Market.
    with st.expander("➕ Log a bet", expanded=not (singles or accas)):
        fixtures = _wc_betting_fixtures()
        if not fixtures:
            st.caption("No World Cup fixtures available to bet on right now.")
        else:
            labels = [f["label"] for f in fixtures]
            ids = {f["label"]: f["id"] for f in fixtures}
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                fx = st.selectbox("Match", labels, key="wcbet_match")
            with c2:
                market = st.selectbox(
                    "Market", list(WC_MARKETS.keys()), key="wcbet_market",
                    format_func=lambda m: MARKET_LABELS.get(m, m))
            with c3:
                selection = st.selectbox(
                    "Selection", list(WC_MARKETS[market]),
                    format_func=lambda x: _SEL_LABELS.get(x, x))
            c4, c5, c6 = st.columns([1, 1, 2])
            with c4:
                odds = st.number_input("Odds", min_value=1.01, value=2.00,
                                       step=0.05, key="wcbet_odds")
            with c5:
                stake = st.number_input("Stake ($)", min_value=0.0, value=10.0,
                                        step=5.0, key="wcbet_stake")
            with c6:
                book = st.text_input("Bookmaker (optional)", key="wcbet_book")
            if st.button("Log bet", type="primary", key="wcbet_log"):
                bid = log_wc_bet(uid, ids[fx], market, selection, float(odds),
                                 float(stake), bookmaker=(book or None),
                                 source="manual")
                if bid:
                    st.toast("✅ Bet logged", icon="✅")
                    st.rerun()
                else:
                    st.error("Couldn't log that bet — odds must be > 1 and stake > 0.")

    # WC-ACC-03: accumulator (parlay) slip builder — always available, even before
    # any single bets are logged.
    _render_bet_slip(uid)

    if not singles and not accas:
        st.info("No bets logged yet — log one above, build an accumulator, or tap ➕ "
                "on a model pick in the 📋 Today & Bets tab.")
        return

    # Accumulators — a parent header row per acca with expandable legs (WC-ACC-04).
    if accas:
        st.markdown('<div style="color:#8B949E;font-size:0.8rem;font-weight:600;'
                    'margin:8px 0 2px;">🎫 Accumulators</div>', unsafe_allow_html=True)
        for a in accas:
            with st.expander(_acca_expander_label(a)):
                st.markdown(
                    f'<div style="border:1px solid {BORDER};border-radius:6px;'
                    f'overflow:hidden;">'
                    + "".join(_acca_leg_row_html(lg) for lg in a["legs"]) + "</div>",
                    unsafe_allow_html=True)
                st.caption(f'Combined @{a["combined_odds"]:.2f} · stake '
                           f'${a["stake"]:,.2f} · every leg must win.')

    # Single bets.
    if singles:
        if accas:
            st.markdown('<div style="color:#8B949E;font-size:0.8rem;font-weight:600;'
                        'margin:10px 0 2px;">🎟️ Single bets</div>',
                        unsafe_allow_html=True)
        st.markdown(
            f'<div style="border:1px solid {BORDER};border-radius:8px;overflow:hidden;">'
            + "".join(_bet_row_html(b) for b in singles) + "</div>",
            unsafe_allow_html=True,
        )
    st.caption("Bets settle automatically off the 90-minute score (knockouts on "
               "regulation). 🎯 = logged from a model tip. Your own bets — separate "
               "from the model's picks.")


# ============================================================================
# Page Entry Point
# ============================================================================

def main() -> None:
    _render_header()

    # Tabs replace the former single 6,500px scroll. The actionable content
    # (fixtures + value bets) is the default landing tab; "Results" is the
    # completed-match history beside it; reference material is one click away,
    # not a long scroll down (WC-08-03; Results tab added 2026-06-25).
    tab_bets, tab_mybets, tab_results, tab_groups, tab_ko, tab_model = st.tabs(
        ["📋 Today & Bets", "🎟️ My Bets", "✅ Results", "📊 Groups",
         "🏆 Knockouts", "📈 Model"]
    )

    with tab_bets:
        _render_todays_matches()
        _render_value_bets()
        _render_research_card()

    with tab_mybets:
        _render_my_bets()

    with tab_results:
        _render_results()

    with tab_groups:
        # Collapsed by default so the tab opens compact — expand what you need.
        with st.expander("📊 Group Standings", expanded=False):
            _render_group_standings()
        with st.expander("🎯 Advancement Probabilities & What-If", expanded=False):
            _render_group_advancement()
        with st.expander("🥉 Third-Place Race", expanded=False):
            _render_third_place()

    with tab_ko:
        _render_knockout_bracket()

    with tab_model:
        _render_scorecard()
        _render_model_comparison()
        _render_winner_chart()
        _render_model_performance()


main()
