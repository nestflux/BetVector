"""
BetVector — World Cup 2026 Dashboard Page (WC-06-01)
=====================================================
Tournament hub: today's matches with predictions, group standings,
value bets, model performance, and winner probability chart.
"""

from datetime import date, datetime

import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import func as sa_func, select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.models import (
    WCMatch, WCOdds, WCPrediction, WCTeam, WCValueBet,
)
from src.world_cup.predictor import MODEL_NAME

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


def _today() -> str:
    return date.today().isoformat()


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

        first_date = session.execute(
            select(WCMatch.date).order_by(WCMatch.date).limit(1)
        ).scalar_one_or_none()

        last_date = session.execute(
            select(WCMatch.date).order_by(WCMatch.date.desc()).limit(1)
        ).scalar_one_or_none()

    pct = played / TOTAL_MATCHES if TOTAL_MATCHES else 0
    days_remaining = "?"
    if last_date:
        try:
            end = datetime.strptime(last_date, "%Y-%m-%d").date()
            days_remaining = max(0, (end - date.today()).days)
        except ValueError:
            pass

    st.markdown(
        f"### 🏆 FIFA World Cup 2026",
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Matches Played", f"{played} / {TOTAL_MATCHES}")
    c2.metric("Progress", f"{pct:.0%}")
    c3.metric("Days Remaining", days_remaining)

    st.progress(pct)


# ============================================================================
# Section 2 — Today's Matches
# ============================================================================

def _render_todays_matches() -> None:
    _section_header("Today's Matches")
    today = _today()

    with get_session() as session:
        matches = session.execute(
            select(WCMatch)
            .where(WCMatch.date == today)
            .options(
                joinedload(WCMatch.home_team),
                joinedload(WCMatch.away_team),
                joinedload(WCMatch.predictions),
                joinedload(WCMatch.odds),
            )
            .order_by(WCMatch.kickoff_time)
        ).unique().scalars().all()

        if not matches:
            st.info("No World Cup matches scheduled today.")
            return

        for m in matches:
            home_name = m.home_team.name if m.home_team else "?"
            away_name = m.away_team.name if m.away_team else "?"
            pred = next(
                (p for p in m.predictions if p.model_name == MODEL_NAME), None
            )

            with st.container():
                cols = st.columns([1, 3, 3, 2])
                cols[0].markdown(f"**{m.kickoff_time or 'TBD'}**")
                cols[1].markdown(f"**{home_name}**")
                cols[2].markdown(f"**{away_name}**")

                if m.status == "finished" and m.home_goals is not None:
                    cols[3].markdown(f"**{m.home_goals} - {m.away_goals}**")
                elif pred:
                    cols[3].markdown(
                        f":green[H {pred.home_win_prob:.0%}] · "
                        f"D {pred.draw_prob:.0%} · "
                        f":red[A {pred.away_win_prob:.0%}]"
                    )

                if pred and m.status != "finished":
                    h2h_odds = sorted(
                        [o for o in m.odds if o.market_type == "h2h"],
                        key=lambda o: -o.odds_decimal,
                    )[:3]
                    if h2h_odds:
                        odds_str = " · ".join(
                            f"{o.selection}: {o.odds_decimal:.2f}" for o in h2h_odds
                        )
                        st.caption(f"Best odds: {odds_str}")

                st.divider()


# ============================================================================
# Section 3 — Group Standings
# ============================================================================

def _render_group_standings() -> None:
    _section_header("Group Standings")

    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()
        finished = session.execute(
            select(WCMatch)
            .where(WCMatch.status == "finished", WCMatch.stage == "group")
        ).scalars().all()

    # Build standings
    standings: dict[str, dict[int, dict]] = {}
    for t in teams:
        if t.group_letter not in standings:
            standings[t.group_letter] = {}
        standings[t.group_letter][t.id] = {
            "name": t.name, "pts": 0, "gd": 0, "gf": 0, "mp": 0, "w": 0, "d": 0, "l": 0,
        }

    for m in finished:
        if m.home_goals is None or not m.group_letter:
            continue
        g = m.group_letter
        h = standings.get(g, {}).get(m.home_team_id)
        a = standings.get(g, {}).get(m.away_team_id)
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
            teams_sorted = sorted(
                standings[g].values(),
                key=lambda x: (-x["pts"], -x["gd"], -x["gf"]),
            )
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
                        name_cell = f'<span style="color:{color}">●</span> {t["name"]}'
                    else:
                        name_cell = t["name"]
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
# Section 4 — Value Bets
# ============================================================================

def _render_value_bets() -> None:
    _section_header("Value Bets")

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
# Page Entry Point
# ============================================================================

def main() -> None:
    _render_header()
    _render_todays_matches()
    _render_group_standings()
    _render_value_bets()
    _render_model_performance()
    _render_winner_chart()


main()
