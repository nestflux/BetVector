"""WC accumulator (parlay) tracker (WC-ACC-01) — combined odds, all-legs-must-win
settlement, void-drops-out, log validation, read-time display, user-scoping.

The pure money math is unit-tested directly; log / settle / load run over an
in-memory DB. Leg settlement reuses betting.tracker._did_bet_win, so a leg settles
exactly like a single WC bet.
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
    accumulator_effective_odds, accumulator_odds, accumulator_pnl,
    accumulator_status, load_wc_accumulators, log_wc_accumulator,
    settle_wc_accumulators,
)
from src.world_cup.models import WCAccaLeg, WCAccumulator, WCMatch, WCTeam  # noqa: E402


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


def _leg(match_id, market_type, selection, odds, **extra):
    d = {"match_id": match_id, "market_type": market_type,
         "selection": selection, "odds": odds}
    d.update(extra)
    return d


# ---- pure money math --------------------------------------------------------

def test_accumulator_odds_is_product():
    assert accumulator_odds([2.0, 3.0]) == 6.0
    assert accumulator_odds([1.5, 2.0, 4.0]) == 12.0
    assert accumulator_odds([]) == 1.0            # neutral


def test_accumulator_status_all_cases():
    assert accumulator_status(["won", "won"]) == "won"
    assert accumulator_status(["won", "lost"]) == "lost"      # one loss kills it
    assert accumulator_status(["lost", "pending"]) == "lost"  # locked lost while open
    assert accumulator_status(["won", "pending"]) == "pending"
    assert accumulator_status(["won", "void"]) == "won"       # void drops out
    assert accumulator_status(["void", "void"]) == "void"     # nothing left to win
    assert accumulator_status([]) == "void"


def test_effective_odds_excludes_non_winners():
    # only WON legs multiply; void/lost/pending excluded
    assert accumulator_effective_odds([2.0, 3.0], ["won", "won"]) == 6.0
    assert accumulator_effective_odds([2.0, 4.0, 1.5],
                                      ["won", "void", "won"]) == 3.0
    assert accumulator_effective_odds([2.0, 3.0], ["void", "void"]) == 1.0


def test_accumulator_pnl_math():
    # all win: stake * (combined - 1)
    assert accumulator_pnl("won", 10.0, [2.0, 3.0], ["won", "won"]) == 50.0
    # one loss: -stake
    assert accumulator_pnl("lost", 10.0, [2.0, 3.0], ["won", "lost"]) == -10.0
    # void leg drops out -> payout recomputed on the survivors only
    assert accumulator_pnl("won", 10.0, [2.0, 4.0, 1.5],
                           ["won", "void", "won"]) == 20.0   # eff 3.0 -> 10*(3-1)
    # all void / pending -> stake returned (0 profit)
    assert accumulator_pnl("void", 10.0, [2.0, 3.0], ["void", "void"]) == 0.0
    assert accumulator_pnl("pending", 10.0, [2.0, 3.0], ["won", "pending"]) == 0.0


# ---- log validation ---------------------------------------------------------

def test_log_valid_accumulator(db):
    m1, m2 = _match(db), _match(db)
    aid = log_wc_accumulator(1, [_leg(m1, "1X2", "home", 2.0),
                                 _leg(m2, "OU25", "over", 1.8)], 10.0)
    assert isinstance(aid, int)
    with db() as s:
        acca = s.get(WCAccumulator, aid)
        assert acca.combined_odds == round(2.0 * 1.8, 4)   # frozen at log
        assert acca.status == "pending"
        assert len(acca.legs) == 2


def test_log_rejects_bad_slips(db):
    m1, m2 = _match(db), _match(db)
    good = _leg(m1, "1X2", "home", 2.0)
    assert log_wc_accumulator(1, [good], 10.0) is None                  # < 2 legs
    assert log_wc_accumulator(1, [], 10.0) is None                      # no legs
    assert log_wc_accumulator(1, [good, _leg(m2, "1X2", "home", 2.0)], 0) is None  # stake
    # one bad leg rejects the whole slip (all-or-nothing)
    assert log_wc_accumulator(1, [good, _leg(m2, "1X2", "over", 2.0)], 10.0) is None
    assert log_wc_accumulator(1, [good, _leg(m2, "1X2", "home", 1.0)], 10.0) is None  # odds
    assert log_wc_accumulator(1, [good, _leg(99999, "1X2", "home", 2.0)], 10.0) is None  # match
    # none of the rejected slips persisted
    with db() as s:
        assert s.query(WCAccumulator).count() == 0
        assert s.query(WCAccaLeg).count() == 0


# ---- settlement -------------------------------------------------------------

def test_settle_all_win_pays_combined(db):
    m1 = _match(db, status="finished", home_goals=2, away_goals=0)   # home wins
    m2 = _match(db, status="finished", home_goals=3, away_goals=1)   # over 2.5 wins
    aid = log_wc_accumulator(1, [_leg(m1, "1X2", "home", 2.0),
                                 _leg(m2, "OU25", "over", 3.0)], 10.0)
    assert settle_wc_accumulators() == 1
    with db() as s:
        acca = s.get(WCAccumulator, aid)
        assert acca.status == "won"
        assert acca.pnl == 50.0                       # 10 * (2.0*3.0 - 1)
        assert all(leg.status == "won" for leg in acca.legs)


def test_settle_one_loss_kills_bet(db):
    m1 = _match(db, status="finished", home_goals=2, away_goals=0)   # home wins
    m2 = _match(db, status="finished", home_goals=0, away_goals=1)   # home LOSES
    aid = log_wc_accumulator(1, [_leg(m1, "1X2", "home", 2.0),
                                 _leg(m2, "1X2", "home", 3.0)], 10.0)
    assert settle_wc_accumulators() == 1
    with db() as s:
        acca = s.get(WCAccumulator, aid)
        assert acca.status == "lost" and acca.pnl == -10.0


def test_settle_pending_until_all_resolve(db):
    m1 = _match(db, status="finished", home_goals=2, away_goals=0)
    m2 = _match(db, status="scheduled")                  # not played yet
    aid = log_wc_accumulator(1, [_leg(m1, "1X2", "home", 2.0),
                                 _leg(m2, "1X2", "home", 3.0)], 10.0)
    assert settle_wc_accumulators() == 0                 # one leg still open
    assert load_wc_accumulators(1)[0]["status"] == "pending"
    # finish the second leg -> now it settles
    with db() as s:
        m = s.get(WCMatch, m2)
        m.status, m.home_goals, m.away_goals = "finished", 1, 0
        s.commit()
    assert settle_wc_accumulators() == 1
    with db() as s:
        assert s.get(WCAccumulator, aid).status == "won"


def test_settle_idempotent(db):
    m1 = _match(db, status="finished", home_goals=2, away_goals=0)
    m2 = _match(db, status="finished", home_goals=1, away_goals=1)   # draw
    log_wc_accumulator(1, [_leg(m1, "1X2", "home", 2.0),
                           _leg(m2, "1X2", "draw", 3.2)], 10.0)
    assert settle_wc_accumulators() == 1
    assert settle_wc_accumulators() == 0                 # nothing left pending


def test_settle_void_leg_drops_out(db):
    m1 = _match(db, status="finished", home_goals=2, away_goals=0)   # home wins
    m2 = _match(db, status="finished", home_goals=1, away_goals=0)   # under 2.5 wins
    m3 = _match(db, status="void")                                   # abandoned -> void
    aid = log_wc_accumulator(1, [_leg(m1, "1X2", "home", 2.0),
                                 _leg(m2, "OU25", "under", 1.5),
                                 _leg(m3, "1X2", "home", 4.0)], 10.0)
    assert settle_wc_accumulators() == 1
    with db() as s:
        acca = s.get(WCAccumulator, aid)
        assert acca.status == "won"
        assert acca.combined_odds == round(2.0 * 1.5 * 4.0, 4)   # frozen incl. void leg
        assert acca.pnl == 20.0                                  # eff 2.0*1.5 -> 10*(3-1)
        statuses = sorted(leg.status for leg in acca.legs)
        assert statuses == ["void", "won", "won"]


def test_settle_no_accumulators_is_safe(db):
    assert settle_wc_accumulators() == 0                 # empty DB, never raises


# ---- read-time settlement + scoping ----------------------------------------

def test_load_settles_at_read_time_without_writing(db):
    m1 = _match(db, status="finished", home_goals=3, away_goals=1)
    m2 = _match(db, status="finished", home_goals=2, away_goals=2)   # BTTS yes
    aid = log_wc_accumulator(1, [_leg(m1, "OU25", "over", 1.8),
                                 _leg(m2, "BTTS", "yes", 1.9)], 10.0)
    acca = load_wc_accumulators(1)[0]                     # settle NOT called
    assert acca["status"] == "won"
    assert acca["pnl"] == round(10.0 * (1.8 * 1.9 - 1), 2)
    assert acca["effective_odds"] == round(1.8 * 1.9, 4)
    assert acca["n_legs"] == 2 and len(acca["legs"]) == 2
    with db() as s:                                       # read-time only — no write
        assert s.get(WCAccumulator, aid).status == "pending"


def test_load_user_scoping(db):
    m1, m2 = _match(db), _match(db)
    log_wc_accumulator(1, [_leg(m1, "1X2", "home", 2.0),
                           _leg(m2, "1X2", "away", 3.0)], 10.0)
    log_wc_accumulator(2, [_leg(m1, "1X2", "away", 2.5),
                           _leg(m2, "1X2", "home", 2.5)], 5.0)
    assert len(load_wc_accumulators(1)) == 1
    assert len(load_wc_accumulators(2)) == 1
    assert load_wc_accumulators(1)[0]["stake"] == 10.0


def test_load_leg_detail_carries_match_info(db):
    m1 = _match(db, status="finished", home_goals=2, away_goals=0)
    m2 = _match(db)
    log_wc_accumulator(1, [_leg(m1, "1X2", "home", 2.0, model_prob=0.55, edge=0.05),
                           _leg(m2, "OU25", "over", 1.8)], 10.0)
    legs = load_wc_accumulators(1)[0]["legs"]
    assert {leg["market_type"] for leg in legs} == {"1X2", "OU25"}
    first = next(leg for leg in legs if leg["market_type"] == "1X2")
    assert first["home"] and first["away"]                     # team names joined
    assert first["model_prob"] == 0.55 and first["edge"] == 0.05  # frozen at log
    assert first["market_label"] == "Match result"


# ---- table registration -----------------------------------------------------

def test_new_tables_registered_on_base():
    # create_all builds these on both SQLite (local) and Postgres (Neon)
    assert "wc_accumulator" in Base.metadata.tables
    assert "wc_acca_leg" in Base.metadata.tables
