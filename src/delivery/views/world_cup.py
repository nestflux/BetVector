"""
BetVector — World Cup 2026 Dashboard Page (WC-06-01)
=====================================================
Tournament hub: today's matches with predictions, group standings,
value bets, model performance, and winner probability chart.
"""

from datetime import date, datetime, timedelta
from html import escape

import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import func as sa_func, select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.flags import render_flag
from src.world_cup.models import (
    WCMatch, WCPrediction, WCTeam, WCValueBet,
)
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.timeutil import EASTERN, eastern_date, format_kickoff_et
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

        last_date = session.execute(
            select(WCMatch.date).order_by(WCMatch.date.desc()).limit(1)
        ).scalar_one_or_none()

    days_remaining = "?"
    if last_date:
        try:
            end = datetime.strptime(last_date, "%Y-%m-%d").date()
            days_remaining = max(0, (end - date.today()).days)
        except ValueError:
            pass

    # Slim one-line header — replaces the former 3-metric block + progress bar
    # so the page leads with content, not chrome (WC-08-03).
    st.markdown(
        "#### 🏆 FIFA World Cup 2026 "
        f"<span style='color:{TEXT_DIM};font-weight:400;font-size:0.85rem'>"
        f"· {played}/{TOTAL_MATCHES} played · {days_remaining} days to final</span>",
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

    with get_session() as session:
        matches = session.execute(
            select(WCMatch)
            .options(
                joinedload(WCMatch.home_team),
                joinedload(WCMatch.away_team),
                joinedload(WCMatch.predictions),
                joinedload(WCMatch.odds),
            )
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


# ============================================================================
# Shared — Group standings computation (used by sections 3 and 3b)
# ============================================================================

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

def _render_value_bets() -> None:
    _section_header("Value Bets")
    st.caption(
        "⚠️ Tracked / shadow picks — the WC model is not yet calibrated against a "
        "sharp market on this little data. Monitor CLV before staking real money."
    )

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
            rows.append({
                "Match": f"{home.name if home else '?'} vs {away.name if away else '?'}",
                "Market": f"{vb.market_type}/{vb.selection}",
                "Edge": f"+{vb.edge:.1%}",
                "Odds": f"{vb.best_odds:.2f}",
                "Bookmaker": vb.bookmaker,
                "Kelly": f"{vb.kelly_stake:.2%}" if vb.kelly_stake else "—",
            })

    st.dataframe(rows, use_container_width=True, hide_index=True)


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

    from src.world_cup.research import build_research_card
    card = build_research_card(sel_id)
    if not card or not card["selections"]:
        st.info("No odds / prediction data for this match yet.")
        return

    rows = []
    for x in card["selections"]:
        rows.append({
            "Selection": x["label"],
            "Model": f"{x['model_prob']:.0%}" if x["model_prob"] is not None else "—",
            "Market": f"{x['market_prob']:.0%}" if x["market_prob"] is not None else "—",
            "Edge": f"{x['edge']:+.1%}" if x["edge"] is not None else "—",
            "Move": f"{x['movement']:+.1%}" if x["movement"] is not None else "—",
            "Best price": f"{x['best_odds']:.2f} ({x['best_book']})" if x["best_odds"] else "—",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(
        "Edge = model − de-vigged market. Move = consensus shift since opening "
        "(+ = market moved toward it). xG form: no reliable WC source — deferred."
    )

    _render_lineup_flag(sel_id)

    # Review queue — biggest model-market disagreements across upcoming matches
    st.markdown("**Biggest disagreements to review**")
    from src.world_cup.research import top_disagreements
    disagreements = top_disagreements(limit=10)
    if not disagreements:
        st.caption("No disagreements to review yet (needs odds + predictions).")
        return
    q_rows = [{
        "Match": d["match"],
        "Selection": d["selection"],
        "Model": f"{d['model']:.0%}",
        "Market": f"{d['market']:.0%}",
        "Edge": f"{d['edge']:+.1%}",
        "Best price": f"{d['best_odds']:.2f} ({d['best_book']})" if d["best_odds"] else "—",
    } for d in disagreements]
    st.dataframe(q_rows, use_container_width=True, hide_index=True)


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
# Page Entry Point
# ============================================================================

def main() -> None:
    _render_header()

    # Four tabs replace the former single 6,500px scroll. The actionable
    # content (fixtures + value bets) is the default landing tab; reference
    # material is one click away, not a long scroll down (WC-08-03).
    tab_bets, tab_groups, tab_ko, tab_model = st.tabs(
        ["📋 Today & Bets", "📊 Groups", "🏆 Knockouts", "📈 Model"]
    )

    with tab_bets:
        _render_todays_matches()
        _render_value_bets()
        _render_research_card()

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
