"""WC knockout 90-minute (regulation) settlement — WC-ACC-02.

Bookmaker markets (1X2 / O-U / BTTS) settle on the 90-minute score, not extra time /
penalties. Tests the goal heuristic, the self-checked reconstruction from ESPN
keyEvents, settlement_score routing, the reconciler, and end-to-end that a KO won on
penalties settles a "home win" (single AND acca leg) as NOT won.
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
import src.world_cup.regulation as reg_mod  # noqa: E402
from src.world_cup.bets import (  # noqa: E402
    load_wc_accumulators, load_wc_bets, log_wc_accumulator, log_wc_bet,
    settle_wc_accumulators, settle_wc_bets, settlement_score,
)
from src.world_cup.regulation import (  # noqa: E402
    _detail_indicates_et, _is_goal, reconcile_knockout_regulation,
    reconstruct_regulation_score,
)
from src.world_cup.models import WCMatch, WCTeam  # noqa: E402


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


def _match(db, *, stage="group", status="finished", home_goals=None, away_goals=None,
           went_to_extra_time=0, home_goals_reg=None, away_goals_reg=None,
           home="Argentina", away="France", date="2026-07-05"):
    _SEQ[0] += 1
    mid = _SEQ[0]
    h, a = 100 + mid, 200 + mid
    with db() as s:
        s.add(WCTeam(id=h, name=home, fifa_code=f"H{mid % 99}",
                     confederation="UEFA", group_letter="A"))
        s.add(WCTeam(id=a, name=away, fifa_code=f"A{mid % 99}",
                     confederation="UEFA", group_letter="B"))
        s.add(WCMatch(id=mid, date=date, stage=stage, home_team_id=h, away_team_id=a,
                      status=status, home_goals=home_goals, away_goals=away_goals,
                      went_to_extra_time=went_to_extra_time,
                      home_goals_reg=home_goals_reg, away_goals_reg=away_goals_reg))
        s.commit()
    return mid


def _ke(period, team, ttype="Goal"):
    return {"period": {"number": period}, "team": {"displayName": team},
            "type": {"text": ttype}}


# ---- goal heuristic ---------------------------------------------------------

def test_is_goal_covers_subtypes_and_exclusions():
    assert _is_goal("Goal")
    assert _is_goal("Goal - Header")           # ESPN goal subtypes count
    assert _is_goal("Goal - Volley")
    assert _is_goal("Penalty - Scored")        # scored penalty in open play
    assert _is_goal("Own Goal")
    assert not _is_goal("Penalty - Missed")
    assert not _is_goal("Penalty - Saved")
    assert not _is_goal("Goal Disallowed")     # VAR-ruled-out — not a goal
    assert not _is_goal("Yellow Card")
    assert not _is_goal("Substitution")
    assert not _is_goal(None)


def test_detail_indicates_et():
    assert not _detail_indicates_et("FT")
    assert _detail_indicates_et("FT-Pens")
    assert _detail_indicates_et("AET")
    assert _detail_indicates_et("After Extra Time")
    assert not _detail_indicates_et(None)


# ---- reconstruction (mock keyEvents) ---------------------------------------

def _patch_keyevents(monkeypatch, events):
    monkeypatch.setattr(reg_mod, "_fetch_key_events", lambda _id: events)


def test_reconstruct_2022_final_shape(monkeypatch):
    # ARG 2-2 FRA at 90 (2 pens/goals each in reg), 3-3 after ET, pens excluded.
    events = [
        _ke(1, "Argentina", "Penalty - Scored"), _ke(1, "Argentina", "Goal"),
        _ke(2, "France", "Penalty - Scored"), _ke(2, "France", "Goal"),
        _ke(3, "Argentina", "Goal"), _ke(3, "France", "Penalty - Scored"),  # ET
        _ke(5, "Argentina", "Penalty - Scored"),  # shootout — excluded (period 5)
        _ke(5, "France", "Penalty - Scored"),
    ]
    _patch_keyevents(monkeypatch, events)
    assert reconstruct_regulation_score("X", "Argentina", "France", 3, 3) == (2, 2)


def test_reconstruct_self_check_fails_when_a_goal_type_missed(monkeypatch):
    # keyEvents only show 1 of the 2 official goals -> all-periods 1-0 != final 1-1 -> defer
    _patch_keyevents(monkeypatch, [_ke(2, "Argentina", "Goal")])
    assert reconstruct_regulation_score("X", "Argentina", "France", 1, 1) is None


def test_reconstruct_empty_keyevents_defers(monkeypatch):
    _patch_keyevents(monkeypatch, [])
    assert reconstruct_regulation_score("X", "Argentina", "France", 1, 1) is None


def test_reconstruct_all_regulation_no_et(monkeypatch):
    # both goals in regulation, none in ET -> reg == all == final
    _patch_keyevents(monkeypatch, [_ke(1, "Argentina", "Goal"),
                                   _ke(2, "France", "Goal - Header")])
    assert reconstruct_regulation_score("X", "Argentina", "France", 1, 1) == (1, 1)


# ---- settlement_score routing ----------------------------------------------

def test_settlement_score_group_uses_final(db):
    mid = _match(db, stage="group", home_goals=2, away_goals=1)
    with db() as s:
        assert settlement_score(s.get(WCMatch, mid)) == (2, 1)


def test_settlement_score_knockout_et_uses_regulation(db):
    mid = _match(db, stage="round_of_32", home_goals=2, away_goals=1,
                 went_to_extra_time=1, home_goals_reg=1, away_goals_reg=1)
    with db() as s:
        assert settlement_score(s.get(WCMatch, mid)) == (1, 1)  # 90-min draw


def test_settlement_score_et_unresolved_defers(db):
    mid = _match(db, stage="round_of_32", home_goals=2, away_goals=1,
                 went_to_extra_time=1, home_goals_reg=None, away_goals_reg=None)
    with db() as s:
        assert settlement_score(s.get(WCMatch, mid)) is None  # defer, don't guess


def test_settlement_score_unscored_is_none(db):
    mid = _match(db, stage="group", status="scheduled")
    with db() as s:
        assert settlement_score(s.get(WCMatch, mid)) is None


# ---- end-to-end: a KO won on pens settles on the 90-minute score ------------

def test_single_home_win_on_penalty_win_settles_lost(db):
    # 1-1 at 90 (reg), 2-1 after ET (final) — "home win" is a LOSER (90-min draw).
    mid = _match(db, stage="round_of_32", home_goals=2, away_goals=1,
                 went_to_extra_time=1, home_goals_reg=1, away_goals_reg=1)
    win_bet = log_wc_bet(1, mid, "1X2", "home", 2.5, 10.0)
    draw_bet = log_wc_bet(1, mid, "1X2", "draw", 3.2, 10.0)
    assert settle_wc_bets() == 2
    bets = {b["id"]: b for b in load_wc_bets(1)}
    assert bets[win_bet]["status"] == "lost"   # settled on the 90-minute draw
    assert bets[draw_bet]["status"] == "won"    # 1-1 at 90 minutes


def test_acca_leg_on_penalty_win_settles_on_90min(db):
    mid = _match(db, stage="round_of_16", home_goals=2, away_goals=1,
                 went_to_extra_time=1, home_goals_reg=1, away_goals_reg=1)
    other = _match(db, stage="group", home_goals=3, away_goals=0,
                   home="Brazil", away="Chile")
    aid = log_wc_accumulator(1, [
        {"match_id": mid, "market_type": "1X2", "selection": "home", "odds": 2.5},
        {"match_id": other, "market_type": "1X2", "selection": "home", "odds": 1.5},
    ], 10.0)
    assert settle_wc_accumulators() == 1
    acca = load_wc_accumulators(1)[0]
    assert acca["status"] == "lost"   # the KO leg lost at 90 min -> whole acca lost


def test_et_unresolved_leaves_bet_pending(db):
    mid = _match(db, stage="round_of_32", home_goals=2, away_goals=1,
                 went_to_extra_time=1)  # reg score NULL -> defer
    log_wc_bet(1, mid, "1X2", "home", 2.5, 10.0)
    assert settle_wc_bets() == 0
    assert load_wc_bets(1)[0]["status"] == "pending"


# ---- reconciler (mock ESPN) -------------------------------------------------

def _patch_espn(monkeypatch, events_for_date, key_events):
    monkeypatch.setattr(reg_mod, "fetch_espn_results_for_date",
                        lambda _d: events_for_date)
    monkeypatch.setattr(reg_mod, "_fetch_key_events", lambda _id: key_events)


def test_reconcile_sets_regulation_and_flag(monkeypatch, db):
    mid = _match(db, stage="round_of_32", home_goals=3, away_goals=3, date="2026-07-05")
    espn = [{"home_name": "Argentina", "away_name": "France", "home_goals": 3,
             "away_goals": 3, "date": "2026-07-05", "espn_event_id": "E1",
             "detail": "FT-Pens"}]
    key_events = [
        _ke(1, "Argentina", "Penalty - Scored"), _ke(1, "Argentina", "Goal"),
        _ke(2, "France", "Penalty - Scored"), _ke(2, "France", "Goal"),
        _ke(3, "Argentina", "Goal"), _ke(3, "France", "Goal"),  # ET
    ]
    _patch_espn(monkeypatch, espn, key_events)
    out = reconcile_knockout_regulation()
    assert out["extra_time"] == 1 and out["resolved"] == 1
    with db() as s:
        m = s.get(WCMatch, mid)
        assert m.went_to_extra_time == 1
        assert m.home_goals_reg == 2 and m.away_goals_reg == 2   # 90-min score
    # idempotent — a second run re-asserts the same values
    assert reconcile_knockout_regulation()["resolved"] == 1


def test_reconcile_regulation_match_flags_zero(monkeypatch, db):
    mid = _match(db, stage="round_of_32", home_goals=2, away_goals=1, date="2026-07-05")
    espn = [{"home_name": "Argentina", "away_name": "France", "home_goals": 2,
             "away_goals": 1, "date": "2026-07-05", "espn_event_id": "E2",
             "detail": "FT"}]                       # decided in 90
    _patch_espn(monkeypatch, espn, [])
    out = reconcile_knockout_regulation()
    assert out["extra_time"] == 0
    with db() as s:
        m = s.get(WCMatch, mid)
        assert m.went_to_extra_time == 0            # final IS the 90-min score
        assert settlement_score(m) == (2, 1)


def test_reconcile_defers_when_selfcheck_fails(monkeypatch, db):
    mid = _match(db, stage="round_of_32", home_goals=1, away_goals=1, date="2026-07-05")
    espn = [{"home_name": "Argentina", "away_name": "France", "home_goals": 1,
             "away_goals": 1, "date": "2026-07-05", "espn_event_id": "E3",
             "detail": "FT-Pens"}]
    _patch_espn(monkeypatch, espn, [_ke(2, "Argentina", "Goal")])  # only 1 of 2 goals
    out = reconcile_knockout_regulation()
    assert out["extra_time"] == 1 and out["deferred"] == 1 and out["resolved"] == 0
    with db() as s:
        m = s.get(WCMatch, mid)
        assert m.went_to_extra_time == 1
        assert m.home_goals_reg is None             # deferred — never guessed
        assert settlement_score(m) is None


def test_reconcile_ignores_group_matches(monkeypatch, db):
    _match(db, stage="group", home_goals=2, away_goals=2, date="2026-07-05")
    _patch_espn(monkeypatch, [], [])
    assert reconcile_knockout_regulation()["checked"] == 0   # group never reconciled


def test_reconcile_maps_flipped_orientation(monkeypatch, db):
    # our stored row has France at home; ESPN reports Argentina at home
    mid = _match(db, stage="round_of_32", home="France", away="Argentina",
                 home_goals=3, away_goals=3, date="2026-07-05")
    espn = [{"home_name": "Argentina", "away_name": "France", "home_goals": 3,
             "away_goals": 3, "date": "2026-07-05", "espn_event_id": "E4",
             "detail": "FT-Pens"}]
    key_events = [
        _ke(1, "Argentina", "Goal"), _ke(1, "Argentina", "Goal"),   # ARG 2 in reg
        _ke(2, "France", "Goal"),                                     # FRA 1 in reg
        _ke(3, "Argentina", "Goal"), _ke(3, "France", "Goal"), _ke(3, "France", "Goal"),
    ]  # all-periods ARG 3, FRA 3 == final; reg ARG 2, FRA 1
    _patch_espn(monkeypatch, espn, key_events)
    reconcile_knockout_regulation()
    with db() as s:
        m = s.get(WCMatch, mid)
        # stored home is France -> home_goals_reg should be France's 1, not Argentina's 2
        assert m.home_goals_reg == 1 and m.away_goals_reg == 2
