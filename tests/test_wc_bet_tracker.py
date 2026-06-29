"""WC personal bet tracker (WC-BET-01) — log / settle / load / summary.

Settlement reuses betting.tracker._did_bet_win, so a few sanity outcomes plus the
WC-specific log validation, settlement, read-time display, user-scoping, and the
P&L summary math, all over an in-memory DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.database.db as db_mod  # noqa: E402
import src.database.models  # noqa: E402,F401  (register User/users table on Base)
from src.database.db import Base  # noqa: E402
from src.world_cup.bets import (  # noqa: E402
    bet_outcome, bet_pnl, is_valid_selection, load_wc_bets, log_wc_bet,
    settle_wc_bets, wc_bet_summary,
)
from src.world_cup.models import WCBetLog, WCMatch, WCTeam  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    orig_e, orig_f = db_mod._engine, db_mod._SessionFactory
    db_mod._engine, db_mod._SessionFactory = engine, Session
    try:
        yield Session
    finally:
        db_mod._engine, db_mod._SessionFactory = orig_e, orig_f


_SEQ = [0]


def _match(db, *, status="scheduled", home_goals=None, away_goals=None,
           date="2026-06-20"):
    _SEQ[0] += 1
    mid = _SEQ[0]
    h, a = 100 + mid, 200 + mid
    with db() as s:
        s.add(WCTeam(id=h, name=f"Home{mid}", fifa_code=f"H{mid % 99}",
                     confederation="UEFA", group_letter="A"))
        s.add(WCTeam(id=a, name=f"Away{mid}", fifa_code=f"A{mid % 99}",
                     confederation="UEFA", group_letter="A"))
        s.add(WCMatch(id=mid, date=date, home_team_id=h, away_team_id=a,
                      status=status, home_goals=home_goals, away_goals=away_goals))
        s.commit()
    return mid


# ---- pure helpers -----------------------------------------------------------

def test_bet_outcome_delegates_to_league_logic():
    assert bet_outcome("1X2", "home", 2, 0) is True
    assert bet_outcome("1X2", "draw", 1, 1) is True
    assert bet_outcome("1X2", "away", 0, 1) is True
    assert bet_outcome("OU25", "over", 2, 1) is True    # 3 goals
    assert bet_outcome("OU25", "under", 1, 1) is True   # 2 goals
    assert bet_outcome("OU15", "under", 1, 0) is True   # 1 goal
    assert bet_outcome("BTTS", "yes", 1, 2) is True
    assert bet_outcome("BTTS", "no", 0, 3) is True
    assert bet_outcome("1X2", "home", None, None) is None   # unscored -> void/pending


def test_bet_pnl():
    assert bet_pnl("won", 10.0, 2.5) == 15.0     # profit = 10*(2.5-1)
    assert bet_pnl("lost", 10.0, 2.5) == -10.0
    assert bet_pnl("void", 10.0, 2.5) == 0.0


def test_valid_selection():
    assert is_valid_selection("1X2", "home")
    assert not is_valid_selection("1X2", "over")
    assert not is_valid_selection("NOPE", "home")


# ---- log --------------------------------------------------------------------

def test_log_valid_bet(db):
    bid = log_wc_bet(1, _match(db), "1X2", "home", 2.10, 20.0, source="manual")
    assert isinstance(bid, int)


def test_log_rejects_bad_input(db):
    mid = _match(db)
    assert log_wc_bet(1, mid, "1X2", "over", 2.0, 10.0) is None   # bad selection
    assert log_wc_bet(1, mid, "NOPE", "home", 2.0, 10.0) is None  # bad market
    assert log_wc_bet(1, mid, "1X2", "home", 1.0, 10.0) is None   # odds must be > 1
    assert log_wc_bet(1, mid, "1X2", "home", 2.0, 0) is None      # stake must be > 0


# ---- settle -----------------------------------------------------------------

def test_settle_marks_won_lost_and_pnl(db):
    mid = _match(db, status="finished", home_goals=2, away_goals=0)
    win = log_wc_bet(1, mid, "1X2", "home", 2.0, 10.0)
    lose = log_wc_bet(1, mid, "1X2", "away", 3.0, 10.0)
    assert settle_wc_bets() == 2
    bets = {b["id"]: b for b in load_wc_bets(1)}
    assert bets[win]["status"] == "won" and bets[win]["pnl"] == 10.0
    assert bets[lose]["status"] == "lost" and bets[lose]["pnl"] == -10.0


def test_settle_leaves_unfinished_pending(db):
    log_wc_bet(1, _match(db, status="scheduled"), "1X2", "home", 2.0, 10.0)
    assert settle_wc_bets() == 0
    assert load_wc_bets(1)[0]["status"] == "pending"


def test_settle_idempotent(db):
    mid = _match(db, status="finished", home_goals=1, away_goals=1)
    log_wc_bet(1, mid, "1X2", "draw", 3.2, 10.0)
    assert settle_wc_bets() == 1
    assert settle_wc_bets() == 0    # nothing left pending


# ---- read-time settlement + scoping ----------------------------------------

def test_load_settles_at_read_time_without_writing(db):
    mid = _match(db, status="finished", home_goals=3, away_goals=1)
    bid = log_wc_bet(1, mid, "OU25", "over", 1.8, 10.0)   # 4 goals -> over wins
    b = load_wc_bets(1)[0]                                  # settle NOT called
    assert b["status"] == "won" and b["pnl"] == 8.0
    with db() as s:
        assert s.get(WCBetLog, bid).status == "pending"    # read-time only, no write


def test_user_scoping(db):
    mid = _match(db)
    log_wc_bet(1, mid, "1X2", "home", 2.0, 10.0)
    log_wc_bet(2, mid, "1X2", "away", 3.0, 10.0)
    assert len(load_wc_bets(1)) == 1 and len(load_wc_bets(2)) == 1
    assert load_wc_bets(1)[0]["selection"] == "home"


# ---- summary ----------------------------------------------------------------

def test_summary_math(db):
    m_win = _match(db, status="finished", home_goals=2, away_goals=0)
    m_lose = _match(db, status="finished", home_goals=0, away_goals=1)
    m_pend = _match(db, status="scheduled")
    log_wc_bet(1, m_win, "1X2", "home", 2.0, 10.0, source="research_card")  # +10
    log_wc_bet(1, m_lose, "1X2", "home", 2.0, 10.0, source="manual")        # -10
    log_wc_bet(1, m_pend, "1X2", "home", 2.0, 10.0)                          # pending
    s = wc_bet_summary(1)
    assert s["total"] == 3 and s["pending"] == 1 and s["settled"] == 2
    assert s["won"] == 1 and s["lost"] == 1
    assert s["net_pnl"] == 0.0 and s["staked_settled"] == 20.0
    assert s["roi"] == 0.0 and s["win_rate"] == 0.5
    assert s["advised_settled"] == 1 and s["advised_won"] == 1   # the research_card bet


# ---- view wiring (world_cup.py runs st.* at import → source + AST-exec) ------

HUB_SRC = (ROOT / "src" / "delivery" / "views" / "world_cup.py").read_text()


def test_my_bets_tab_wired():
    assert "🎟️ My Bets" in HUB_SRC                  # the tab label
    assert "def _render_my_bets" in HUB_SRC and "_render_my_bets()" in HUB_SRC
    assert "get_session_user_id()" in HUB_SRC        # user-scoped
    assert "log_wc_bet(" in HUB_SRC                   # the form logs a bet
    assert "load_wc_bets(" in HUB_SRC and "wc_bet_summary(" in HUB_SRC
    compile(HUB_SRC, "world_cup.py", "exec")


def test_bet_row_and_summary_helpers_render():
    import ast
    from html import escape as _esc
    ns = {
        "escape": _esc, "GREEN": "#3FB950", "RED": "#F85149", "TEXT": "#E6EDF3",
        "TEXT_DIM": "#8B949E", "BORDER": "#30363D", "SURFACE": "#161B22",
        "YELLOW": "#D29922", "ACCENT": "#58A6FF",
        "_SEL_LABELS": {"home": "Home", "over": "Over"},
        "_short_date": lambda s: s,
    }
    pure = {"_bet_row_html", "_bet_summary_html"}
    for node in ast.parse(HUB_SRC).body:
        if isinstance(node, ast.FunctionDef) and node.name in pure:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<wc>", "exec"), ns)

    won = ns["_bet_row_html"]({
        "status": "won", "pnl": 12.0, "source": "research_card", "home": "Brazil",
        "away": "Spain", "market_label": "Match result", "selection": "home",
        "bookmaker": "FanDuel", "date": "2026-06-20", "odds": 2.1, "stake": 10.0})
    assert "✓ won" in won and "+$12.00" in won and "🎯" in won and "Brazil v Spain" in won

    lost = ns["_bet_row_html"]({
        "status": "lost", "pnl": -10.0, "source": "manual", "home": "A", "away": "B",
        "market_label": "Over/Under 2.5", "selection": "over", "bookmaker": None,
        "date": "2026-06-20", "odds": 1.9, "stake": 10.0})
    assert "✗ lost" in lost and "🎯" not in lost    # manual bets carry no tip marker

    summ = ns["_bet_summary_html"]({
        "net_pnl": 25.0, "roi": 0.125, "win_rate": 0.6, "won": 3, "lost": 2,
        "void": 0, "staked_total": 200.0, "pending": 1})
    # "Net P&L" renders escaped as "Net P&amp;L" (correct) — assert on &-free tokens.
    assert "+$25.00" in summ and "ROI" in summ and "Win rate" in summ


# ---- WC-BET-03: log-from-advice (value-pick -> loggable bet) -----------------

def test_vb_to_canon_mapping():
    import ast
    ns = {"_VB_MARKET_MAP": {"h2h": "1X2", "totals": "OU25", "btts": "BTTS"}}
    for node in ast.parse(HUB_SRC).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_vb_to_canon":
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<wc>", "exec"), ns)
    f = ns["_vb_to_canon"]
    assert f("h2h", "home") == ("1X2", "home")
    assert f("h2h", "draw") == ("1X2", "draw")
    assert f("totals", "over") == ("OU25", "over")   # model prices only the 2.5 line
    assert f("totals", "under") == ("OU25", "under")
    assert f("btts", "yes") == ("BTTS", "yes")
    assert f("btts", "no") == ("BTTS", "no")
    assert f("h2h", "lay") is None        # unsupported selection
    assert f("spreads", "home") is None   # unsupported market
    assert f(None, None) is None


def test_log_from_advice_wired():
    assert "def _render_log_pick_control" in HUB_SRC
    assert "_render_log_pick_control(picks)" in HUB_SRC      # called under the value bets
    assert 'source="research_card"' in HUB_SRC               # tagged as a model tip
    assert "_vb_to_canon(" in HUB_SRC                         # picks mapped to canonical
    assert "get_session_user_id()" in HUB_SRC                # user-scoped
