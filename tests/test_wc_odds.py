"""WC-ODDS-01 — bet-tracker odds lookup + bookmaker selection.

Read-only lookups map the tracker's markets (1X2 / O-U) onto the odds feed
(`h2h` / `totals` + point), pick a specific book or the best price, and expose the
book selector. Verified over an in-memory DB, plus shadow-safety (no writes) and the
view wiring for the auto-fill.
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
import src.database.models  # noqa: E402,F401
from src.database.db import Base  # noqa: E402
from src.world_cup.models import WCMatch, WCOdds, WCTeam  # noqa: E402
from src.world_cup.tracker_odds import (  # noqa: E402
    _odds_market_for, default_bookmaker, wc_odds_books, wc_odds_lookup,
)


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


def _seed(db, odds_rows):
    """One match (Alpha v Beta) + odds rows [(book, market, selection, price, point)]."""
    with db() as s:
        s.add(WCTeam(id=1, name="Alpha", fifa_code="ALP", confederation="UEFA",
                     group_letter="A"))
        s.add(WCTeam(id=2, name="Beta", fifa_code="BET", confederation="UEFA",
                     group_letter="A"))
        s.add(WCMatch(id=1, date="2026-07-05", stage="round_of_32",
                      home_team_id=1, away_team_id=2, status="scheduled"))
        for book, mkt, sel, price, point in odds_rows:
            s.add(WCOdds(match_id=1, bookmaker=book, market_type=mkt,
                         selection=sel, odds_decimal=price, point=point))
        s.commit()


# ---- market map + default ---------------------------------------------------

def test_odds_market_for():
    assert _odds_market_for("1X2") == "h2h"
    assert _odds_market_for("OU25") == "totals"
    assert _odds_market_for("OU15") == "totals"
    assert _odds_market_for("BTTS") is None       # not stored in wc_odds
    assert _odds_market_for("QUALIFY") is None


def test_default_bookmaker_is_fanduel():
    assert default_bookmaker() == "FanDuel"       # config/settings.yaml


# ---- 1X2 lookup -------------------------------------------------------------

def test_lookup_1x2_book_and_best(db):
    _seed(db, [
        ("FanDuel", "h2h", "Alpha", 2.10, None),
        ("Unibet", "h2h", "Alpha", 2.30, None),   # best price for home
        ("FanDuel", "h2h", "Beta", 3.40, None),
        ("FanDuel", "h2h", "Draw", 3.20, None),
    ])
    assert wc_odds_lookup(1, "1X2", "home", "FanDuel") == {"odds": 2.10,
                                                           "bookmaker": "FanDuel"}
    assert wc_odds_lookup(1, "1X2", "home", None) == {"odds": 2.30,
                                                      "bookmaker": "Unibet"}   # best
    assert wc_odds_lookup(1, "1X2", "home", "Best price")["bookmaker"] == "Unibet"
    assert wc_odds_lookup(1, "1X2", "away", "FanDuel")["odds"] == 3.40
    assert wc_odds_lookup(1, "1X2", "draw", "FanDuel")["odds"] == 3.20


def test_lookup_missing_book_returns_none(db):
    _seed(db, [("FanDuel", "h2h", "Alpha", 2.10, None)])
    assert wc_odds_lookup(1, "1X2", "home", "Betfair") is None    # Betfair has no price
    assert wc_odds_lookup(1, "1X2", "draw", "FanDuel") is None     # no Draw row stored


# ---- O/U lookup (keyed by point) --------------------------------------------

def test_lookup_ou_by_point(db):
    # wc_odds unique key is (match, book, market, selection) — no point — so a book's
    # `totals` market carries ONE Over/Under at its main line (2.5). Alternate lines
    # live under `alternate_totals` (not pulled), so OU25 fills; OU15/OU35 don't.
    _seed(db, [
        ("FanDuel", "totals", "Over", 1.90, 2.5),
        ("FanDuel", "totals", "Under", 1.95, 2.5),
    ])
    assert wc_odds_lookup(1, "OU25", "over", "FanDuel")["odds"] == 1.90    # the 2.5 line
    assert wc_odds_lookup(1, "OU25", "under", "FanDuel")["odds"] == 1.95
    assert wc_odds_lookup(1, "OU15", "over", "FanDuel") is None            # line is 2.5
    assert wc_odds_lookup(1, "OU35", "over", "FanDuel") is None


def test_lookup_btts_qualify_none(db):
    _seed(db, [("FanDuel", "h2h", "Alpha", 2.10, None)])
    assert wc_odds_lookup(1, "BTTS", "yes", "FanDuel") is None
    assert wc_odds_lookup(1, "QUALIFY", "home", "FanDuel") is None


# ---- book selector ----------------------------------------------------------

def test_wc_odds_books_fanduel_first(db):
    _seed(db, [
        ("Unibet", "h2h", "Alpha", 2.3, None),
        ("FanDuel", "h2h", "Alpha", 2.1, None),
        ("Betfair", "totals", "Over", 1.9, 2.5),
    ])
    books = wc_odds_books(1)
    assert books[0] == "FanDuel"                        # default book first
    assert set(books) == {"FanDuel", "Unibet", "Betfair"}


# ---- shadow-safety + view wiring --------------------------------------------

def test_tracker_odds_is_read_only():
    src = (ROOT / "src" / "world_cup" / "tracker_odds.py").read_text()
    assert ".add(" not in src and ".commit(" not in src and ".merge(" not in src
    assert "select(WCOdds" in src                       # it only reads


def test_view_wires_odds_autofill():
    src = (ROOT / "src" / "delivery" / "views" / "world_cup.py").read_text()
    assert "def _book_options" in src and "def _suggest_odds" in src
    assert src.count('st.selectbox("Bookmaker"') >= 2   # log form + slip add-leg
    assert "wc_odds_lookup(" in src and "wc_odds_books(" in src
    compile(src, "world_cup.py", "exec")


# ============================================================================
# WC-ODDS-02 — on-demand BTTS auto-fetch (live, US-only, budget-guarded)
# ============================================================================
from src.world_cup.tracker_odds import (  # noqa: E402
    _below_budget_floor, _parse_btts, fetch_btts_odds, pick_btts,
)

# A realistic single-event odds payload (The Odds API /events/{id}/odds shape).
_EVENTS = [{"id": "evt1", "home_team": "Alpha", "away_team": "Beta"}]
_ODDS = {"bookmakers": [
    {"title": "FanDuel", "markets": [
        {"key": "h2h", "outcomes": [{"name": "Alpha", "price": 2.10}]},   # not btts
        {"key": "btts", "outcomes": [{"name": "Yes", "price": 1.80},
                                     {"name": "No", "price": 2.00}]}]},
    {"title": "DraftKings", "markets": [
        {"key": "btts", "outcomes": [{"name": "Yes", "price": 1.90},
                                     {"name": "No", "price": 1.95}]}]},
]}


class _FakeResp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


def _fake_get(events=None, odds=None, remaining="400", counter=None):
    """A stand-in for requests.get routing /events (free) vs /events/{id}/odds (paid)."""
    events = _EVENTS if events is None else events
    odds = _ODDS if odds is None else odds

    def _get(url, params=None, timeout=None):
        if url.endswith("/events"):
            return _FakeResp(200, events, {"x-requests-remaining": remaining})
        if "/events/" in url and url.endswith("/odds"):
            if counter is not None:
                counter["paid"] += 1
            return _FakeResp(200, odds)
        return _FakeResp(404, {})
    return _get


# ---- parse + pick (pure) ----------------------------------------------------

def test_parse_btts_extracts_only_btts():
    parsed = _parse_btts(_ODDS)
    assert parsed == {"FanDuel": {"yes": 1.80, "no": 2.00},
                      "DraftKings": {"yes": 1.90, "no": 1.95}}
    assert _parse_btts({}) == {}                     # empty payload -> {}


def test_parse_btts_skips_junk_prices():
    event = {"bookmakers": [
        {"title": "Book1", "markets": [
            {"key": "btts", "outcomes": [{"name": "Yes", "price": 1.85},
                                         {"name": "No", "price": 1.0},      # <= 1.0 -> drop
                                         {"name": "Draw", "price": 3.0}]}]},  # not yes/no
        {"title": "Blank", "markets": [
            {"key": "btts", "outcomes": [{"name": "No", "price": None}]}]},  # unusable -> book dropped
    ]}
    assert _parse_btts(event) == {"Book1": {"yes": 1.85}}


def test_pick_btts_specific_best_and_fallback():
    f = {"FanDuel": {"yes": 1.80, "no": 2.00},
         "DraftKings": {"yes": 1.90, "no": 1.95}}
    assert pick_btts(f, "yes", "FanDuel") == {"odds": 1.80, "bookmaker": "FanDuel"}
    assert pick_btts(f, "no", "FanDuel") == {"odds": 2.00, "bookmaker": "FanDuel"}
    assert pick_btts(f, "yes", None) == {"odds": 1.90, "bookmaker": "DraftKings"}   # best
    assert pick_btts(f, "yes", "Best price")["bookmaker"] == "DraftKings"
    # chosen book didn't quote BTTS -> fall back to the best price (with its book)
    assert pick_btts(f, "yes", "Unibet") == {"odds": 1.90, "bookmaker": "DraftKings"}


def test_pick_btts_none_when_side_unquoted():
    assert pick_btts({}, "yes", "FanDuel") is None
    assert pick_btts({"X": {"no": 2.0}}, "yes", "FanDuel") is None   # nobody quoted Yes


def test_below_budget_floor():
    assert _below_budget_floor("5") is True          # below the hard-stop (30)
    assert _below_budget_floor("30") is True          # at the floor -> stand down
    assert _below_budget_floor("400") is False        # ample budget
    assert _below_budget_floor(None) is False         # unknown -> don't block
    assert _below_budget_floor("n/a") is False


# ---- live fetch (mocked HTTP) ----------------------------------------------

def test_fetch_btts_odds_happy_path(db, monkeypatch):
    _seed(db, [("FanDuel", "h2h", "Alpha", 2.10, None)])   # a match to resolve
    import src.world_cup.tracker_odds as to
    monkeypatch.setattr(to, "_get_api_key", lambda: "KEY")
    counter = {"paid": 0}
    monkeypatch.setattr(to.requests, "get", _fake_get(counter=counter))
    fetched = fetch_btts_odds(1, region="us")
    assert fetched == {"FanDuel": {"yes": 1.80, "no": 2.00},
                       "DraftKings": {"yes": 1.90, "no": 1.95}}
    assert counter["paid"] == 1                       # exactly one paid (~1 credit) call


def test_fetch_btts_odds_budget_guard_skips_paid_call(db, monkeypatch):
    _seed(db, [("FanDuel", "h2h", "Alpha", 2.10, None)])
    import src.world_cup.tracker_odds as to
    monkeypatch.setattr(to, "_get_api_key", lambda: "KEY")
    counter = {"paid": 0}
    monkeypatch.setattr(to.requests, "get", _fake_get(remaining="5", counter=counter))
    assert fetch_btts_odds(1) == {}                   # budget below hard-stop -> stand down
    assert counter["paid"] == 0                       # the paid call was never made


def test_fetch_btts_odds_no_event_match(db, monkeypatch):
    _seed(db, [("FanDuel", "h2h", "Alpha", 2.10, None)])
    import src.world_cup.tracker_odds as to
    monkeypatch.setattr(to, "_get_api_key", lambda: "KEY")
    other = [{"id": "z", "home_team": "Zed", "away_team": "Yak"}]
    monkeypatch.setattr(to.requests, "get", _fake_get(events=other))
    assert fetch_btts_odds(1) == {}                   # no Odds-API event for this match


def test_fetch_btts_odds_no_api_key(db, monkeypatch):
    import src.world_cup.tracker_odds as to
    monkeypatch.setattr(to, "_get_api_key", lambda: "")
    assert fetch_btts_odds(1) == {}                   # no key -> no fetch, no crash


# ---- shadow-safety + view wiring (BTTS) -------------------------------------

def test_btts_fetch_never_writes_wc_odds():
    """The live BTTS path returns prices for DISPLAY ONLY — never persisted. Writing
    them to wc_odds would feed the value finder and start generating BTTS value picks."""
    src = (ROOT / "src" / "world_cup" / "tracker_odds.py").read_text()
    assert "WCOdds(" not in src                       # never instantiated for an insert
    assert ".add(" not in src and ".commit(" not in src and ".merge(" not in src


def test_view_wires_btts_autofetch():
    src = (ROOT / "src" / "delivery" / "views" / "world_cup.py").read_text()
    assert "def _btts_cached" in src and "CACHE_TTL_ODDS" in src
    assert "fetch_btts_odds" in src and "pick_btts(" in src
    assert 'market_type == "BTTS"' in src             # _suggest_odds routes BTTS live
    compile(src, "world_cup.py", "exec")
