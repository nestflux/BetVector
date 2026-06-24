"""
BetVector — World Cup 2026 Match Deep Dive (DF-08)
===================================================
Read-only, per-match analysis for a single World Cup fixture, mirroring the
league ``match_detail.py`` against the WC tables (WCMatch / WCPrediction /
WCOdds). Reached from the World Cup hub: the upcoming-fixtures strip and the
research card set ``st.session_state["wc_deep_dive_match_id"]`` and switch here;
the id is also synced to ``?wc_match_id=<id>`` so the URL stays shareable.

Sections:
1. Match header — flags, names, date, kickoff (ET), result if finished.
2. Scoreline matrix — the model's 7x7 Poisson grid, rebuilt from the stored
   expected goals (wc_predictions stores lambda, not the matrix).
3. Model vs every book — per market (1X2 / O/U 1.5·2.5·3.5 / BTTS), the model
   probability beside EVERY pulled book's own de-vigged line, with the model edge
   highlighted and the best price flagged (line shopping).
4. Line movement & CLV (DF-09) — for each backable selection, its best-available
   price across the snapshots we hold (open → entry → current → close) with the
   entry and close marked, plus the stored CLV (did we beat the close?).
5. Confirmed lineups (DF-09) — both XIs + formations + the rotation flag, reusing
   the same lineup_signal that powers the research card.

DF-10 adds qualification impact + the Bayesian shadow read. The World Cup model
is SHADOW / decision-support only — nothing here changes the model or any value
bet.
"""

from html import escape

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import aliased

from src.database.db import get_session
from src.world_cup.flags import render_flag
from src.world_cup.lineups import lineup_signal
from src.world_cup.models import WCMatch, WCTeam
from src.world_cup.predictor import scoreline_matrix_from_lambdas
from src.world_cup.research import build_book_comparison, build_movement
from src.world_cup.timeutil import format_kickoff_et

# Design system (CLAUDE.md Rule 5) — defined locally; the WC hub page runs main()
# at import, so we never import tokens from it.
BG = "#0D1117"
SURFACE = "#161B22"
TEXT = "#E6EDF3"
TEXT_DIM = "#8B949E"
GREEN = "#3FB950"
YELLOW = "#D29922"
RED = "#F85149"
BORDER = "#30363D"

# Inline pill marking model-generated numbers (mirrors match_detail.py).
_MODEL_BADGE = (
    f'<span style="background:{GREEN};color:{BG};font-family:JetBrains Mono,monospace;'
    f'font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;'
    f'margin-left:8px;vertical-align:middle;">MODEL</span>'
)

# Per-cell tint for a book's de-vigged line vs the model (DF-06/07 trust classes):
# value = model edge inside the trust band (a soft line worth shopping); capped =
# edge past the ceiling (likely model error, never celebrated); else neutral.
_CELL_BG = {
    "value": "rgba(63,185,80,0.16)",
    "capped": "rgba(210,153,34,0.16)",
}
_EDGE_COL = {"value": GREEN, "capped": YELLOW}


def _pct(x) -> str:
    """Percent or em-dash for a possibly-None probability."""
    return f"{x:.0%}" if x is not None else "—"


# ============================================================================
# Section 2 — Scoreline heatmap
# ============================================================================

def _scoreline_heatmap(matrix: list[list[float]], home: str, away: str) -> go.Figure:
    """7x7 Plotly heatmap of the model's scoreline grid (matrix[h][a] = P(home h,
    away a)). The most likely scoreline is outlined. Mirrors match_detail.py's
    league heatmap so the two deep dives read identically."""
    arr = np.array(matrix)
    max_h, max_a = np.unravel_index(arr.argmax(), arr.shape)

    text = [[f"{arr[h][a]:.1%}" for a in range(7)] for h in range(7)]
    text[max_h][max_a] = f"<b>{arr[max_h][max_a]:.1%}</b>"

    fig = go.Figure(data=go.Heatmap(
        z=arr,
        x=[str(i) for i in range(7)],
        y=[str(i) for i in range(7)],
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=11, family="JetBrains Mono, monospace"),
        colorscale=[
            [0, "#0D1117"], [0.25, "#161B22"], [0.5, "#1C4532"],
            [0.75, "#2D6A4F"], [1.0, "#3FB950"],
        ],
        showscale=False,
        hovertemplate=(f"{escape(home)} %{{y}} - %{{x}} {escape(away)}<br>"
                       "Probability: %{z:.1%}<extra></extra>"),
    ))
    fig.add_shape(
        type="rect",
        x0=max_a - 0.5, x1=max_a + 0.5,
        y0=max_h - 0.5, y1=max_h + 0.5,
        line=dict(color=GREEN, width=3),
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="JetBrains Mono, monospace", color=TEXT_DIM, size=12),
        xaxis=dict(title=f"{escape(away)} goals", side="top", dtick=1),
        yaxis=dict(title=f"{escape(home)} goals", autorange="reversed", dtick=1),
        margin=dict(l=60, r=20, t=60, b=20), height=400,
    )
    return fig


def _render_heatmap(comp: dict) -> None:
    st.markdown(
        f'<div class="bv-section-header">Scoreline probability matrix{_MODEL_BADGE}</div>',
        unsafe_allow_html=True,
    )
    matrix = scoreline_matrix_from_lambdas(comp["lambda_home"], comp["lambda_away"])
    if not matrix:
        st.info(
            "No model prediction for this match yet — the scoreline matrix appears "
            "once the WC pipeline has run for this fixture."
        )
        return

    arr = np.array(matrix)
    mh, ma = np.unravel_index(arr.argmax(), arr.shape)
    st.markdown(
        f'<p style="color:{TEXT_DIM};font-size:0.85rem;margin:0 0 6px;">'
        f'Most likely scoreline: '
        f'<span style="color:{GREEN};font-weight:700;font-family:JetBrains Mono,monospace;">'
        f'{mh}-{ma}</span> ({arr[mh][ma]:.1%}) · expected goals '
        f'<span style="font-family:JetBrains Mono,monospace;color:{TEXT};">'
        f'{comp["lambda_home"]:.2f}</span> – '
        f'<span style="font-family:JetBrains Mono,monospace;color:{TEXT};">'
        f'{comp["lambda_away"]:.2f}</span></p>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(
        _scoreline_heatmap(matrix, comp["home"], comp["away"]),
        use_container_width=True, config={"displayModeBar": False},
    )


# ============================================================================
# Section 3 — Model vs every pulled book
# ============================================================================

def _book_cell_html(sel: str, book: dict, best: dict) -> str:
    """One book's de-vigged probability for a selection: tinted by the model's
    trust class, with the raw price (★ when it's the best price across books) and
    the signed edge for an actionable cell."""
    prob = book["probs"].get(sel)
    raw = book["raw"].get(sel)
    trust = book["trust"].get(sel, "na")
    edge = book["edges"].get(sel)
    bg = _CELL_BG.get(trust, "transparent")

    is_best = bool(best.get(sel) and best[sel]["book"] == book["book"])
    star = f' <span style="color:{GREEN};">★</span>' if is_best else ""
    price = (f'<div style="font-size:0.66rem;color:{TEXT_DIM};'
             f'font-family:JetBrains Mono,monospace;">@{raw:.2f}{star}</div>'
             if raw else "")
    edge_html = ""
    if trust in _EDGE_COL and edge is not None:
        edge_html = (f'<div style="font-size:0.66rem;font-weight:700;'
                     f'color:{_EDGE_COL[trust]};font-family:JetBrains Mono,monospace;">'
                     f'{edge:+.0%}</div>')
    return (
        f'<td style="text-align:center;padding:5px 8px;background:{bg};'
        f'border-bottom:1px solid {BORDER};">'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:0.84rem;color:{TEXT};">'
        f'{_pct(prob)}</div>{price}{edge_html}</td>'
    )


def _market_table_html(market: dict) -> str:
    """Pure HTML for one market's model-vs-EVERY-book table: the model row + the
    de-vigged consensus row + one row per pulled book, edge-tinted so divergent
    books pop. The header sticks so the selection columns stay labelled while
    scrolling many books. Returned (not drawn) so it stays testable + renderable."""
    sels = market["selections"]
    labels = market["labels"]
    n = market["n_books"]

    head_cells = "".join(
        f'<th style="text-align:center;padding:6px 8px;color:{TEXT_DIM};'
        f'font-weight:600;font-size:0.78rem;">{escape(labels.get(s, s))}</th>'
        for s in sels
    )
    head = (
        f'<thead style="position:sticky;top:0;background:{SURFACE};">'
        f'<tr><th style="text-align:left;padding:6px 8px;color:{TEXT_DIM};'
        f'font-size:0.78rem;">Source</th>{head_cells}</tr></thead>'
    )

    # Model row (emphasised) + de-vigged consensus row.
    model_cells = "".join(
        f'<td style="text-align:center;padding:5px 8px;font-weight:700;color:{TEXT};'
        f'font-family:JetBrains Mono,monospace;font-size:0.86rem;'
        f'border-bottom:1px solid {BORDER};">{_pct(market["model"].get(s))}</td>'
        for s in sels
    )
    cons = market.get("consensus") or {}
    cons_cells = "".join(
        f'<td style="text-align:center;padding:5px 8px;color:{TEXT_DIM};'
        f'font-family:JetBrains Mono,monospace;font-size:0.82rem;'
        f'border-bottom:1px solid {BORDER};">{_pct(cons.get(s))}</td>'
        for s in sels
    )
    rows = [
        f'<tr style="background:rgba(88,166,255,0.06);"><td style="padding:5px 8px;'
        f'color:{TEXT};font-weight:700;border-bottom:1px solid {BORDER};">Model{_MODEL_BADGE}'
        f'</td>{model_cells}</tr>',
        f'<tr><td style="padding:5px 8px;color:{TEXT_DIM};border-bottom:1px solid {BORDER};">'
        f'Market consensus</td>{cons_cells}</tr>',
    ]
    for b in market["books"]:
        cells = "".join(_book_cell_html(s, b, market["best"]) for s in sels)
        rows.append(
            f'<tr><td style="padding:5px 8px;color:{TEXT};font-size:0.82rem;'
            f'border-bottom:1px solid {BORDER};">{escape(b["book"])}</td>{cells}</tr>'
        )

    return (
        f'<div style="margin:6px 0 2px;color:{TEXT};font-weight:700;font-size:0.95rem;">'
        f'{escape(market["title"])} '
        f'<span style="color:{TEXT_DIM};font-weight:400;font-size:0.8rem;">'
        f'· model vs {n} book{"s" if n != 1 else ""}</span></div>'
        f'<div style="max-height:340px;overflow:auto;border:1px solid {BORDER};'
        f'border-radius:8px;margin-bottom:10px;">'
        f'<table style="width:100%;border-collapse:collapse;">{head}<tbody>'
        f'{"".join(rows)}</tbody></table></div>'
    )


def _render_model_vs_books(comp: dict) -> None:
    st.markdown(
        '<div class="bv-section-header">Model vs every book</div>',
        unsafe_allow_html=True,
    )
    markets = comp.get("markets", [])
    if not markets:
        st.info(
            "No bookmaker odds for this match yet. The comparison fills once the "
            "odds pull captures this fixture (pre-kickoff window)."
        )
        return
    st.caption(
        "Each book's de-vigged line beside the model. Green = the model sees value "
        "vs that book (edge inside the trust band); amber = a gap past the ceiling, "
        "likely model error, not a bet. ★ marks the best price across books. "
        "Shadow / decision-support — nothing here is staked."
    )
    for market in markets:
        st.markdown(_market_table_html(market), unsafe_allow_html=True)


# ============================================================================
# Section 4 — Line movement & CLV (DF-09)
# ============================================================================
# WCOdds holds only the opening + latest price (no tick history), so a backable
# selection's movement is the few real snapshots we have, all on one consistent
# best-available basis: open → entry (logged) → current → close (frozen at
# kickoff). The chart marks entry + close; the table carries the CLV (entry vs
# close, +ve = we beat the close). All read-only / shadow — nothing is staked.

# Marker per snapshot: entry + close (the decision points) are large/solid; the
# context points (open, current) are smaller and hollow.
_MV_SYMBOL = {"Open": "circle-open", "Entry": "circle",
              "Current": "circle-open", "Close": "diamond"}
_MV_SIZE = {"Open": 9, "Entry": 14, "Current": 9, "Close": 14}
_MV_ORDER = ["Open", "Entry", "Current", "Close"]
# Distinct line colours per selection (design-system green/blue/amber/violet/…).
_MV_PALETTE = (GREEN, "#58A6FF", YELLOW, "#BC8CFF", "#F778BA", "#79C0FF")


def _movement_chart(selections: list[dict]) -> go.Figure:
    """One line per backable selection across the captured snapshots (Open →
    Entry → Current → Close), with the entry and close points emphasised. The
    shape is the CLV story: a line drifting up after entry means the price we beat
    got longer; the close marker is where it settled."""
    fig = go.Figure()
    for i, s in enumerate(selections):
        pts = s["points"]
        if len(pts) < 2:               # a single point isn't a movement line
            continue
        xs = [stage for stage, _ in pts]
        ys = [price for _, price in pts]
        colour = _MV_PALETTE[i % len(_MV_PALETTE)]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers", name=s["selection"],
            line=dict(color=colour, width=2),
            marker=dict(
                color=colour,
                symbol=[_MV_SYMBOL.get(x, "circle") for x in xs],
                size=[_MV_SIZE.get(x, 9) for x in xs],
                line=dict(color=colour, width=1.5),
            ),
            hovertemplate=("%{x}: %{y:.2f}<extra>"
                           + escape(s["selection"]) + "</extra>"),
        ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="JetBrains Mono, monospace", color=TEXT_DIM, size=12),
        xaxis=dict(categoryorder="array", categoryarray=_MV_ORDER,
                   showgrid=False, title=""),
        yaxis=dict(title="Decimal odds", gridcolor=BORDER, zeroline=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=11)),
        margin=dict(l=55, r=20, t=46, b=28), height=360,
    )
    return fig


def _price_td(value, mark: bool = False) -> str:
    """One price cell; em-dash when we don't hold that snapshot. ``mark`` bolds
    the decision points (entry + close)."""
    if not value:
        return (f'<td style="text-align:center;padding:5px 8px;color:{TEXT_DIM};'
                f'border-bottom:1px solid {BORDER};">—</td>')
    weight = "700" if mark else "400"
    return (f'<td style="text-align:center;padding:5px 8px;color:{TEXT};'
            f'font-weight:{weight};font-family:JetBrains Mono,monospace;'
            f'font-size:0.84rem;border-bottom:1px solid {BORDER};">{value:.2f}</td>')


def _clv_td(clv) -> str:
    """CLV cell: +ve green (beat the close), −ve red, 0 dim; 'awaiting close'
    until the closing line is captured near kickoff."""
    if clv is None:
        return (f'<td style="text-align:center;padding:5px 8px;color:{TEXT_DIM};'
                f'font-size:0.78rem;border-bottom:1px solid {BORDER};">awaiting close</td>')
    col = GREEN if clv > 0 else (RED if clv < 0 else TEXT_DIM)
    return (f'<td style="text-align:center;padding:5px 8px;color:{col};font-weight:700;'
            f'font-family:JetBrains Mono,monospace;font-size:0.84rem;'
            f'border-bottom:1px solid {BORDER};">{clv:+.1%}</td>')


def _movement_table_html(data: dict) -> str:
    """Pure HTML: one row per backable selection — its open / entry / current /
    close price (entry + close bolded as the decision points) and the stored CLV.
    Returned (not drawn) so it stays testable + renderable."""
    headers = ("Open", "Entry", "Current", "Close", "CLV")
    head = (
        f'<thead><tr><th style="text-align:left;padding:6px 8px;color:{TEXT_DIM};'
        f'font-size:0.78rem;">Backable selection</th>'
        + "".join(
            f'<th style="text-align:center;padding:6px 8px;color:{TEXT_DIM};'
            f'font-size:0.78rem;">{h}</th>' for h in headers)
        + '</tr></thead>'
    )
    rows = []
    for s in data["selections"]:
        label = escape(f'{s["selection"]} · {s["market"]}')
        rows.append(
            f'<tr><td style="padding:5px 8px;color:{TEXT};font-size:0.82rem;'
            f'border-bottom:1px solid {BORDER};">{label}</td>'
            f'{_price_td(s["open"])}{_price_td(s["entry"], mark=True)}'
            f'{_price_td(s["current"])}{_price_td(s["close"], mark=True)}'
            f'{_clv_td(s["clv"])}</tr>'
        )
    return (
        f'<div style="border:1px solid {BORDER};border-radius:8px;overflow:auto;'
        f'margin-bottom:8px;"><table style="width:100%;border-collapse:collapse;">'
        f'{head}<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _render_movement(match_id: int) -> None:
    st.markdown('<div class="bv-section-header">Line movement &amp; CLV</div>',
                unsafe_allow_html=True)
    data = build_movement(match_id)
    if not data or not data["selections"]:
        st.info(
            "No backable selections were flagged on this match, so there's no line "
            "to track. The World Cup model is shadow / decision-support — it logs a "
            "shadow bet only when it sees value, and only those appear here."
        )
        return
    st.caption(
        "Each backable selection's best available price at the snapshots we hold — "
        "the opening line, the entry we logged, the current best line, and the "
        "closing line frozen at kickoff (entry and close are the marked points). "
        "CLV is the headline: entry vs close, positive means we beat the close. WC "
        "odds keep only the opening and latest price, so these are real snapshots, "
        "not a tick-by-tick history. Shadow / decision-support."
    )
    if data["has_movement"]:
        st.plotly_chart(_movement_chart(data["selections"]),
                        use_container_width=True, config={"displayModeBar": False})
    st.markdown(_movement_table_html(data), unsafe_allow_html=True)


# ============================================================================
# Section 5 — Confirmed lineups (DF-09)
# ============================================================================
# Reuses lineups.lineup_signal — the SAME signal that powers the research-card
# rotation flag (world_cup.py:_render_lineup_flag) — so the deep dive and the card
# never disagree. Decision-support only: a confirmed XI / rotation read is a
# hypothesis to re-check, never a model input.

def _lineup_card_html(team: dict) -> str:
    """Pure HTML card for one team's confirmed XI: team · formation · rotation note
    over the 11 starters. Heavy rotation reads amber (a flag to re-check), a small
    change count reads dim. All names escaped."""
    formation = escape(team.get("formation") or "—")
    changes = team.get("changes")
    note = ""
    if team.get("heavy_rotation"):
        note = (f'<div style="color:{YELLOW};font-weight:700;font-size:0.78rem;'
                f'margin-bottom:2px;">⚠️ heavy rotation · {int(changes)} changes '
                f'vs last XI</div>')
    elif changes is not None:
        plural = "s" if changes != 1 else ""
        note = (f'<div style="color:{TEXT_DIM};font-size:0.78rem;margin-bottom:2px;">'
                f'{int(changes)} change{plural} vs last XI</div>')
    xi_html = "".join(
        f'<li style="padding:2px 0;color:{TEXT};font-size:0.84rem;">{escape(name)}</li>'
        for name in team.get("xi", [])
    )
    return (
        f'<div style="border:1px solid {BORDER};border-radius:8px;padding:10px 12px;'
        f'background:{SURFACE};">'
        f'<div style="color:{TEXT};font-weight:700;font-size:0.95rem;">'
        f'{escape(team["team"])}</div>'
        f'<div style="color:{TEXT_DIM};font-family:JetBrains Mono,monospace;'
        f'font-size:0.8rem;margin-bottom:4px;">Formation {formation}</div>'
        f'{note}<ul style="list-style:none;padding:0;margin:6px 0 0;">{xi_html}</ul>'
        f'</div>'
    )


def _render_lineups(match_id: int) -> None:
    st.markdown('<div class="bv-section-header">Confirmed lineups</div>',
                unsafe_allow_html=True)
    sig = lineup_signal(match_id)
    if not sig or not any(t.get("status") == "announced" for t in sig["teams"]):
        st.info(
            "🔒 Lineups not announced yet — ESPN posts the confirmed XI about an "
            "hour before kickoff. Check back closer to the match."
        )
        return
    st.caption(
        "Confirmed starting XIs and formations. A heavy-rotation flag is a "
        "hypothesis to re-check — a rested XI can undercut a value lean. "
        "Decision-support only; the model and value bets are unchanged."
    )
    teams = sig["teams"]
    heavy = False
    for col, t in zip(st.columns(len(teams)), teams):
        with col:
            if t.get("status") != "announced":
                st.markdown(f'**{escape(t["team"])}**')
                st.caption("XI not announced yet")
                continue
            st.markdown(_lineup_card_html(t), unsafe_allow_html=True)
            heavy = heavy or bool(t.get("heavy_rotation"))
    if heavy:
        st.warning(
            "⚠️ Heavy rotation flagged — a much-changed XI can invalidate a value "
            "pick. A hypothesis to re-check, not a model signal."
        )


# ============================================================================
# Section 1 — Header
# ============================================================================

def _render_header(comp: dict) -> None:
    home_flag = render_flag(comp["home_fifa"]) if comp.get("home_fifa") else ""
    away_flag = render_flag(comp["away_fifa"]) if comp.get("away_fifa") else ""
    kickoff = format_kickoff_et(comp["date"], comp.get("kickoff_time"), with_day=True)

    result_html = ""
    if comp["status"] == "finished" and comp["home_goals"] is not None:
        result_html = (
            f'<div style="margin-top:6px;font-family:JetBrains Mono,monospace;'
            f'font-size:1.6rem;font-weight:700;color:{TEXT};">'
            f'{comp["home_goals"]} - {comp["away_goals"]}</div>'
        )

    st.markdown(
        f'<div style="text-align:center;margin-bottom:18px;">'
        f'<div style="color:{TEXT_DIM};font-size:0.78rem;text-transform:uppercase;'
        f'letter-spacing:0.05em;margin-bottom:6px;">{escape(kickoff)}</div>'
        f'<div style="display:flex;align-items:center;justify-content:center;gap:12px;'
        f'font-size:1.3rem;font-weight:700;color:{TEXT};">'
        f'{home_flag} {escape(comp["home"])} '
        f'<span style="color:{TEXT_DIM};font-size:1rem;font-weight:400;">v</span> '
        f'{escape(comp["away"])} {away_flag}</div>'
        f'{result_html}</div>',
        unsafe_allow_html=True,
    )


# ============================================================================
# No-match picker
# ============================================================================

def _render_picker() -> None:
    """Shown when no match is selected — pick a WC fixture to open its deep dive."""
    st.markdown('<div class="bv-page-title">World Cup — Match Deep Dive</div>',
                unsafe_allow_html=True)
    st.caption("Pick a match to open its model heatmap and full model-vs-books read.")

    HomeTeam = aliased(WCTeam)
    AwayTeam = aliased(WCTeam)
    with get_session() as session:
        rows = session.execute(
            select(WCMatch, HomeTeam.name, AwayTeam.name)
            .join(HomeTeam, WCMatch.home_team_id == HomeTeam.id)
            .join(AwayTeam, WCMatch.away_team_id == AwayTeam.id)
            .order_by(WCMatch.date, WCMatch.kickoff_time)
        ).all()

    if not rows:
        st.info("No World Cup matches in the database yet.")
        return

    upcoming = [(m, hn, an) for m, hn, an in rows if m.status != "finished"]
    recent = [(m, hn, an) for m, hn, an in rows if m.status == "finished"]

    tab_up, tab_recent = st.tabs(["Upcoming", "Recent results"])
    for tab, bucket, key in ((tab_up, upcoming, "wc_dd_pick_up"),
                             (tab_recent, recent, "wc_dd_pick_recent")):
        with tab:
            if not bucket:
                st.info("Nothing here yet.")
                continue
            opts = {m.id: f"{m.date} · {hn} v {an}" for m, hn, an in bucket}
            chosen = st.selectbox("Match", options=list(opts.keys()),
                                  format_func=lambda x, o=opts: o[x], key=key)
            if st.button("Open deep dive", type="primary", key=f"{key}_go"):
                st.query_params["wc_match_id"] = str(chosen)
                st.rerun()


# ============================================================================
# Render one match
# ============================================================================

def _render_deep_dive(match_id: int) -> None:
    comp = build_book_comparison(match_id)
    if not comp:
        st.error(f"World Cup match {match_id} not found.")
        if st.button("← Back to World Cup"):
            st.query_params.pop("wc_match_id", None)
            st.switch_page("views/world_cup.py")
        return

    if st.button("← Back to World Cup"):
        st.query_params.pop("wc_match_id", None)
        st.switch_page("views/world_cup.py")

    st.caption(
        "🔍 Shadow deep dive — read-only model analysis. The World Cup model is "
        "decision-support only; nothing here changes a value bet."
    )
    _render_header(comp)
    st.divider()
    _render_heatmap(comp)
    st.divider()
    _render_model_vs_books(comp)
    st.divider()
    _render_movement(match_id)
    st.divider()
    _render_lineups(match_id)


# ============================================================================
# Page entry — resolve the match id and render
# ============================================================================

# Priority: session_state (set by the WC hub on switch_page) → ?wc_match_id (URL
# share / refresh). Pop session_state after reading so it's one-shot, and sync to
# the query param so the URL stays shareable (mirrors match_detail.py).
_match_id_resolved: int | None = None
if "wc_deep_dive_match_id" in st.session_state:
    _match_id_resolved = int(st.session_state.pop("wc_deep_dive_match_id"))
    st.query_params["wc_match_id"] = str(_match_id_resolved)
if _match_id_resolved is None:
    _qp = st.query_params.get("wc_match_id")
    if _qp:
        try:
            _match_id_resolved = int(_qp)
        except (ValueError, TypeError):
            _match_id_resolved = None

if _match_id_resolved is None:
    _render_picker()
else:
    _render_deep_dive(_match_id_resolved)
