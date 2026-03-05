"""
BetVector — Self-Contained Demo App
====================================
A standalone showcase of the BetVector dashboard with realistic mock data.
No database or pipeline required — run with:

    streamlit run demo_app.py

All data is synthetic but representative of a live EPL matchday (GW29, 2025-26).
Design system is identical to the production dashboard (MP §8).
"""

from __future__ import annotations

import base64
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Page config (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent
_BADGE_DIR = _PROJECT_ROOT / "data" / "badges"
_LOGO_DIR = _PROJECT_ROOT / "docs" / "logo"
_LOGO_WORDMARK = str(_LOGO_DIR / "Bvlogo3.png")
_LOGO_ICON     = str(_LOGO_DIR / "Bvlogo1.5.png")

st.set_page_config(
    page_title="BetVector — Demo",
    page_icon=_LOGO_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Pre-encode wordmark for the centred page header
try:
    _LOGO_B64 = base64.b64encode(Path(_LOGO_WORDMARK).read_bytes()).decode("ascii")
except OSError:
    _LOGO_B64 = ""

# ─────────────────────────────────────────────────────────────────────────────
# Design system — MP §8 tokens
# ─────────────────────────────────────────────────────────────────────────────

BG       = "#0D1117"
SURFACE  = "#161B22"
BORDER   = "#30363D"
TEXT     = "#E6EDF3"
MUTED    = "#8B949E"
GREEN    = "#3FB950"
RED      = "#F85149"
YELLOW   = "#D29922"
BLUE     = "#58A6FF"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

html, body, [class*="css"] {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }}
.stApp {{ background-color: {BG}; }}
[data-testid="stSidebar"] {{ background-color: {SURFACE}; border-right: 1px solid {BORDER}; }}

[data-testid="stMetricValue"] {{
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 28px !important; font-weight: 700 !important;
}}
[data-testid="stMetricLabel"] {{
    font-family: 'Inter', sans-serif !important;
    color: {MUTED} !important; font-size: 12px !important;
    text-transform: uppercase; letter-spacing: 0.5px;
}}
[data-testid="stMetricDelta"] {{ font-family: 'JetBrains Mono', monospace !important; }}

.bv-card {{
    background-color: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 16px; margin-bottom: 12px;
}}
.bv-card:hover {{ border-color: {GREEN}; background-color: #1C2333; }}

.bv-page-title {{
    font-family: 'Inter', sans-serif; font-size: 24px; font-weight: 700;
    color: {TEXT}; margin-bottom: 4px;
}}
.bv-section-header {{
    font-family: 'Inter', sans-serif; font-size: 18px; font-weight: 600;
    color: {TEXT}; margin-bottom: 12px;
}}
.bv-empty-state {{
    text-align: center; padding: 48px 24px; color: {MUTED};
    font-family: 'Inter', sans-serif; font-size: 14px;
}}
.text-muted  {{ color: {MUTED} !important; }}
.text-green  {{ color: {GREEN} !important; }}
.text-red    {{ color: {RED}   !important; }}
.text-yellow {{ color: {YELLOW}!important; }}
.text-blue   {{ color: {BLUE}  !important; }}
.bv-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-family: 'Inter', sans-serif; font-size: 11px; font-weight: 600; color: {BG};
}}
.bv-badge-green  {{ background-color: {GREEN}; }}
.bv-badge-red    {{ background-color: {RED}; }}
.bv-badge-yellow {{ background-color: {YELLOW}; }}
.bv-badge-blue   {{ background-color: {BLUE}; }}
.bv-badge-muted  {{ background-color: #484F58; color: {TEXT}; }}
.demo-banner {{
    background: linear-gradient(135deg, #1C2333 0%, #161B22 100%);
    border: 1px solid {BLUE}; border-radius: 8px;
    padding: 10px 16px; margin-bottom: 16px;
    font-family: 'Inter', sans-serif; font-size: 13px; color: {BLUE};
}}
#MainMenu {{visibility: hidden;}} footer {{visibility: hidden;}} header {{visibility: hidden;}}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


def render_page_logo(width: int = 200) -> None:
    """Render the BetVector wordmark centred at the top of the content area."""
    if not _LOGO_B64:
        return
    st.markdown(
        f'<div style="text-align:center;padding:28px 0 6px;">'
        f'<img src="data:image/png;base64,{_LOGO_B64}" '
        f'style="width:{width}px;max-width:55%;" alt="BetVector">'
        f'</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Badge helper (loads real badges if available, falls back to text)
# ─────────────────────────────────────────────────────────────────────────────

_badge_cache: dict[int, str | None] = {}

def _b64_badge(team_id: int) -> str | None:
    if team_id in _badge_cache:
        return _badge_cache[team_id]
    p = _BADGE_DIR / f"{team_id}.png"
    if p.exists():
        try:
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            _badge_cache[team_id] = b64
            return b64
        except OSError:
            pass
    _badge_cache[team_id] = None
    return None


def badge(team_id: int, name: str, size: int = 20) -> str:
    b64 = _b64_badge(team_id)
    safe = name.replace("&", "&amp;")
    if b64:
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'style="height:{size}px;vertical-align:middle;margin-right:4px;" '
            f'alt="{safe}"> {safe}'
        )
    return safe


# ─────────────────────────────────────────────────────────────────────────────
# Mock data — GW29 EPL 2025-26 (realistic synthetic)
# ─────────────────────────────────────────────────────────────────────────────

TEAMS = {
    # team_id (real DB ids): name
    1:  "Arsenal",
    2:  "Aston Villa",
    3:  "Brentford",
    4:  "Brighton",
    5:  "Burnley",
    6:  "Chelsea",
    7:  "Crystal Palace",
    8:  "Everton",
    9:  "Fulham",
    10: "Leeds United",
    11: "Leicester City",
    12: "Liverpool",
    13: "Luton Town",
    14: "Manchester City",
    15: "Manchester United",
    16: "Newcastle United",
    17: "Nottingham Forest",
    18: "Sheffield United",
    19: "Tottenham Hotspur",
    20: "West Ham United",
    21: "Wolves",
    22: "Sunderland",
}

FIXTURES = [
    # (home_id, away_id, date, kickoff, home_score, away_score, status)
    (1,  4,  "2026-03-07", "12:30", None, None, "scheduled"),
    (14, 12, "2026-03-07", "17:30", None, None, "scheduled"),
    (6,  19, "2026-03-08", "14:00", None, None, "scheduled"),
    (3,  8,  "2026-03-08", "14:00", None, None, "scheduled"),
    (2,  16, "2026-03-08", "16:30", None, None, "scheduled"),
    (20, 15, "2026-03-09", "20:00", None, None, "scheduled"),
    (12, 1,  "2026-02-22", "12:30", 2,    2,    "finished"),
    (19, 14, "2026-02-22", "17:30", 1,    2,    "finished"),
    (4,  6,  "2026-02-23", "14:00", 0,    1,    "finished"),
    (16, 2,  "2026-02-23", "16:30", 3,    1,    "finished"),
    (8,  17, "2026-02-24", "20:00", 0,    0,    "finished"),
]

# Value bets — (home_id, away_id, market, selection, model_prob, odds, edge, confidence, bookmaker)
VALUE_BETS = [
    (1,  4,  "1X2",  "home",  0.62, 2.10, 0.123, "high",   "FanDuel",   "Arsenal are in dominant home form (W5D0L0 last 5). "
                                                                           "Brighton's xGA away (1.81/90) exposes their defensive frailty. "
                                                                           "Model sees 62% home probability vs 47.6% implied."),
    (14, 12, "OU25", "over",  0.71, 1.87, 0.087, "high",   "Pinnacle",  "Man City vs Liverpool routinely exceeds 2.5 goals — 8 of last 10 H2H did. "
                                                                           "Both sides press high; expected goals model forecasts 3.2 total."),
    (6,  19, "BTTS", "yes",   0.67, 1.75, 0.062, "medium", "Bet365",    "Chelsea score in 89% of home games; Spurs score in 83% away. "
                                                                           "Defensive PPDA for both teams is above 9.0 — low press intensity."),
    (2,  16, "1X2",  "away",  0.44, 2.75, 0.095, "high",   "FanDuel",   "Newcastle's away record is exceptional (+1.7 NPxG diff last 5 away). "
                                                                           "Villa's home form has cooled (W2D2L1 last 5). Model: 44% away vs 36.4% implied."),
    (3,  8,  "OU15", "under", 0.58, 2.30, 0.074, "medium", "Betway",    "Brentford vs Everton matches are historically low-scoring (avg 1.8 goals). "
                                                                           "Everton's attack ranks bottom-3 in NPxG; Brentford missing key striker."),
]

# Historical bet log (resolved)
RECENT_BETS = [
    ("2026-02-22", "Liverpool vs Arsenal", "1X2",  "draw",  0.28, 3.80, "won",   38.00,  28.00),
    ("2026-02-22", "Spurs vs Man City",    "OU25", "over",  0.68, 1.91, "won",   19.10,  10.00),
    ("2026-02-23", "Brighton vs Chelsea",  "1X2",  "away",  0.41, 2.60, "lost",  -20.00, 20.00),
    ("2026-02-23", "Newcastle vs V.Villa", "1X2",  "home",  0.58, 1.95, "won",   19.50,  20.00),
    ("2026-02-24", "Everton vs Nott'm F",  "BTTS", "yes",   0.55, 1.72, "lost",  -15.00, 15.00),
    ("2026-02-15", "Arsenal vs Man Utd",   "1X2",  "home",  0.71, 1.65, "won",   16.50,  15.00),
    ("2026-02-15", "Liverpool vs Wolves",  "OU25", "over",  0.74, 1.62, "won",   16.20,  15.00),
    ("2026-02-16", "Chelsea vs Brentford", "1X2",  "home",  0.64, 1.80, "won",   18.00,  15.00),
    ("2026-02-16", "Man City vs Fulham",   "OU35", "over",  0.52, 2.10, "lost",  -20.00, 20.00),
    ("2026-02-08", "Spurs vs West Ham",    "1X2",  "home",  0.61, 1.88, "won",   18.80,  15.00),
]

# League standings (realistic Mar 2026 EPL)
STANDINGS = [
    (12,  "Liverpool",         28, 20, 5, 3, 63, 28, 35, 65),
    (1,   "Arsenal",           28, 18, 7, 3, 58, 24, 34, 61),
    (14,  "Manchester City",   28, 18, 5, 5, 60, 31, 29, 59),
    (6,   "Chelsea",           28, 16, 6, 6, 55, 34, 21, 54),
    (16,  "Newcastle United",  28, 15, 7, 6, 48, 33, 15, 52),
    (2,   "Aston Villa",       28, 14, 6, 8, 52, 40, 12, 48),
    (19,  "Tottenham Hotspur", 28, 13, 5, 10,49, 44, 5,  44),
    (4,   "Brighton",          28, 11, 8, 9, 45, 43, 2,  41),
    (20,  "West Ham United",   28, 10, 7, 11,39, 46, -7, 37),
    (15,  "Manchester United", 28, 10, 6, 12,38, 48, -10,36),
    (9,   "Fulham",            28, 9,  8, 11,38, 42, -4, 35),
    (3,   "Brentford",         28, 9,  7, 12,40, 48, -8, 34),
    (17,  "Nottingham Forest", 28, 9,  6, 13,35, 44, -9, 33),
    (7,   "Crystal Palace",    28, 8,  8, 12,32, 44,-12, 32),
    (21,  "Wolves",            28, 7,  6, 15,30, 52,-22, 27),
    (8,   "Everton",           28, 6,  7, 15,28, 48,-20, 25),
    (10,  "Leeds United",      28, 6,  5, 17,32, 58,-26, 23),
    (22,  "Sunderland",        28, 5,  6, 17,25, 55,-30, 21),
    (5,   "Burnley",           28, 4,  5, 19,22, 60,-38, 17),
    (11,  "Leicester City",    28, 2,  4, 22,20, 68,-48,  10),
]

# Team form (last 5)
TEAM_FORM = {
    "Liverpool":          ["W","W","D","W","W"],
    "Arsenal":            ["W","D","W","W","W"],
    "Manchester City":    ["W","W","L","W","W"],
    "Chelsea":            ["W","W","D","W","L"],
    "Newcastle United":   ["W","D","W","W","D"],
    "Aston Villa":        ["D","W","D","L","W"],
    "Tottenham Hotspur":  ["L","W","W","D","L"],
    "Brighton":           ["D","W","L","D","W"],
}

# NPxG rankings
NPXG = [
    (14, "Manchester City",   1.82, 0.71, 1.11,  7.2, 11.3),
    (12, "Liverpool",         1.76, 0.68, 1.08,  7.8, 12.1),
    (1,  "Arsenal",           1.71, 0.72, 0.99,  8.1, 11.6),
    (6,  "Chelsea",           1.54, 0.81, 0.73,  9.2, 9.4),
    (16, "Newcastle United",  1.48, 0.77, 0.71,  8.9, 10.2),
    (2,  "Aston Villa",       1.41, 0.92, 0.49,  9.8, 8.7),
    (19, "Tottenham Hotspur", 1.38, 1.05, 0.33, 10.1, 8.1),
    (4,  "Brighton",          1.29, 1.11, 0.18, 10.8, 7.9),
    (3,  "Brentford",         1.22, 1.31,-0.09, 11.3, 7.2),
    (20, "West Ham United",   1.18, 1.28,-0.10, 11.7, 6.8),
]

# Bankroll history (100 days of mock data)
_rng = random.Random(42)
_bankroll = [1000.0]
for _ in range(99):
    daily_pnl = _rng.gauss(2.5, 28)
    _bankroll.append(max(_bankroll[-1] + daily_pnl, 400))

BANKROLL_HISTORY = pd.DataFrame({
    "date": [date(2025, 12, 1) + timedelta(days=i) for i in range(100)],
    "bankroll": _bankroll,
})

# Model performance history (Brier score weekly)
_brier_dates = [date(2025, 9, 1) + timedelta(weeks=i) for i in range(26)]
_brier_base = 0.620
_brier_vals = []
for i in range(26):
    noise = _rng.gauss(0, 0.008)
    trend = -0.0016 * i
    _brier_vals.append(round(_brier_base + trend + noise, 4))

BRIER_HISTORY = pd.DataFrame({
    "date": _brier_dates,
    "brier": _brier_vals,
})

# ─────────────────────────────────────────────────────────────────────────────
# Shared rendering helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mono(val: str, colour: str = TEXT) -> str:
    return f'<span style="font-family:\'JetBrains Mono\',monospace;color:{colour};">{val}</span>'


def _badge_pill(label: str, colour: str, text_col: str = BG) -> str:
    return (
        f'<span style="background:{colour};color:{text_col};padding:2px 8px;'
        f'border-radius:4px;font-family:Inter,sans-serif;font-size:11px;'
        f'font-weight:600;margin-right:4px;">{label}</span>'
    )


def _edge_badge(edge: float, is_best: bool = False) -> str:
    """Market edge badge — green/yellow/red, with ring if it's the best pick."""
    pct = edge * 100
    if edge >= 0.10:
        bg, fg = GREEN, BG
    elif edge >= 0.05:
        bg, fg = YELLOW, BG
    elif edge > 0:
        bg, fg = "#30363D", MUTED
    else:
        bg, fg = "#21262D", "#484F58"

    ring = (
        f"box-shadow:0 0 0 2px {BG},0 0 0 4px {BLUE};"
        if is_best else ""
    )
    label = f"+{pct:.0f}%" if edge > 0 else "—"
    return (
        f'<div style="background:{bg};color:{fg};padding:6px 8px;'
        f'border-radius:6px;font-family:\'JetBrains Mono\',monospace;'
        f'font-size:11px;font-weight:700;text-align:center;{ring}">{label}</div>'
    )


def demo_banner(text: str = "⚡ DEMO MODE — All data is synthetic. Represents GW29, EPL 2025-26.") -> None:
    st.markdown(f'<div class="demo-banner">{text}</div>', unsafe_allow_html=True)


def page_title(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="bv-page-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<p class="text-muted">{subtitle}</p>', unsafe_allow_html=True)
    st.divider()


def section_header(title: str) -> None:
    st.markdown(f'<div class="bv-section-header">{title}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 — Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def page_fixtures() -> None:
    demo_banner()
    page_title("Fixtures", "All upcoming & recent EPL matches — model indicators per market")

    # Top Picks banner
    st.markdown(
        f'<div style="background:{SURFACE};border:1px solid {GREEN};border-radius:8px;'
        f'padding:14px 18px;margin-bottom:20px;">'
        f'<div style="font-family:Inter,sans-serif;font-size:13px;font-weight:600;'
        f'color:{GREEN};margin-bottom:10px;">🎯 TOP PICKS THIS GAMEWEEK</div>'
        f'<div style="display:flex;gap:16px;flex-wrap:wrap;">'
        + "".join([
            f'<div style="background:#0D1117;border-radius:6px;padding:10px 14px;">'
            f'<div style="font-size:12px;color:{MUTED};">{m} · {s}</div>'
            f'<div style="font-family:JetBrains Mono,monospace;font-size:14px;'
            f'font-weight:700;color:{GREEN};">+{e:.1f}%</div>'
            f'</div>'
            for m, s, e in [
                ("Arsenal vs Brighton", "Arsenal Win", 12.3),
                ("Man City vs Liverpool", "Over 2.5", 8.7),
                ("Newcastle vs V.Villa", "Away Win", 9.5),
            ]
        ])
        + '</div></div>',
        unsafe_allow_html=True,
    )

    upcoming = [f for f in FIXTURES if f[6] == "scheduled"]
    finished = [f for f in FIXTURES if f[6] == "finished"]

    # ── Upcoming ──────────────────────────────────────────────────────────────
    section_header("Upcoming — GW29")

    MARKET_LABELS = ["H", "D", "A", "O1.5", "U1.5", "O2.5", "U2.5", "BTTS+", "BTTS-"]
    MOCK_EDGES = {
        (1,  4):  [0.123, -0.02,  0.031, -0.04,  0.01,  0.055,  0.02, 0.062, -0.01],
        (14, 12): [-0.01,  0.02, -0.03,  0.091, -0.05,  0.087, -0.04, 0.071, -0.02],
        (6,  19): [0.041,  0.03,  0.022,  0.06, -0.02,  0.048,  0.01, 0.062,  0.02],
        (3,  8):  [0.031, -0.01,  0.044,  0.01,  0.074, -0.02,  0.038, 0.028, 0.051],
        (2,  16): [-0.02,  0.01,  0.095,  0.03, -0.01,  0.044,  0.02,  0.035, 0.018],
        (20, 15): [0.028,  0.04,  0.011,  0.05, -0.01,  0.038,  0.02,  0.042, 0.015],
    }

    for home_id, away_id, dt, ko, _, __, ___ in upcoming:
        key = (home_id, away_id)
        home_name = TEAMS[home_id]
        away_name = TEAMS[away_id]
        edges = MOCK_EDGES.get(key, [0.0] * 9)
        best_idx = max(range(9), key=lambda i: edges[i])

        # Find matching value bet explanation
        vb_info = next(
            (vb for vb in VALUE_BETS if vb[0] == home_id and vb[1] == away_id), None
        )
        pred_home = round(_rng.uniform(1.1, 2.4), 1)
        pred_away = round(_rng.uniform(0.7, 1.8), 1)

        cards_html = "".join(
            f'<div style="text-align:center;">'
            f'<div style="font-size:9px;color:{MUTED};margin-bottom:4px;">{MARKET_LABELS[i]}</div>'
            + _edge_badge(edges[i], is_best=(i == best_idx))
            + '</div>'
            for i in range(9)
        )

        # Border highlight: green if has a value bet
        border = f"border-left: 3px solid {GREEN};" if vb_info else f"border-left: 3px solid {BORDER};"
        data_badge = _badge_pill("⚡ VALUE BET", GREEN) if vb_info else ""

        st.markdown(
            f'<div class="bv-card" style="{border}">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">'
            f'<div>'
            f'<div style="font-family:Inter,sans-serif;font-size:16px;font-weight:600;color:{TEXT};">'
            f'{badge(home_id, home_name)} <span style="color:{MUTED};">vs</span> {badge(away_id, away_name)}'
            f'</div>'
            f'<div style="font-size:12px;color:{MUTED};margin-top:3px;">EPL · {dt} · {ko}</div>'
            f'</div>'
            f'<div style="text-align:right;">'
            f'{data_badge}'
            f'<div style="font-size:11px;color:{MUTED};margin-top:4px;">'
            f'Model: {_mono(f"{pred_home:.1f} – {pred_away:.1f}", BLUE)}'
            f'</div>'
            f'</div>'
            f'</div>'
            f'<div style="display:grid;grid-template-columns:repeat(9,1fr);gap:6px;">{cards_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if vb_info:
            with st.expander(f"Model narrative — {home_name} vs {away_name}"):
                st.markdown(
                    f'<p style="font-family:Inter,sans-serif;font-size:13px;color:{MUTED};">'
                    f'{vb_info[8]}</p>',
                    unsafe_allow_html=True,
                )

    # ── Recent Results ─────────────────────────────────────────────────────────
    st.divider()
    section_header("Recent Results")

    for home_id, away_id, dt, ko, hg, ag, status in finished:
        home_name = TEAMS[home_id]
        away_name = TEAMS[away_id]
        win_col = (
            GREEN if hg > ag else RED if hg < ag else YELLOW
        )
        st.markdown(
            f'<div class="bv-card" style="display:flex;align-items:center;gap:12px;padding:10px 16px;">'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:12px;color:{MUTED};min-width:85px;">{dt}</span>'
            f'<span style="font-family:Inter,sans-serif;font-size:14px;color:{TEXT};flex:1;text-align:right;">'
            f'{badge(home_id, home_name)}</span>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:16px;font-weight:700;'
            f'color:{win_col};min-width:50px;text-align:center;">{hg} – {ag}</span>'
            f'<span style="font-family:Inter,sans-serif;font-size:14px;color:{TEXT};flex:1;">'
            f'{badge(away_id, away_name)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — Today's Picks
# ─────────────────────────────────────────────────────────────────────────────

def page_picks() -> None:
    demo_banner()
    page_title("Today's Picks", "Value bets — one card per unique pick, best bookmaker shown")

    MARKET_DISPLAY = {
        "1X2": "Match Result", "OU25": "Over/Under 2.5 Goals",
        "OU15": "Over/Under 1.5 Goals", "BTTS": "Both Teams To Score",
    }
    SELECTION_DISPLAY = {
        ("1X2","home"): "Home Win",  ("1X2","draw"): "Draw",  ("1X2","away"): "Away Win",
        ("OU25","over"): "Over 2.5", ("OU25","under"): "Under 2.5",
        ("OU15","under"): "Under 1.5",
        ("BTTS","yes"): "BTTS Yes",
    }

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Upcoming Picks", len(VALUE_BETS))
    col2.metric("Avg Edge", f"{sum(v[6] for v in VALUE_BETS)/len(VALUE_BETS):.1%}")
    col3.metric("High Confidence", sum(1 for v in VALUE_BETS if v[7] == "high"))
    col4.metric("Best Edge", f"+{max(v[6] for v in VALUE_BETS):.1%}")

    st.divider()

    st.markdown(
        f'<div style="font-family:Inter,sans-serif;font-size:14px;font-weight:600;'
        f'color:{TEXT};margin:20px 0 10px;text-transform:uppercase;letter-spacing:0.5px;">'
        f'2026-03-07 — 2026-03-10 '
        f'<span style="font-size:12px;font-weight:400;color:#484F58;margin-left:8px;">'
        f'{len(VALUE_BETS)} picks</span></div>',
        unsafe_allow_html=True,
    )

    for i, vb in enumerate(VALUE_BETS):
        home_id, away_id, mkt, sel, model_prob, odds, edge, conf, bookmaker, explanation = vb
        home_name = TEAMS[home_id]
        away_name = TEAMS[away_id]
        selection_label = SELECTION_DISPLAY.get((mkt, sel), f"{mkt}/{sel}")
        market_label = MARKET_DISPLAY.get(mkt, mkt)
        edge_pct = edge * 100
        edge_col = GREEN if edge_pct >= 10 else YELLOW if edge_pct >= 5 else TEXT

        # Match date from FIXTURES
        fix = next((f for f in FIXTURES if f[0] == home_id and f[1] == away_id), None)
        match_date = fix[2] if fix else "2026-03-08"
        kickoff = fix[3] if fix else "TBD"

        conf_colour = {"high": GREEN, "medium": YELLOW, "low": "#484F58"}[conf]
        conf_badge = _badge_pill(conf.upper(), conf_colour)
        bk_colour = BLUE if bookmaker == "FanDuel" else TEXT
        suggested_stake = round(1000 * 0.02, 2)

        st.markdown(
            f'<div class="bv-card">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">'
            f'<div>'
            f'<div style="font-family:Inter,sans-serif;font-size:16px;font-weight:600;color:{TEXT};">'
            f'{badge(home_id, home_name)} vs {badge(away_id, away_name)}'
            f'</div>'
            f'<div style="font-size:12px;color:{MUTED};margin-top:3px;">'
            f'EPL · {match_date} · {kickoff}</div>'
            f'</div>'
            f'<div>{conf_badge}</div>'
            f'</div>'
            f'<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:8px;">'
            f'<div><span style="font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;">Market</span><br>'
            f'<span style="font-size:14px;color:{TEXT};">{selection_label}</span></div>'
            f'<div><span style="font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;">Model Prob</span><br>'
            f'{_mono(f"{model_prob:.1%}")}</div>'
            f'<div><span style="font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;">Best Odds</span><br>'
            f'{_mono(f"{odds:.2f}")}</div>'
            f'<div><span style="font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;">Edge</span><br>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:14px;font-weight:700;color:{edge_col};">+{edge_pct:.1f}%</span></div>'
            f'<div><span style="font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;">Bookmaker</span><br>'
            f'<span style="color:{bk_colour};font-size:14px;">{bookmaker}</span></div>'
            f'<div><span style="font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;">Suggested Stake</span><br>'
            f'{_mono(f"£{suggested_stake:.2f}")}</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        with st.expander("Model explanation & details"):
            st.markdown(
                f'<p style="font-family:Inter,sans-serif;font-size:13px;color:{MUTED};">{explanation}</p>',
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            c1.metric("Implied Prob", f"{1/odds:.1%}")
            c2.metric("Expected Value", f"+{(model_prob * odds - 1):.3f}")
            c3.metric("Alt. Bookmakers", f"{_rng.randint(3, 12)}")
            if st.button("🔍 Deep Dive", key=f"dive_{i}"):
                st.info("In the live dashboard, this opens the full Match Deep Dive page.")

    # Glossary
    st.divider()
    with st.expander("Glossary — What do these terms mean?"):
        glossary = {
            "Model Prob": "The model's estimated probability of the outcome, based on xG, form, Elo rating, and market signals.",
            "Odds": "Decimal odds offered by the bookmaker. Odds of 2.10 → win £2.10 per £1 staked (including your stake back).",
            "Edge": "Gap between model probability and the bookmaker's implied probability. Positive edge = underpriced bet.",
            "Suggested Stake": "Recommended bet size from Kelly / flat staking rules applied to your bankroll.",
            "Confidence": "HIGH = edge ≥10%, MEDIUM = 5-10%, LOW = marginal signal.",
        }
        for term, defn in glossary.items():
            st.markdown(
                f'<div style="display:flex;gap:8px;margin-bottom:8px;">'
                f'<span style="font-family:JetBrains Mono,monospace;font-size:12px;font-weight:600;'
                f'color:{TEXT};min-width:140px;">{term}</span>'
                f'<span style="font-family:Inter,sans-serif;font-size:12px;color:{MUTED};">{defn}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 — Performance Tracker
# ─────────────────────────────────────────────────────────────────────────────

def page_performance() -> None:
    demo_banner()
    page_title("Performance Tracker", "P&L, win rate, and historical bet results")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total P&L",     "+£342.10",  delta="+£38.00 last 7d")
    col2.metric("Win Rate",       "58.3%",    delta="+2.1pp last 30d")
    col3.metric("ROI",            "+8.9%",    delta="+1.3pp last 30d")
    col4.metric("Bets Placed",    "72")
    col5.metric("Avg Edge Found", "+8.2%")

    st.divider()

    # ── Rolling P&L chart ──────────────────────────────────────────────────
    section_header("Cumulative P&L — Last 90 Days")

    cum_pnl = [0.0]
    for _, _, _, _, odds, _, outcome, pnl, _ in RECENT_BETS[-10:]:
        cum_pnl.append(cum_pnl[-1] + pnl)

    # Extend with synthetic 90-day history
    full_dates = [date(2025, 12, 1) + timedelta(days=i) for i in range(90)]
    np.random.seed(42)
    daily_returns = np.random.normal(3.5, 25, 90)
    cum_returns = np.cumsum(daily_returns)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=full_dates,
        y=cum_returns,
        mode="lines",
        fill="tozeroy",
        line=dict(color=GREEN, width=2),
        fillcolor="rgba(63,185,80,0.1)",
        name="Cumulative P&L",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color=MUTED, line_width=1)
    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=SURFACE,
        font=dict(family="Inter", color=TEXT, size=12),
        xaxis=dict(showgrid=False, color=MUTED),
        yaxis=dict(showgrid=True, gridcolor=BORDER, color=MUTED, tickprefix="£"),
        margin=dict(l=0, r=0, t=20, b=0),
        height=280,
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Win/Loss by market ────────────────────────────────────────────────
    st.divider()
    section_header("Performance by Market")

    perf_data = {
        "1X2":  {"bets": 38, "won": 23, "roi": 11.2},
        "OU25": {"bets": 22, "won": 13, "roi":  6.8},
        "BTTS": {"bets": 9,  "won":  4, "roi": -3.1},
        "OU15": {"bets": 3,  "won":  2, "roi":  8.4},
    }

    for mkt, d in perf_data.items():
        wr = d["won"] / d["bets"] * 100
        roi_col = GREEN if d["roi"] > 0 else RED
        pct = d["won"] / d["bets"]
        bar_html = (
            f'<div style="background:{BORDER};border-radius:4px;height:6px;margin:6px 0;">'
            f'<div style="background:{GREEN};width:{pct*100:.0f}%;height:100%;border-radius:4px;"></div>'
            f'</div>'
        )
        st.markdown(
            f'<div class="bv-card" style="padding:12px 16px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-family:Inter,sans-serif;font-size:14px;font-weight:600;color:{TEXT};">{mkt}</span>'
            f'<div style="display:flex;gap:20px;">'
            f'<div style="text-align:right;"><div style="font-size:10px;color:{MUTED};">BETS</div>'
            f'<div style="font-family:JetBrains Mono,monospace;color:{TEXT};">{d["bets"]}</div></div>'
            f'<div style="text-align:right;"><div style="font-size:10px;color:{MUTED};">WIN RATE</div>'
            f'<div style="font-family:JetBrains Mono,monospace;color:{TEXT};">{wr:.0f}%</div></div>'
            f'<div style="text-align:right;"><div style="font-size:10px;color:{MUTED};">ROI</div>'
            f'<div style="font-family:JetBrains Mono,monospace;font-weight:700;color:{roi_col};">'
            f'{d["roi"]:+.1f}%</div></div>'
            f'</div></div>'
            f'{bar_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Recent bet log ────────────────────────────────────────────────────
    st.divider()
    section_header("Recent Bets")

    for dt, match, mkt, sel, model_p, odds, outcome, pnl, stake in RECENT_BETS:
        outcome_col = GREEN if outcome == "won" else RED
        pnl_str = f"+£{pnl:.2f}" if pnl > 0 else f"-£{abs(pnl):.2f}"
        pnl_col = GREEN if pnl > 0 else RED
        st.markdown(
            f'<div class="bv-card" style="display:flex;align-items:center;gap:12px;padding:10px 16px;">'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:11px;color:{MUTED};min-width:85px;">{dt}</span>'
            f'<span style="font-family:Inter,sans-serif;font-size:13px;color:{TEXT};flex:1;">{match}</span>'
            f'<span style="font-family:Inter,sans-serif;font-size:12px;color:{MUTED};">{mkt} / {sel}</span>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:12px;color:{TEXT};">{odds:.2f}</span>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:13px;font-weight:700;'
            f'color:{outcome_col};">{outcome.upper()}</span>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:13px;font-weight:700;'
            f'color:{pnl_col};">{pnl_str}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 4 — League Explorer
# ─────────────────────────────────────────────────────────────────────────────

def page_leagues() -> None:
    demo_banner()
    page_title("League Explorer", "Standings, form, NPxG rankings, and upcoming fixtures")

    # Standings
    section_header("Standings — EPL 2025-26 (GW28)")

    header_cells = "".join(
        f'<th style="padding:8px 12px;text-align:{"left" if c=="Team" else "right"};'
        f'font-family:Inter,sans-serif;font-size:12px;font-weight:600;color:{MUTED};'
        f'border-bottom:1px solid {BORDER};text-transform:uppercase;letter-spacing:0.5px;">{c}</th>'
        for c in ["Pos", "Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"]
    )
    rows_html = []
    for i, (tid, name, p, w, d, l, gf, ga, gd, pts) in enumerate(STANDINGS):
        bg = BG if i % 2 == 0 else SURFACE
        # Champions League positions: green border left for top 4
        cl_style = f"border-left:3px solid {GREEN};" if i < 4 else (
            f"border-left:3px solid {YELLOW};" if i == 4 else
            f"border-left:3px solid {RED};" if i >= 17 else ""
        )
        team_cell = badge(tid, name, size=18)
        cells = [
            f'<td style="padding:8px 12px;text-align:left;font-family:JetBrains Mono,monospace;color:{TEXT};">{i+1}</td>',
            f'<td style="padding:8px 12px;text-align:left;font-family:Inter,sans-serif;color:{TEXT};">{team_cell}</td>',
        ] + [
            f'<td style="padding:8px 12px;text-align:right;font-family:JetBrains Mono,monospace;color:{TEXT};">{v}</td>'
            for v in [p, w, d, l, gf, ga, f"+{gd}" if gd > 0 else str(gd),
                       f'<strong style="color:{GREEN if i<4 else TEXT};">{pts}</strong>']
        ]
        rows_html.append(
            f'<tr style="background:{bg};{cl_style}border-bottom:1px solid {BORDER};">'
            f'{"".join(cells)}</tr>'
        )

    standings_table = (
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="background:{SURFACE};">{header_cells}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table>'
        f'<div style="font-size:11px;color:{MUTED};margin-top:8px;">'
        f'<span style="color:{GREEN};">■</span> Champions League &nbsp;'
        f'<span style="color:{YELLOW};">■</span> Europa League &nbsp;'
        f'<span style="color:{RED};">■</span> Relegation zone</div>'
    )
    st.markdown(standings_table, unsafe_allow_html=True)

    # Team Form
    st.divider()
    section_header("Team Form (Last 5 Matches)")

    for team_name, form in TEAM_FORM.items():
        tid = next((k for k, v in TEAMS.items() if v == team_name), None)
        badges_html = "".join(
            f'<span style="display:inline-block;width:24px;height:24px;border-radius:50%;'
            f'background:{GREEN if r=="W" else RED if r=="L" else YELLOW};'
            f'color:{BG};text-align:center;line-height:24px;font-family:Inter,sans-serif;'
            f'font-size:11px;font-weight:600;margin-right:4px;">{r}</span>'
            for r in form
        )
        pts = sum(3 if r == "W" else 1 if r == "D" else 0 for r in form)
        st.markdown(
            f'<div class="bv-card" style="display:flex;justify-content:space-between;align-items:center;padding:10px 16px;">'
            f'<span style="font-family:Inter,sans-serif;font-size:14px;color:{TEXT};min-width:200px;">'
            f'{badge(tid, team_name, 18) if tid else team_name}</span>'
            f'<div>{badges_html}</div>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:14px;color:{MUTED};">{pts} pts</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # NPxG Rankings
    st.divider()
    section_header("NPxG Performance Rankings (Last 5 Matches)")
    st.markdown(
        f'<p style="font-family:Inter,sans-serif;font-size:13px;color:{MUTED};margin-bottom:12px;">'
        f'Non-penalty expected goals difference — strips out penalty luck for a truer attacking quality measure. '
        f'PPDA = pressing intensity (lower = more aggressive).</p>',
        unsafe_allow_html=True,
    )

    npxg_header = "".join(
        f'<th style="padding:8px 12px;text-align:{"left" if c in ("Rank","Team") else "right"};'
        f'font-family:Inter,sans-serif;font-size:12px;font-weight:600;color:{MUTED};'
        f'border-bottom:1px solid {BORDER};text-transform:uppercase;">{c}</th>'
        for c in ["Rank", "Team", "NPxG", "NPxGA", "NPxG Diff", "PPDA", "Deep Comps"]
    )
    npxg_rows = []
    for i, (tid, name, npxg, npxga, diff, ppda, deep) in enumerate(NPXG):
        bg = BG if i % 2 == 0 else SURFACE
        diff_col = GREEN if diff > 0 else RED
        diff_str = f'+{diff:.2f}' if diff > 0 else f'{diff:.2f}'
        npxg_rows.append(
            f'<tr style="background:{bg};border-bottom:1px solid {BORDER};">'
            f'<td style="padding:8px 12px;font-family:JetBrains Mono,monospace;color:{MUTED};">{i+1}</td>'
            f'<td style="padding:8px 12px;font-family:Inter,sans-serif;color:{TEXT};">{badge(tid, name, 18)}</td>'
            f'<td style="padding:8px 12px;text-align:right;font-family:JetBrains Mono,monospace;color:{TEXT};">{npxg:.2f}</td>'
            f'<td style="padding:8px 12px;text-align:right;font-family:JetBrains Mono,monospace;color:{TEXT};">{npxga:.2f}</td>'
            f'<td style="padding:8px 12px;text-align:right;font-family:JetBrains Mono,monospace;font-weight:700;color:{diff_col};">{diff_str}</td>'
            f'<td style="padding:8px 12px;text-align:right;font-family:JetBrains Mono,monospace;color:{TEXT};">{ppda:.1f}</td>'
            f'<td style="padding:8px 12px;text-align:right;font-family:JetBrains Mono,monospace;color:{TEXT};">{deep:.1f}</td>'
            f'</tr>'
        )
    st.markdown(
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="background:{SURFACE};">{npxg_header}</tr></thead>'
        f'<tbody>{"".join(npxg_rows)}</tbody>'
        f'</table>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 5 — Model Health
# ─────────────────────────────────────────────────────────────────────────────

def page_model_health() -> None:
    demo_banner()
    page_title("Model Health", "Brier score, calibration, and self-improvement diagnostics")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Current Brier", "0.5781",  delta="-0.0324 vs baseline")
    col2.metric("Calibration Error", "2.1%", delta="-0.4pp last recal")
    col3.metric("Training Matches", "2,280")
    col4.metric("Last Retrain", "2026-01-15")

    st.divider()

    # Brier score trend
    section_header("Brier Score Trend — Season 2025-26")
    st.markdown(
        f'<p style="font-size:13px;color:{MUTED};margin-bottom:12px;">'
        f'Lower is better. Baseline (random) = 0.6667. Perfect calibration = 0.0.</p>',
        unsafe_allow_html=True,
    )

    fig_brier = go.Figure()
    fig_brier.add_hline(y=0.6667, line_dash="dash", line_color=MUTED,
                        annotation_text="Baseline (random)", annotation_font_color=MUTED)
    fig_brier.add_trace(go.Scatter(
        x=BRIER_HISTORY["date"], y=BRIER_HISTORY["brier"],
        mode="lines+markers",
        line=dict(color=BLUE, width=2),
        marker=dict(size=5, color=BLUE),
        name="Brier Score",
    ))
    fig_brier.update_layout(
        paper_bgcolor=BG, plot_bgcolor=SURFACE,
        font=dict(family="Inter", color=TEXT, size=12),
        xaxis=dict(showgrid=False, color=MUTED),
        yaxis=dict(showgrid=True, gridcolor=BORDER, color=MUTED, range=[0.54, 0.69]),
        margin=dict(l=0, r=0, t=20, b=0),
        height=280, showlegend=False,
    )
    st.plotly_chart(fig_brier, use_container_width=True)

    # Calibration curve
    st.divider()
    section_header("Calibration Curve")
    st.markdown(
        f'<p style="font-size:13px;color:{MUTED};margin-bottom:12px;">'
        f'Perfect calibration = diagonal. Points above line = model under-confident. '
        f'Points below = over-confident.</p>',
        unsafe_allow_html=True,
    )

    np.random.seed(0)
    mean_pred = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    fraction_pos = mean_pred + np.random.normal(0, 0.03, len(mean_pred))
    fraction_pos = np.clip(fraction_pos, 0, 1)

    fig_cal = go.Figure()
    fig_cal.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1], mode="lines",
        line=dict(color=MUTED, dash="dash", width=1),
        name="Perfect calibration",
    ))
    fig_cal.add_trace(go.Scatter(
        x=mean_pred, y=fraction_pos, mode="lines+markers",
        line=dict(color=GREEN, width=2),
        marker=dict(size=8, color=GREEN),
        name="BetVector model",
    ))
    fig_cal.update_layout(
        paper_bgcolor=BG, plot_bgcolor=SURFACE,
        font=dict(family="Inter", color=TEXT, size=12),
        xaxis=dict(title="Mean Predicted Probability", showgrid=True, gridcolor=BORDER, color=MUTED),
        yaxis=dict(title="Fraction of Positives", showgrid=True, gridcolor=BORDER, color=MUTED),
        margin=dict(l=0, r=0, t=20, b=0),
        height=280, showlegend=True,
        legend=dict(bgcolor=SURFACE, bordercolor=BORDER),
    )
    st.plotly_chart(fig_cal, use_container_width=True)

    # Feature importance
    st.divider()
    section_header("Top Feature Importances (Poisson Model)")

    features = [
        ("home_npxg_diff_5",        0.142),
        ("elo_diff",                 0.118),
        ("home_form_5",              0.094),
        ("market_implied_home_prob", 0.088),
        ("away_npxg_diff_5",         0.081),
        ("home_ppda_5",              0.074),
        ("congestion_home",          0.062),
        ("weather_wind_speed",       0.041),
        ("away_form_5",              0.038),
        ("referee_cards_per_game",   0.033),
    ]
    for feat, imp in features:
        bar_w = imp / features[0][1] * 100
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:12px;color:{TEXT};min-width:220px;">{feat}</span>'
            f'<div style="flex:1;background:{BORDER};border-radius:4px;height:8px;">'
            f'<div style="background:{BLUE};width:{bar_w:.0f}%;height:100%;border-radius:4px;"></div>'
            f'</div>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:12px;color:{MUTED};min-width:40px;text-align:right;">'
            f'{imp:.3f}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 6 — Bankroll Manager
# ─────────────────────────────────────────────────────────────────────────────

def page_bankroll() -> None:
    demo_banner()
    page_title("Bankroll Manager", "Track your bankroll, staking, and drawdown")

    col1, col2, col3, col4, col5 = st.columns(5)
    current = BANKROLL_HISTORY["bankroll"].iloc[-1]
    peak = BANKROLL_HISTORY["bankroll"].max()
    drawdown = (peak - current) / peak * 100
    starting = 1000.0
    col1.metric("Current Bankroll", f"£{current:.2f}", delta=f"+£{current-starting:.2f} from start")
    col2.metric("Peak",            f"£{peak:.2f}")
    col3.metric("Drawdown",        f"-{drawdown:.1f}%")
    col4.metric("Starting",        f"£{starting:.2f}")
    col5.metric("Staking Method",  "Flat 2%")

    st.divider()
    section_header("Bankroll Curve — Last 100 Days")

    fig_br = go.Figure()
    fig_br.add_hline(y=starting, line_dash="dash", line_color=MUTED,
                     annotation_text="Starting bankroll", annotation_font_color=MUTED)
    fig_br.add_trace(go.Scatter(
        x=BANKROLL_HISTORY["date"], y=BANKROLL_HISTORY["bankroll"],
        mode="lines", fill="tozeroy",
        line=dict(color=GREEN if current >= starting else RED, width=2),
        fillcolor=f"rgba({'63,185,80' if current >= starting else '248,81,73'},0.1)",
        name="Bankroll",
    ))
    fig_br.update_layout(
        paper_bgcolor=BG, plot_bgcolor=SURFACE,
        font=dict(family="Inter", color=TEXT, size=12),
        xaxis=dict(showgrid=False, color=MUTED),
        yaxis=dict(showgrid=True, gridcolor=BORDER, color=MUTED, tickprefix="£"),
        margin=dict(l=0, r=0, t=20, b=0),
        height=300, showlegend=False,
    )
    st.plotly_chart(fig_br, use_container_width=True)

    # Safety limits status
    st.divider()
    section_header("Safety Limits")

    limits = [
        ("Max Single Bet",        "5% of bankroll", f"£{current*0.05:.2f}", True),
        ("Daily Loss Limit",      "10% of bankroll", f"£{current*0.10:.2f}", True),
        ("Drawdown Alert",        "25% from peak", f"-{drawdown:.1f}% ({drawdown<25 and 'OK' or '⚠️ ALERT'})", drawdown < 25),
        ("Min Bankroll Floor",    "50% of starting", f"£{starting*0.5:.2f}", current >= starting * 0.5),
    ]
    for label, rule, val, ok in limits:
        status_col = GREEN if ok else RED
        status = "✓ SAFE" if ok else "⚠ ALERT"
        st.markdown(
            f'<div class="bv-card" style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;">'
            f'<div>'
            f'<div style="font-family:Inter,sans-serif;font-size:14px;font-weight:600;color:{TEXT};">{label}</div>'
            f'<div style="font-size:12px;color:{MUTED};">{rule}</div>'
            f'</div>'
            f'<div style="display:flex;gap:16px;align-items:center;">'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:13px;color:{TEXT};">{val}</span>'
            f'<span style="font-family:Inter,sans-serif;font-size:12px;font-weight:600;color:{status_col};">{status}</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 7 — Match Deep Dive
# ─────────────────────────────────────────────────────────────────────────────

def page_deep_dive() -> None:
    demo_banner()
    page_title("Match Deep Dive", "Full analysis for Arsenal vs Brighton — GW29")

    home_id, away_id = 1, 4
    home_name, away_name = TEAMS[home_id], TEAMS[away_id]

    # Match header
    st.markdown(
        f'<div class="bv-card" style="text-align:center;padding:24px;">'
        f'<div style="display:flex;justify-content:center;align-items:center;gap:32px;">'
        f'<div style="text-align:center;">'
        f'<div style="font-size:40px;">{badge(home_id, "", 48)}</div>'
        f'<div style="font-family:Inter,sans-serif;font-size:20px;font-weight:700;color:{TEXT};margin-top:8px;">{home_name}</div>'
        f'<div style="font-size:12px;color:{MUTED};">HOME</div>'
        f'</div>'
        f'<div style="text-align:center;">'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:32px;color:{MUTED};">VS</div>'
        f'<div style="font-size:12px;color:{MUTED};margin-top:4px;">2026-03-07 · 12:30</div>'
        f'<div style="font-size:11px;color:{MUTED};">Emirates Stadium</div>'
        f'</div>'
        f'<div style="text-align:center;">'
        f'<div style="font-size:40px;">{badge(away_id, "", 48)}</div>'
        f'<div style="font-family:Inter,sans-serif;font-size:20px;font-weight:700;color:{TEXT};margin-top:8px;">{away_name}</div>'
        f'<div style="font-size:12px;color:{MUTED};">AWAY</div>'
        f'</div>'
        f'</div>'
        f'<div style="margin-top:16px;font-family:JetBrains Mono,monospace;font-size:24px;font-weight:700;color:{BLUE};">'
        f'Model: 1.8 – 0.9</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Scoreline matrix
    st.divider()
    section_header("Scoreline Probability Matrix (7×7)")
    st.markdown(
        f'<p style="font-size:13px;color:{MUTED};margin-bottom:12px;">'
        f'Probability of each exact scoreline. All market probabilities derived from this matrix.</p>',
        unsafe_allow_html=True,
    )

    np.random.seed(7)
    matrix = np.random.dirichlet(np.ones(49), size=1).reshape(7, 7) * 0.85
    matrix[1][0] = 0.182  # 1-0 most likely for strong home side
    matrix[2][0] = 0.124  # 2-0
    matrix[2][1] = 0.108  # 2-1
    matrix[1][1] = 0.079  # 1-1

    labels = [str(i) for i in range(7)]
    fig_mat = go.Figure(data=go.Heatmap(
        z=matrix * 100,
        x=[f"Away {g}" for g in labels],
        y=[f"Home {g}" for g in labels],
        colorscale=[[0, SURFACE], [0.5, "#1f4e2e"], [1, GREEN]],
        text=[[f"{v:.1f}%" for v in row] for row in matrix * 100],
        texttemplate="%{text}",
        textfont=dict(family="JetBrains Mono", size=11, color=TEXT),
        showscale=False,
    ))
    fig_mat.update_layout(
        paper_bgcolor=BG, plot_bgcolor=BG,
        font=dict(family="JetBrains Mono", color=TEXT, size=11),
        margin=dict(l=0, r=0, t=20, b=0),
        height=340,
    )
    st.plotly_chart(fig_mat, use_container_width=True)

    # Market probabilities
    st.divider()
    section_header("Derived Market Probabilities")

    markets = [
        ("Home Win (Arsenal)",  0.623, 2.10, 0.476, 0.147, "high"),
        ("Draw",                0.198, 3.60, 0.278, -0.080, "low"),
        ("Away Win (Brighton)", 0.179, 4.20, 0.238, -0.059, "low"),
        ("Over 2.5 Goals",      0.614, 1.83, 0.546, 0.068, "medium"),
        ("BTTS Yes",            0.512, 1.74, 0.575, -0.063, "low"),
    ]
    for label, model_p, odds, impl_p, edge, conf in markets:
        edge_col = GREEN if edge > 0.05 else YELLOW if edge > 0 else RED
        value_badge = _badge_pill("VALUE", GREEN) if edge > 0.05 else ""
        st.markdown(
            f'<div class="bv-card" style="display:flex;justify-content:space-between;align-items:center;padding:10px 16px;">'
            f'<span style="font-family:Inter,sans-serif;font-size:14px;color:{TEXT};flex:1;">{label}</span>'
            f'<div style="display:flex;gap:20px;align-items:center;">'
            f'<div style="text-align:right;"><div style="font-size:10px;color:{MUTED};">MODEL</div>'
            f'<div style="font-family:JetBrains Mono,monospace;color:{TEXT};">{model_p:.1%}</div></div>'
            f'<div style="text-align:right;"><div style="font-size:10px;color:{MUTED};">ODDS</div>'
            f'<div style="font-family:JetBrains Mono,monospace;color:{TEXT};">{odds:.2f}</div></div>'
            f'<div style="text-align:right;"><div style="font-size:10px;color:{MUTED};">IMPLIED</div>'
            f'<div style="font-family:JetBrains Mono,monospace;color:{TEXT};">{impl_p:.1%}</div></div>'
            f'<div style="text-align:right;min-width:70px;">'
            f'<div style="font-size:10px;color:{MUTED};">EDGE</div>'
            f'<div style="font-family:JetBrains Mono,monospace;font-weight:700;color:{edge_col};">'
            f'{edge:+.1%}</div></div>'
            f'{value_badge}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Narrative
    st.divider()
    section_header("Model Narrative")
    st.markdown(
        f'<div class="bv-card" style="font-family:Inter,sans-serif;font-size:14px;color:{MUTED};line-height:1.7;">'
        f'<p><strong style="color:{TEXT};">Form & Momentum:</strong> Arsenal enter this fixture unbeaten in 5 EPL home '
        f'games (W5 D0 L0), outscoring opponents 14-2. Their NPxG differential of +0.99 per 90 (2nd in league) '
        f'reflects sustained attacking dominance beyond lucky finishes.</p>'
        f'<p><strong style="color:{TEXT};">Defensive Concern for Brighton:</strong> Brighton\'s xGA away stands at 1.81 '
        f'per 90 — 14th in the league away from home. Their high defensive line (PPDA 8.1) is typically effective '
        f'against mid-table sides but creates vulnerability to Arsenal\'s pressing triggers.</p>'
        f'<p><strong style="color:{TEXT};">Elo Rating Gap:</strong> Arsenal Elo 1842 vs Brighton 1647 — a differential '
        f'of 195 points, corresponding to roughly 78% expected win probability for a neutral venue. Home advantage '
        f'adjusts this upward to ~82%.</p>'
        f'<p><strong style="color:{TEXT};">Weather:</strong> Forecast dry, 12°C, wind 8 km/h. No weather discount applied.</p>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar navigation
# ─────────────────────────────────────────────────────────────────────────────

PAGES = {
    "📅  Fixtures":           page_fixtures,
    "🎯  Today's Picks":      page_picks,
    "📈  Performance":        page_performance,
    "🏟️  League Explorer":    page_leagues,
    "🔬  Model Health":       page_model_health,
    "💰  Bankroll Manager":   page_bankroll,
    "🔍  Match Deep Dive":    page_deep_dive,
}

# Sidebar — persistent logo (expanded = wordmark, collapsed = V icon)
st.logo(image=_LOGO_WORDMARK, icon_image=_LOGO_ICON, size="large")

with st.sidebar:
    st.markdown(
        f'<p class="text-muted" style="font-size:12px;">Quantitative edge in football betting</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="demo-banner" style="font-size:11px;margin-top:4px;">DEMO MODE</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    page_name = st.radio(
        "Navigate",
        list(PAGES.keys()),
        label_visibility="collapsed",
    )

# Centred wordmark at top of every page, then render content
render_page_logo()
PAGES[page_name]()
