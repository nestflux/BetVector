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
6. Lineup impact (WC-11A-02) — a display-only adjusted-xG what-if: the model's λ
   rescaled by how the confirmed XI's goal-share compares to the team's last XI,
   with a per-player scorer board. Neutral, never an edge; the model is unchanged.
7. Who's likely to score (WC-11A-03) — each confirmed-XI player's anytime-scorer
   chance (P = 1 − e^(−λ)) from his goal-share, ranked, with the penalty taker
   flagged. The model's own ranking; no odds pulled.
8. Player watch (WC-11A-04) — squad notes off the same data: card-prone starters
   (recent club booking rate), stars missing from the last XI, and caps/goals
   milestones. Facts, not model numbers; no odds pulled.
9. Group & qualification impact (DF-10) — the current group table with this tie
   highlighted, plus what each result does to qualification (points-only,
   conservative). Knockout ties say "win or out" instead.
10. Bayesian vs Poisson (DF-10) — the staked Poisson beside the stored Bayesian
    shadow prediction for THIS match (display-only; the Bayesian never stakes).
11. Glossary (DF-10 + WC-11A-02/03/04) — plain-English definitions for the
    deep-dive terms.

The World Cup model is SHADOW / decision-support only — nothing here changes the
model or any value bet.
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
from src.world_cup.player_rates import player_rate
from src.world_cup.predictor import scoreline_matrix_from_lambdas
from src.world_cup.research import (
    build_book_comparison, build_group_context, build_lineup_impact,
    build_model_comparison, build_movement, build_player_watch, build_scorer_board,
)
from src.world_cup.timeutil import format_kickoff_et
from src.delivery.help_content import glossary_sections_html

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

# Position chips (cosmetic): map ESPN's granular abbrev (G, CD-L, AM-R, CF-L, ...)
# to a readable group so a confirmed XI reads like a team sheet. Pure display —
# never touches the model/value path. Colours are a neutral accent palette,
# deliberately NOT the value green/red.
_POS_RANK = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
_POS_COLOR = {"GK": "#D29922", "DEF": "#58A6FF", "MID": "#39C5CF", "FWD": "#A371F7"}
_POS_EXPLICIT = {
    "G": "GK",
    "D": "DEF", "CD": "DEF", "LB": "DEF", "RB": "DEF", "WB": "DEF", "SW": "DEF",
    "M": "MID", "CM": "MID", "DM": "MID", "AM": "MID", "LM": "MID", "RM": "MID",
    "F": "FWD", "CF": "FWD", "LF": "FWD", "RF": "FWD",
    "ST": "FWD", "LW": "FWD", "RW": "FWD", "SS": "FWD",
}


def _position_group(pos):
    """ESPN position abbrev (e.g. 'CD-L', 'AM', 'G') -> 'GK'/'DEF'/'MID'/'FWD',
    or None for a sub/blank/unknown code. Display-only."""
    if not pos:
        return None
    base = str(pos).split("-", 1)[0].strip().upper()
    if base in ("", "SUB"):
        return None
    if base in _POS_EXPLICIT:
        return _POS_EXPLICIT[base]
    # Fallback for an unseen ESPN code: classify by its role letter.
    if base.startswith("G"):
        return "GK"
    if base.endswith(("B", "D")):
        return "DEF"
    if base.endswith("M"):
        return "MID"
    if base.endswith(("F", "W", "S", "T")):
        return "FWD"
    return None


def _position_chip(group) -> str:
    """Fixed-width position badge so names align in a column; an empty same-width
    placeholder when the position is unknown."""
    if not group:
        return '<span style="display:inline-block;width:34px;"></span>'
    col = _POS_COLOR.get(group, TEXT_DIM)
    return (f'<span style="display:inline-block;width:34px;color:{col};'
            f'font-family:JetBrains Mono,monospace;font-size:0.7rem;font-weight:700;'
            f'letter-spacing:0.5px;">{group}</span>')


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
    rows = team.get("xi_rows")
    if rows:
        # Order the XI like a team sheet: GK, then DEF, MID, FWD, then by name —
        # and show each player's position group as a small chip beside the name.
        ordered = sorted(
            rows,
            key=lambda r: (_POS_RANK.get(_position_group(r.get("position")), 9),
                           r.get("name", "")),
        )
        xi_html = "".join(
            f'<li style="padding:2px 0;color:{TEXT};font-size:0.84rem;'
            f'display:flex;align-items:baseline;gap:6px;">'
            f'{_position_chip(_position_group(r.get("position")))}'
            f'<span>{escape(r.get("name", ""))}</span></li>'
            for r in ordered
        )
    else:
        # Fallback (signal without xi_rows): names only, alphabetical.
        xi_html = "".join(
            f'<li style="padding:2px 0;color:{TEXT};font-size:0.84rem;">'
            f'{escape(name)}</li>'
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
# Section 6 — Lineup impact: display-only adjusted-λ (WC-11A-02)
# ============================================================================
# Once the XI is confirmed, build_lineup_impact rescales the model's stored xG (λ)
# by how the announced XI's goal-share compares to the team's last XI. Purely a
# what-if for the eye — the delta is shown NEUTRALLY (not as an edge), and nothing
# here changes the model or a value bet (the value finder still works off the
# model's own λ). Reuses lineup_signal for the XI + player_rates for the rates.

def _impact_scorer_row_html(s: dict) -> str:
    """One scorer-board row: player · goals-per-90 (his goal-share basis) · the
    slice of the adjusted λ he carries. A rotated-out player (not in the XI) reads
    dim + struck through with 'rotated out'; an unrated player shows '—'. Escaped."""
    name = escape(str(s.get("player", "")))
    share = s.get("share")
    exp = s.get("exp_goals")
    share_txt = f"{share:.2f}" if share is not None else "—"
    if not s.get("in_xi", True):
        name_html = (f'<span style="color:{TEXT_DIM};text-decoration:line-through;">'
                     f'{name}</span>')
        xg_html = f'<span style="color:{TEXT_DIM};font-size:0.74rem;">rotated out</span>'
    else:
        name_html = f'<span style="color:{TEXT};">{name}</span>'
        xg_html = (f'<span style="color:{TEXT};font-family:JetBrains Mono,monospace;">'
                   f'{exp:.2f}</span>' if exp is not None else
                   f'<span style="color:{TEXT_DIM};">—</span>')
    return (
        f'<tr><td style="padding:3px 8px;font-size:0.83rem;border-bottom:1px solid {BORDER};">'
        f'{name_html}</td>'
        f'<td style="text-align:center;padding:3px 8px;color:{TEXT_DIM};'
        f'font-family:JetBrains Mono,monospace;font-size:0.8rem;'
        f'border-bottom:1px solid {BORDER};">{share_txt}</td>'
        f'<td style="text-align:center;padding:3px 8px;border-bottom:1px solid {BORDER};">'
        f'{xg_html}</td></tr>'
    )


def _impact_lambda_html(t: dict) -> str:
    """The model-λ → adjusted-λ read for one team. Deliberately NEUTRAL (no
    green/red, no 'edge' framing): the delta is a what-if from the XI, not a signal
    to bet on."""
    lm, la = t.get("lambda_model"), t.get("lambda_adjusted")
    if lm is None or la is None:
        return ""
    if not t.get("baseline_available"):
        return (f'<div style="font-family:JetBrains Mono,monospace;font-size:0.92rem;'
                f'color:{TEXT};margin:2px 0 6px;">model xG <b>{lm:.2f}</b> · adjusted '
                f'<b>{la:.2f}</b> <span style="color:{TEXT_DIM};font-size:0.76rem;">'
                f'(no prior XI to compare — adjusted = model)</span></div>')
    delta = t.get("delta") or 0.0
    arrow = "▲" if delta > 0.005 else ("▼" if delta < -0.005 else "■")
    return (f'<div style="font-family:JetBrains Mono,monospace;font-size:0.92rem;'
            f'color:{TEXT};margin:2px 0 6px;">model xG <b>{lm:.2f}</b> '
            f'<span style="color:{TEXT_DIM};">→</span> adjusted <b>{la:.2f}</b> '
            f'<span style="color:{TEXT_DIM};">({arrow} {delta:+.2f})</span></div>')


def _impact_card_html(t: dict) -> str:
    """Pure HTML card for one team's lineup-impact what-if: the model→adjusted λ
    read, a scorer board (XI goal-share → xG slice, with rotated-out players shown),
    and any unrated players. Names escaped; neutral, display-only framing."""
    nation = escape(str(t.get("team", "")))
    status = t.get("status")
    shell = (f'<div style="border:1px solid {BORDER};border-radius:8px;'
             f'padding:10px 12px;background:{SURFACE};">')
    if status == "not_announced":
        return (f'{shell}<div style="color:{TEXT};font-weight:700;font-size:0.95rem;">'
                f'{nation}</div><div style="color:{TEXT_DIM};font-size:0.82rem;'
                f'margin-top:4px;">XI not announced yet.</div></div>')

    formation = escape(str(t.get("formation") or "—"))
    changes = t.get("changes")
    note = ""
    if t.get("heavy_rotation"):
        note = (f'<div style="color:{YELLOW};font-weight:700;font-size:0.76rem;'
                f'margin-bottom:2px;">⚠️ heavy rotation · {int(changes)} changes vs last XI</div>')
    elif changes is not None:
        plural = "s" if changes != 1 else ""
        note = (f'<div style="color:{TEXT_DIM};font-size:0.76rem;margin-bottom:2px;">'
                f'{int(changes)} change{plural} vs last XI</div>')
    header = (
        f'<div style="color:{TEXT};font-weight:700;font-size:0.95rem;">{nation}</div>'
        f'<div style="color:{TEXT_DIM};font-family:JetBrains Mono,monospace;'
        f'font-size:0.78rem;margin-bottom:2px;">Formation {formation}</div>{note}')
    if status == "no_model":
        return (f'{shell}{header}<div style="color:{TEXT_DIM};font-size:0.82rem;'
                f'margin-top:4px;">XI confirmed, but the model hasn\'t scored this '
                f'match yet — no λ to adjust.</div></div>')

    scorer_rows = "".join(_impact_scorer_row_html(s) for s in t.get("scorers", []))
    board = (
        f'<table style="width:100%;border-collapse:collapse;margin-top:2px;">'
        f'<thead><tr style="color:{TEXT_DIM};">'
        f'<th style="text-align:left;padding:3px 8px;font-size:0.72rem;">Player</th>'
        f'<th style="padding:3px 8px;font-size:0.72rem;">g/90</th>'
        f'<th style="padding:3px 8px;font-size:0.72rem;">xG slice</th></tr></thead>'
        f'<tbody>{scorer_rows}</tbody></table>')
    missing = t.get("missing") or []
    miss_html = ""
    if missing:
        names = escape(", ".join(str(x) for x in missing))
        miss_html = (f'<div style="color:{TEXT_DIM};font-size:0.72rem;margin-top:6px;">'
                     f'Unrated, excluded from the what-if: {names}.</div>')
    return f'{shell}{header}{_impact_lambda_html(t)}{board}{miss_html}</div>'


def _render_lineup_impact(match_id: int) -> None:
    st.markdown(
        f'<div class="bv-section-header">Lineup impact — adjusted xG{_MODEL_BADGE}</div>',
        unsafe_allow_html=True,
    )
    data = build_lineup_impact(match_id, player_rate)
    if not data or not any(t.get("status") == "announced" for t in data["teams"]):
        st.info(
            "🔒 Lineups not announced yet — the adjusted-xG what-if appears once "
            "ESPN posts the confirmed XIs (about an hour before kickoff)."
        )
        return
    st.caption(
        "A display-only what-if from the confirmed XI: the model's expected goals "
        "rescaled by how the announced XI's goal-share compares to the team's last "
        "XI (a rotated-out scorer pulls it down, an upgrade lifts it). It never "
        "changes the model or a bet — the value finder still works off the model's "
        "own xG. Goal-share is each player's recent goals-per-90; the delta is "
        "neutral, not an edge. Unrated players are left out of the what-if."
    )
    for col, t in zip(st.columns(len(data["teams"])), data["teams"]):
        with col:
            st.markdown(_impact_card_html(t), unsafe_allow_html=True)


# ============================================================================
# Section 7 — Who's likely to score (WC-11A-03)
# ============================================================================
# build_scorer_board turns each confirmed-XI player's expected goals (his goal-share
# of the team's adjusted λ, from WC-11A-02) into an anytime-scorer chance,
# P = 1 − e^(−player_λ). This is the MODEL's "who scores" ranking — NOT a market
# line, and NO odds are pulled (zero Odds API credits). The probability is shown
# neutrally (it's an estimate, not an edge); the penalty taker is flagged but not
# bumped (his spot-kicks already sit in his goals-per-90). Display-only, shadow.

def _scorer_row_html(rank: int, p: dict) -> str:
    """One ranked anytime-scorer row: rank · player (+ penalty-taker / international
    tags) · goals-per-90 · the anytime probability with a neutral proportional bar.
    The probability is the model's estimate, shown neutrally — not an edge, not a
    market line. All dynamic strings escaped."""
    name = escape(str(p.get("player", "")))
    prob = p.get("p_anytime") or 0.0
    gp90 = p.get("goals_per_90")
    gp90_txt = f"{gp90:.2f}" if gp90 is not None else "—"
    pct = max(0.0, min(100.0, prob * 100.0))

    tags = ""
    if p.get("is_pen_taker"):
        tags += (f'<span title="Designated penalty taker — his spot-kicks are already '
                 f'in his goals-per-90" style="margin-left:6px;border:1px solid {BORDER};'
                 f'border-radius:4px;padding:0 4px;font-size:0.62rem;color:{TEXT_DIM};'
                 f'font-family:JetBrains Mono,monospace;vertical-align:middle;">PK</span>')
    if p.get("source") == "international":
        tags += (f'<span title="No recent club minutes — rate from international '
                 f'goals-per-cap" style="margin-left:6px;border:1px dashed {BORDER};'
                 f'border-radius:4px;padding:0 4px;font-size:0.62rem;color:{TEXT_DIM};'
                 f'font-family:JetBrains Mono,monospace;vertical-align:middle;">intl</span>')

    return (
        f'<tr>'
        f'<td style="padding:3px 8px;color:{TEXT_DIM};font-family:JetBrains Mono,monospace;'
        f'font-size:0.78rem;border-bottom:1px solid {BORDER};text-align:right;">{rank}</td>'
        f'<td style="padding:3px 8px;color:{TEXT};font-size:0.83rem;'
        f'border-bottom:1px solid {BORDER};">{name}{tags}</td>'
        f'<td style="text-align:center;padding:3px 8px;color:{TEXT_DIM};'
        f'font-family:JetBrains Mono,monospace;font-size:0.8rem;'
        f'border-bottom:1px solid {BORDER};">{gp90_txt}</td>'
        f'<td style="padding:3px 8px;border-bottom:1px solid {BORDER};">'
        f'<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end;">'
        f'<div style="width:46px;height:5px;background:{BORDER};border-radius:3px;'
        f'overflow:hidden;"><div style="width:{pct:.0f}%;height:100%;'
        f'background:{TEXT_DIM};"></div></div>'
        f'<span style="font-family:JetBrains Mono,monospace;color:{TEXT};'
        f'font-size:0.82rem;min-width:34px;text-align:right;">{prob:.0%}</span>'
        f'</div></td></tr>'
    )


def _scorer_board_card_html(t: dict) -> str:
    """Pure HTML card for one team's anytime-scorer board: the ranked XI with each
    player's modelled chance of scoring, the penalty taker flagged, and the
    international-fallback labelled. Names escaped; neutral, display-only framing."""
    nation = escape(str(t.get("team", "")))
    status = t.get("status")
    shell = (f'<div style="border:1px solid {BORDER};border-radius:8px;'
             f'padding:10px 12px;background:{SURFACE};">')
    if status == "not_announced":
        return (f'{shell}<div style="color:{TEXT};font-weight:700;font-size:0.95rem;">'
                f'{nation}</div><div style="color:{TEXT_DIM};font-size:0.82rem;'
                f'margin-top:4px;">XI not announced yet.</div></div>')

    formation = escape(str(t.get("formation") or "—"))
    header = (
        f'<div style="color:{TEXT};font-weight:700;font-size:0.95rem;">{nation}</div>'
        f'<div style="color:{TEXT_DIM};font-family:JetBrains Mono,monospace;'
        f'font-size:0.78rem;margin-bottom:4px;">Formation {formation}</div>')
    if status == "no_model":
        return (f'{shell}{header}<div style="color:{TEXT_DIM};font-size:0.82rem;'
                f'margin-top:4px;">XI confirmed, but the model hasn\'t scored this '
                f'match yet — no expected goals to split.</div></div>')

    players = t.get("players") or []
    if not players:
        return (f'{shell}{header}<div style="color:{TEXT_DIM};font-size:0.82rem;'
                f'margin-top:4px;">No rated scorers in this XI — nothing to rank.</div></div>')

    rows = "".join(_scorer_row_html(i, p) for i, p in enumerate(players, start=1))
    board = (
        f'<table style="width:100%;border-collapse:collapse;margin-top:2px;">'
        f'<thead><tr style="color:{TEXT_DIM};">'
        f'<th style="padding:3px 8px;font-size:0.72rem;text-align:right;">#</th>'
        f'<th style="text-align:left;padding:3px 8px;font-size:0.72rem;">Player</th>'
        f'<th style="padding:3px 8px;font-size:0.72rem;">g/90</th>'
        f'<th style="padding:3px 8px;font-size:0.72rem;text-align:right;">Anytime</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>')

    foot = ""
    if any(p.get("is_pen_taker") for p in players):
        foot += (f'<div style="color:{TEXT_DIM};font-size:0.72rem;margin-top:6px;">'
                 f'<b>PK</b> · takes penalties (already counted in his goals-per-90).</div>')
    if any(p.get("source") == "international" for p in players):
        foot += (f'<div style="color:{TEXT_DIM};font-size:0.72rem;margin-top:2px;">'
                 f'<b>intl</b> · no recent club minutes — rate from international '
                 f'goals-per-cap.</div>')
    missing = t.get("missing") or []
    if missing:
        names = escape(", ".join(str(x) for x in missing))
        foot += (f'<div style="color:{TEXT_DIM};font-size:0.72rem;margin-top:2px;">'
                 f'Unrated, not ranked: {names}.</div>')
    return f'{shell}{header}{board}{foot}</div>'


def _render_scorer_board(match_id: int) -> None:
    st.markdown(
        f'<div class="bv-section-header">Who\'s likely to score{_MODEL_BADGE}</div>',
        unsafe_allow_html=True,
    )
    data = build_scorer_board(match_id, player_rate)
    if not data or not any(t.get("status") == "announced" for t in data["teams"]):
        st.info(
            "🔒 Lineups not announced yet — the anytime-scorer board appears once "
            "ESPN posts the confirmed XIs (about an hour before kickoff)."
        )
        return
    st.caption(
        "The model's view of who's likely to score, from the confirmed XI: each "
        "player's expected goals (his goal-share of the team's adjusted xG) turned "
        "into an anytime chance, P = 1 − e^(−λ). It's the model's ranking — not a "
        "market line and not a bet. The penalty taker is flagged (his spot-kicks are "
        "already in his goals-per-90); unrated players are left out."
    )
    for col, t in zip(st.columns(len(data["teams"])), data["teams"]):
        with col:
            st.markdown(_scorer_board_card_html(t), unsafe_allow_html=True)


# ============================================================================
# Section 8 — Player watch (WC-11A-04)
# ============================================================================
# Small squad notes off the same confirmed-XI + player-rate data: card-prone
# starters (recent club booking rate), stars missing from the team's last XI, and
# players nearing a caps / goals milestone. These are FACTS about the squad, not
# model numbers (so no MODEL badge), and pull NO odds — zero Odds API credits.
# Display-only, shadow: context for the matchup, never a bet.

def _eur_short(value) -> str:
    """Compact euro market value for a chip — €180M / €40M / €900k / —."""
    if not value or value <= 0:
        return "—"
    if value >= 1_000_000:
        return f"€{value / 1_000_000:.0f}M"
    if value >= 1_000:
        return f"€{value / 1_000:.0f}k"
    return f"€{value:.0f}"


def _player_watch_card_html(t: dict) -> str:
    """Pure HTML card for one team's player-watch notes: booking risk (amber, like the
    card it warns about), star absence, and caps / goals milestones — each with a
    graceful empty state. Names + values escaped; neutral, display-only framing."""
    nation = escape(str(t.get("team", "")))
    shell = (f'<div style="border:1px solid {BORDER};border-radius:8px;'
             f'padding:10px 12px;background:{SURFACE};">')
    if t.get("status") == "not_announced":
        return (f'{shell}<div style="color:{TEXT};font-weight:700;font-size:0.95rem;">'
                f'{nation}</div><div style="color:{TEXT_DIM};font-size:0.82rem;'
                f'margin-top:4px;">XI not announced yet.</div></div>')

    formation = escape(str(t.get("formation") or "—"))
    header = (
        f'<div style="color:{TEXT};font-weight:700;font-size:0.95rem;">{nation}</div>'
        f'<div style="color:{TEXT_DIM};font-family:JetBrains Mono,monospace;'
        f'font-size:0.78rem;margin-bottom:2px;">Formation {formation}</div>')

    def _subhead(label: str) -> str:
        return (f'<div style="color:{TEXT_DIM};font-size:0.7rem;text-transform:uppercase;'
                f'letter-spacing:0.05em;margin-top:8px;">{label}</div>')

    body = ""

    booking = t.get("booking_risk") or []
    if booking:
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;gap:8px;padding:2px 0;'
            f'font-size:0.83rem;color:{TEXT};"><span>{escape(str(b.get("player", "")))}'
            f'<span title="High recent club yellow-card rate — card-prone" '
            f'style="margin-left:6px;border:1px solid {YELLOW};border-radius:4px;'
            f'padding:0 4px;font-size:0.62rem;color:{YELLOW};'
            f'font-family:JetBrains Mono,monospace;vertical-align:middle;">YEL</span></span>'
            f'<span style="font-family:JetBrains Mono,monospace;color:{TEXT_DIM};'
            f'font-size:0.8rem;">{(b.get("yellows_per_90") or 0.0):.2f}/90</span></div>'
            for b in booking)
        body += _subhead("Booking risk") + rows

    absent = t.get("absent_stars") or []
    if absent:
        names = ", ".join(escape(str(a.get("player", ""))) for a in absent)
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;gap:8px;padding:2px 0;'
            f'font-size:0.83rem;color:{TEXT};"><span>{escape(str(a.get("player", "")))}</span>'
            f'<span style="font-family:JetBrains Mono,monospace;color:{TEXT_DIM};'
            f'font-size:0.8rem;">{escape(_eur_short(a.get("market_value_eur")))}</span></div>'
            for a in absent)
        body += (_subhead("Star absence")
                 + f'<div style="color:{TEXT};font-size:0.83rem;margin:2px 0;">'
                   f'{nation} without {names}.</div>' + rows
                 + f'<div style="color:{TEXT_DIM};font-size:0.7rem;margin-top:2px;">'
                   f'In the previous XI — rotated out or unavailable.</div>')

    miles = t.get("milestones") or []
    if miles:
        rows = "".join(
            f'<div style="padding:2px 0;font-size:0.83rem;color:{TEXT};">'
            f'{escape(str(m.get("player", "")))} — {int(m.get("away", 0))} from '
            f'{int(m.get("target", 0))} '
            f'{"caps" if m.get("kind") == "caps" else "intl goals"} '
            f'<span style="color:{TEXT_DIM};">({int(m.get("current", 0))} now)</span></div>'
            for m in miles)
        body += _subhead("Milestones") + rows

    if not body:
        body = (f'<div style="color:{TEXT_DIM};font-size:0.82rem;margin-top:4px;">'
                f'Nothing flagged — no notably card-prone starters, star absences, '
                f'or nearby milestones.</div>')

    return f'{shell}{header}{body}</div>'


def _render_player_watch(match_id: int) -> None:
    st.markdown('<div class="bv-section-header">Player watch</div>',
                unsafe_allow_html=True)
    data = build_player_watch(match_id, player_rate)
    if not data or not any(t.get("status") == "announced" for t in data["teams"]):
        st.info(
            "🔒 Lineups not announced yet — player-watch notes appear once ESPN posts "
            "the confirmed XIs (about an hour before kickoff)."
        )
        return
    st.caption(
        "Quick squad notes from the confirmed XI: card-prone starters (recent club "
        "booking rate — a heads-up, not a tournament caution count), stars missing from "
        "the team's last XI, and players nearing a caps or goals milestone. Context "
        "only — not a model number and not a bet."
    )
    for col, t in zip(st.columns(len(data["teams"])), data["teams"]):
        with col:
            st.markdown(_player_watch_card_html(t), unsafe_allow_html=True)


# ============================================================================
# Section 9 — Group & qualification impact (DF-10)
# ============================================================================
# What this match does to the group table, from build_group_context. The
# qualification reads are points-only and deliberately conservative — a
# "through"/"out" label is always mathematically safe, and the 8-best-third-place
# race (which hinges on other groups) stays "in contention". Context, not a bet.

_QUAL_CHIP = {
    "clinched": (GREEN, "✓ through (top 2)"),
    "eliminated": (RED, "✗ out of top 2"),
    "contention": (YELLOW, "… in contention"),
}


def _qual_chip_html(status: str) -> str:
    """Small coloured qualification chip for a status string."""
    colour, label = _QUAL_CHIP.get(status, (TEXT_DIM, "…"))
    return (f'<span style="color:{colour};font-weight:700;font-size:0.78rem;'
            f'font-family:JetBrains Mono,monospace;">{label}</span>')


def _standings_table_html(ctx: dict) -> str:
    """Pure HTML group table; the two teams in this tie are highlighted. Team
    names are escaped; render_flag returns a sanitised <img>."""
    rows = []
    for r in ctx["table"]:
        hi = r["is_match_team"]
        name = (f'{render_flag(r["fifa_code"])} '
                f'<span style="color:{TEXT if hi else TEXT_DIM};'
                f'font-weight:{"700" if hi else "400"};">{escape(r["name"])}</span>')
        bg = "rgba(88,166,255,0.08)" if hi else "transparent"
        rows.append(
            f'<tr style="background:{bg};">'
            f'<td style="padding:4px 8px;color:{TEXT_DIM};">{r["rank"]}</td>'
            f'<td style="padding:4px 8px;">{name}</td>'
            f'<td style="text-align:center;padding:4px 8px;color:{TEXT_DIM};">{r["played"]}</td>'
            f'<td style="text-align:center;padding:4px 8px;color:{TEXT_DIM};">{r["gd"]:+d}</td>'
            f'<td style="text-align:center;padding:4px 8px;color:{TEXT};font-weight:700;'
            f'font-family:JetBrains Mono,monospace;">{r["points"]}</td></tr>'
        )
    return (
        f'<div style="border:1px solid {BORDER};border-radius:8px;overflow:hidden;'
        f'margin-bottom:10px;"><table style="width:100%;border-collapse:collapse;'
        f'font-size:0.84rem;">'
        f'<thead><tr style="color:{TEXT_DIM};border-bottom:1px solid {BORDER};">'
        f'<th style="text-align:left;padding:5px 8px;">#</th>'
        f'<th style="text-align:left;padding:5px 8px;">Team</th>'
        f'<th style="padding:5px 8px;">P</th><th style="padding:5px 8px;">GD</th>'
        f'<th style="padding:5px 8px;">Pts</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _scenario_row_html(ctx: dict, sc: dict) -> str:
    """One 'if this happens' row: each team's resulting points + qualification chip."""
    return (
        f'<tr><td style="padding:5px 8px;color:{TEXT};font-size:0.84rem;'
        f'border-bottom:1px solid {BORDER};">{escape(sc["label"])}</td>'
        f'<td style="padding:5px 8px;border-bottom:1px solid {BORDER};">'
        f'<span style="font-family:JetBrains Mono,monospace;color:{TEXT};">'
        f'{escape(ctx["home"])} {sc["home_pts"]}</span> '
        f'{_qual_chip_html(sc["home_status"])}</td>'
        f'<td style="padding:5px 8px;border-bottom:1px solid {BORDER};">'
        f'<span style="font-family:JetBrains Mono,monospace;color:{TEXT};">'
        f'{escape(ctx["away"])} {sc["away_pts"]}</span> '
        f'{_qual_chip_html(sc["away_status"])}</td></tr>'
    )


def _scenarios_table_html(ctx: dict) -> str:
    """Pure HTML: the three group-result scenarios and what each does to the two
    teams' qualification."""
    rows = "".join(_scenario_row_html(ctx, sc) for sc in ctx["scenarios"])
    return (
        f'<div style="border:1px solid {BORDER};border-radius:8px;overflow:auto;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="color:{TEXT_DIM};">'
        f'<th style="text-align:left;padding:6px 8px;font-size:0.78rem;">Result</th>'
        f'<th style="text-align:left;padding:6px 8px;font-size:0.78rem;">{escape(ctx["home"])}</th>'
        f'<th style="text-align:left;padding:6px 8px;font-size:0.78rem;">{escape(ctx["away"])}</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div>'
    )


def _render_group_context(match_id: int) -> None:
    st.markdown(
        '<div class="bv-section-header">Group &amp; qualification impact</div>',
        unsafe_allow_html=True,
    )
    ctx = build_group_context(match_id)
    if not ctx:
        st.info("No group context for this match.")
        return
    if not ctx["is_group"]:
        # Knockout tie — single elimination, there's no table to move.
        st.info(ctx["headline"])
        return
    st.caption(ctx["headline"])
    st.markdown(_standings_table_html(ctx), unsafe_allow_html=True)
    if ctx["status"] == "finished" and ctx["realized"]:
        r = ctx["realized"]
        st.markdown(
            f'<div style="font-size:0.86rem;color:{TEXT};margin-top:2px;">'
            f'After this result: <b>{escape(ctx["home"])}</b> {r["home_pts"]} '
            f'{_qual_chip_html(r["home_status"])} · <b>{escape(ctx["away"])}</b> '
            f'{r["away_pts"]} {_qual_chip_html(r["away_status"])}</div>',
            unsafe_allow_html=True,
        )
    elif ctx["scenarios"]:
        st.markdown(_scenarios_table_html(ctx), unsafe_allow_html=True)
        st.caption(
            "Qualification reads are points-only and deliberately cautious: "
            "“through”/“out” shows only when it's mathematically certain, and the "
            "8-best-third-place race (which hinges on other groups) stays “in "
            "contention”. Context, not a bet."
        )


# ============================================================================
# Section 10 — Bayesian vs Poisson (per-match shadow read, DF-10)
# ============================================================================
# The two STORED predictions side by side — the staked Poisson and the Bayesian
# shadow — for THIS match. Display-only: the Bayesian never stakes and promotion
# is manual (src/world_cup/bayesian_validation.py). This is a divergence read, not
# a second bet.

def _model_cell_html(value, kind: str, strong: bool = False) -> str:
    """One model's number for a metric ('pct' as a percent, 'num' to 2dp)."""
    if value is None:
        body = "—"
    else:
        body = f"{value:.0%}" if kind == "pct" else f"{value:.2f}"
    weight = "700" if strong else "400"
    return (f'<td style="text-align:center;padding:5px 8px;color:{TEXT};'
            f'font-weight:{weight};font-family:JetBrains Mono,monospace;'
            f'font-size:0.84rem;border-bottom:1px solid {BORDER};">{body}</td>')


def _delta_html(delta, kind: str) -> str:
    """Signed gap (Bayesian − Poisson). Neutral colour — neither model is 'right'
    here; this is a divergence read, not an edge."""
    if delta is None:
        return (f'<td style="text-align:center;padding:5px 8px;color:{TEXT_DIM};'
                f'border-bottom:1px solid {BORDER};">—</td>')
    txt = f"{delta:+.0%}" if kind == "pct" else f"{delta:+.2f}"
    return (f'<td style="text-align:center;padding:5px 8px;color:{TEXT_DIM};'
            f'font-family:JetBrains Mono,monospace;font-size:0.82rem;'
            f'border-bottom:1px solid {BORDER};">{txt}</td>')


def _model_compare_table_html(data: dict) -> str:
    """Pure HTML: per-metric Poisson vs Bayesian (shadow) + the gap. Returned (not
    drawn) so it stays testable + renderable."""
    rows = []
    for r in data["rows"]:
        rows.append(
            f'<tr><td style="padding:5px 8px;color:{TEXT};font-size:0.84rem;'
            f'border-bottom:1px solid {BORDER};">{escape(r["metric"])}</td>'
            f'{_model_cell_html(r["poisson"], r["kind"], strong=True)}'
            f'{_model_cell_html(r["bayesian"], r["kind"])}'
            f'{_delta_html(r["delta"], r["kind"])}</tr>'
        )
    return (
        f'<div style="border:1px solid {BORDER};border-radius:8px;overflow:auto;'
        f'margin-bottom:8px;"><table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="color:{TEXT_DIM};">'
        f'<th style="text-align:left;padding:6px 8px;font-size:0.78rem;">Market</th>'
        f'<th style="padding:6px 8px;font-size:0.78rem;">Poisson{_MODEL_BADGE}</th>'
        f'<th style="padding:6px 8px;font-size:0.78rem;">Bayesian (shadow)</th>'
        f'<th style="padding:6px 8px;font-size:0.78rem;">Δ</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _render_model_compare(match_id: int) -> None:
    st.markdown(
        '<div class="bv-section-header">Bayesian vs Poisson — this match</div>',
        unsafe_allow_html=True,
    )
    data = build_model_comparison(match_id)
    if not data or not data["has_poisson"]:
        st.info(
            "No model prediction for this match yet — the comparison appears once the "
            "WC pipeline has run for this fixture."
        )
        return
    if not data["has_bayesian"]:
        st.info(
            "The Bayesian shadow model hasn't scored this match yet — only the staked "
            "Poisson is shown. The shadow read fills in after the next pipeline run."
        )
    st.caption(
        "The staked Poisson beside the Bayesian shadow model for THIS match. The "
        "Bayesian runs in shadow — it never stakes and promotion is manual; read this "
        "as a divergence check, not a second bet. Δ is Bayesian − Poisson."
    )
    st.markdown(_model_compare_table_html(data), unsafe_allow_html=True)
    if data.get("agreement"):
        st.caption(data["agreement"])


# ============================================================================
# Section 11 — Glossary (DF-10 + WC-11A-02/03/04)
# ============================================================================
# Short, plain-English definitions for the deep-dive terms (the owner is learning,
# MP §12). Built by a pure helper so it stays testable.

# The deep-dive glossary reads its definitions from the shared Help Center source
# (help_content.PAGE_GLOSSARIES["WC Deep Dive"]) so every term is written exactly
# once (HC-06). The CSS chrome stays local; the escaped rows come from the shared
# renderer (glossary_sections_html).
_GLOSSARY_CSS = (
    '<style>'
    '.gloss-row{display:flex;gap:8px;margin-bottom:8px;line-height:1.45;}'
    '.gloss-term{font-family:"JetBrains Mono",monospace;font-size:12px;'
    'font-weight:600;color:#E6EDF3;min-width:150px;flex-shrink:0;}'
    '.gloss-def{font-family:Inter,sans-serif;font-size:12px;color:#8B949E;}'
    '</style>'
)


def _render_glossary() -> None:
    with st.expander("Glossary — deep-dive terms", expanded=False):
        st.markdown(
            _GLOSSARY_CSS + glossary_sections_html("WC Deep Dive"),
            unsafe_allow_html=True,
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
    st.divider()
    _render_lineup_impact(match_id)
    st.divider()
    _render_scorer_board(match_id)
    st.divider()
    _render_player_watch(match_id)
    st.divider()
    _render_group_context(match_id)
    st.divider()
    _render_model_compare(match_id)
    st.divider()
    _render_glossary()


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
